"""Общие функции для демо-скриптов стенда.

Две точки входа с хоста, и это важно понимать:

  connect_node(port)  - напрямую к одной ноде (localhost:7000-7005).
                        Годится для диагностики: CLUSTER INFO, CLUSTER NODES,
                        DBSIZE, CLUSTER KEYSLOT, INFO. Эти команды выполняет
                        сама нода, редиректы не нужны.

  connect_proxy()     - через Envoy (localhost:6379). Годится для работы
                        с данными: Envoy держит у себя топологию кластера
                        и сам отрабатывает MOVED и ASK, поэтому клиент
                        может быть обычным, не кластерным.

Прямое обращение к ноде за чужим ключом вернёт MOVED на внутренний адрес
docker-сети, недостижимый с хоста. Это не поломка, а следствие того, что
ноды объявляют друг другу внутренние адреса - именно так шина кластера
и репликация остаются внутри сети.
"""

import os
import sys
from pathlib import Path

NODE_PORTS = (7000, 7001, 7002, 7003, 7004, 7005)

PROXY_PORT = 6379

# Порт -> имя сервиса в compose.yml.
PORT_TO_SERVICE = {
    7000: "redis-node-1",
    7001: "redis-node-2",
    7002: "redis-node-3",
    7003: "redis-node-4",
    7004: "redis-node-5",
    7005: "redis-node-6",
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def redis_host() -> str:
    """Хост, на котором опубликованы порты стенда."""
    return os.environ.get("REDIS_LAB_HOST", "127.0.0.1")


def _redis_class():
    try:
        from redis import Redis
    except ImportError:
        sys.exit("Не установлен пакет redis. Выполните: pip install -r requirements.txt")
    return Redis


def connect_node(port: int):
    """Прямое подключение к одной ноде, без кластерной логики."""
    Redis = _redis_class()
    return Redis(
        host=redis_host(),
        port=port,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )


def connect_proxy():
    """Подключение к кластеру через Envoy обычным клиентом."""
    Redis = _redis_class()
    return Redis(
        host=redis_host(),
        port=PROXY_PORT,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )


def keyslot(key: str) -> int:
    """Слот ключа. Считает сама нода командой CLUSTER KEYSLOT."""
    return int(any_node().execute_command("CLUSTER", "KEYSLOT", key))


def any_node():
    """Первая ответившая нода."""
    from redis import RedisError

    last_error = None
    for port in NODE_PORTS:
        try:
            node = connect_node(port)
            node.ping()
            return node
        except RedisError as error:
            last_error = error
    raise RuntimeError(f"Ни одна нода не ответила: {last_error}")


def cluster_roles() -> list:
    """Роли нод: список словарей с портом, ролью и id мастера."""
    raw = any_node().execute_command("CLUSTER", "NODES")

    result = []
    for line in str(raw).splitlines():
        parts = line.split()
        if len(parts) < 8:
            continue
        node_id, address, flags, master_id = parts[0], parts[1], parts[2], parts[3]
        endpoint = address.split("@")[0]
        try:
            node_port = int(endpoint.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            continue
        result.append(
            {
                "id": node_id,
                "port": node_port,
                "host": endpoint.rsplit(":", 1)[0],
                "role": "master" if "master" in flags else "replica",
                "master_id": None if master_id == "-" else master_id,
                "failed": "fail" in flags,
                "slots": " ".join(parts[8:]) if len(parts) > 8 else "",
                "service": PORT_TO_SERVICE.get(node_port, "?"),
            }
        )
    return sorted(result, key=lambda item: item["port"])


def print_header(text: str) -> None:
    print()
    print(text)
    print("-" * len(text))
