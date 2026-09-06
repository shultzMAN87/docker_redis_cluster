"""Демонстрация failover: что происходит при падении мастера.

Сценарий:
  1. показать текущие роли;
  2. записать контрольные ключи через Envoy;
  3. остановить один мастер;
  4. дождаться, пока его реплика заберёт слоты;
  5. убедиться, что данные на месте и клиент продолжает работать;
  6. вернуть остановленную ноду и проверить, что она реально поднялась.

Скрипт вызывает docker compose, поэтому запускать его нужно
на хосте из каталога проекта.

Запуск:  python scripts/demo_failover.py
"""

import subprocess
import sys
import time

from redis.exceptions import RedisError

from common import (PROJECT_ROOT, cluster_roles, connect_node, connect_proxy,
                    print_header)

WAIT_SECONDS = 90
PREFIX = "demo:failover"


def compose(*args: str) -> None:
    command = ["docker", "compose", *args]
    print(f"  $ {' '.join(command)}")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def show_roles() -> list:
    roles = cluster_roles()
    masters = {node["id"]: node for node in roles if node["role"] == "master"}
    for node in roles:
        mark = "  FAIL" if node["failed"] else ""
        if node["role"] == "master":
            print(f"  {node['service']:<13} :{node['port']}  мастер   "
                  f"слоты {node['slots'] or '-'}{mark}")
        else:
            owner = masters.get(node["master_id"])
            owner_text = f":{owner['port']}" if owner else "?"
            print(f"  {node['service']:<13} :{node['port']}  реплика  "
                  f"мастера {owner_text}{mark}")
    return roles


def node_answers(port: int) -> bool:
    """Прямая проверка: нода действительно обслуживает запросы."""
    try:
        return connect_node(port).ping() is True
    except (RedisError, OSError):
        return False


def wait_until(predicate, timeout: int, message: str) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except (RedisError, RuntimeError, OSError):
            pass
        print(f"    {message}")
        time.sleep(2)
    return False


def main() -> None:
    print_header("1. Текущее состояние")
    roles = show_roles()

    masters = [node for node in roles if node["role"] == "master" and not node["failed"]]
    if len(masters) < 3:
        sys.exit("\nКластер не в полном составе. Сначала: docker compose up -d")

    victim = masters[0]
    replica = next(
        (node for node in roles
         if node["role"] == "replica" and node["master_id"] == victim["id"]),
        None,
    )
    if replica is None:
        sys.exit(f"\nУ мастера :{victim['port']} нет реплики, демонстрация невозможна.")

    print()
    print(f"  Роняем мастер {victim['service']} (:{victim['port']})")
    print(f"  Его слоты должна забрать реплика :{replica['port']}")

    print_header("2. Пишу контрольные ключи через Envoy")
    proxy = connect_proxy()
    control = {}
    for number in range(200):
        key = f"{PREFIX}:{number}"
        proxy.set(key, f"value-{number}")
        control[key] = f"value-{number}"
    print(f"  записано {len(control)} ключей")

    print_header(f"3. Останавливаю {victim['service']}")
    compose("stop", victim["service"])

    print_header("4. Жду промоушена реплики")
    print("  cluster-node-timeout = 5000 мс, обычно занимает 5-15 секунд")

    promoted = wait_until(
        lambda: any(n["port"] == replica["port"] and n["role"] == "master"
                    for n in cluster_roles()),
        WAIT_SECONDS,
        "жду переизбрания...",
    )
    if not promoted:
        print()
        print(f"  !!! За {WAIT_SECONDS} секунд реплика не стала мастером.")
        print(f"  !!! Возвращаю {victim['service']} обратно.")
        compose("start", victim["service"])
        sys.exit(1)

    print()
    print(f"  Реплика :{replica['port']} стала мастером.")
    print()
    show_roles()

    print_header("5. Проверяю данные тем же клиентом")
    print("  Клиент не переподключался и ничего не знает о смене мастера -")
    print("  топологию обновил Envoy.")
    print()
    lost = 0
    for key, expected in control.items():
        try:
            if proxy.get(key) != expected:
                lost += 1
        except RedisError:
            lost += 1
    if lost:
        print(f"  потеряно или недоступно ключей: {lost} из {len(control)}")
        print("  репликация в Redis асинхронная, потери при failover возможны")
    else:
        print(f"  все {len(control)} ключей на месте")

    print_header(f"6. Возвращаю {victim['service']}")
    compose("start", victim["service"])
    print()
    print("  Жду, пока нода начнёт отвечать на PING")

    answers = wait_until(
        lambda: node_answers(victim["port"]),
        WAIT_SECONDS,
        "нода ещё не обслуживает запросы...",
    )

    if not answers:
        print()
        print(f"  !!! За {WAIT_SECONDS} секунд нода не начала отвечать.")
        print("  !!! Проверьте: docker compose ps")
        print(f"  !!! И логи: docker compose logs {victim['service']} --tail 30")
        sys.exit(1)

    print()
    print("  Нода отвечает. Жду, пока кластер снимет пометку FAIL")
    recovered = wait_until(
        lambda: any(n["port"] == victim["port"]
                    and not n["failed"]
                    and n["role"] == "replica"
                    for n in cluster_roles()),
        WAIT_SECONDS,
        "жду согласования ролей...",
    )

    print()
    show_roles()
    print()
    if recovered:
        print("  Вернувшаяся нода подключилась репликой к новому мастеру.")
        print("  Кластер сам перераспределил роли, вмешательства не потребовалось.")
    else:
        print(f"  Нода отвечает, но за {WAIT_SECONDS} секунд кластер не снял")
        print("  пометку FAIL. Проверьте: python scripts/cluster_info.py")

    print_header("Убираю за собой")
    removed = sum(proxy.delete(key) for key in control)
    print(f"  удалено {removed} ключей")
    proxy.close()
    print()


if __name__ == "__main__":
    main()
