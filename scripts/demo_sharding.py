"""Демонстрация шардирования: как ключи разъезжаются по мастерам.

Показывает:
  1. слот ключа считается детерминированно от его имени;
  2. 1000 ключей делятся между тремя мастерами примерно поровну;
  3. нода отказывает в мультиключевой операции через границу слотов;
  4. hash tags кладут связанные ключи в один слот;
  5. Envoy это ограничение скрывает - и чем за это платит.

Запуск:  python scripts/demo_sharding.py
"""

from redis.exceptions import RedisError

from common import (any_node, cluster_roles, connect_node, connect_proxy,
                    keyslot, print_header)

TOTAL_KEYS = 1000
PREFIX = "demo:sharding"


def main() -> None:
    proxy = connect_proxy()

    print_header("1. Слот считается от имени ключа")
    print("  CRC16(key) mod 16384 - результат не зависит от того,")
    print("  к какой ноде вы обратились.")
    print()
    for key in (f"{PREFIX}:1", f"{PREFIX}:2", f"{PREFIX}:3", "user:100:name"):
        print(f"  {key:<24} -> слот {keyslot(key):>5}")

    print_header(f"2. Раскладываю {TOTAL_KEYS} ключей через Envoy")
    # transaction=False принципиально: это пакетная отправка без MULTI/EXEC.
    # Транзакция по ключам из разных слотов невозможна в принципе -
    # ни через прокси, ни без него.
    try:
        pipe = proxy.pipeline(transaction=False)
        for number in range(TOTAL_KEYS):
            pipe.set(f"{PREFIX}:{number}", number)
        pipe.execute()
    except RedisError:
        for number in range(TOTAL_KEYS):
            proxy.set(f"{PREFIX}:{number}", number)
    print(f"  записано {TOTAL_KEYS} ключей обычным клиентом Redis")
    print("  Envoy сам разослал их по нужным мастерам")

    print()
    print("  Сколько ключей осело на каждом мастере:")
    masters = [node for node in cluster_roles()
               if node["role"] == "master" and not node["failed"]]
    for node in masters:
        size = connect_node(node["port"]).dbsize()
        print(f"    {node['service']:<13} :{node['port']}  {size:>5} ключей"
              f"   слоты {node['slots'] or '-'}")

    print_header("3. Что говорит сама нода на межслотовый запрос")
    scattered = [f"{PREFIX}:1", f"{PREFIX}:2", f"{PREFIX}:3"]
    for key in scattered:
        print(f"  {key:<24} слот {keyslot(key):>5}")
    print()
    print("  MGET по ним напрямую к ноде:")
    try:
        any_node().mget(scattered)
        print("    неожиданно отработал")
    except RedisError as error:
        print(f"    отказ: {error}")
    print()
    print("  Так и должно быть. Ключи лежат на разных нодах, и ни одна")
    print("  из них не может выполнить такой запрос целиком.")

    print_header("4. Hash tags: как положить ключи в один слот")
    print("  Часть имени в фигурных скобках берётся для расчёта слота,")
    print("  остальное игнорируется.")
    print()
    tagged = ["{user:100}:name", "{user:100}:email", "{user:100}:city"]
    for key in tagged:
        print(f"  {key:<24} слот {keyslot(key):>5}")

    proxy.mset({tagged[0]: "Иван", tagged[1]: "ivan@example.com", tagged[2]: "Москва"})
    print()
    print(f"  MGET по ним: {proxy.mget(tagged)}")
    print()
    print("  Один слот - значит одна нода, значит доступны транзакции,")
    print("  Lua-скрипты и любые мультиключевые команды.")

    print_header("5. Транзакция через границу слотов")
    print("  MULTI/EXEC по ключам из разных слотов - через Envoy:")
    try:
        pipe = proxy.pipeline(transaction=True)
        pipe.set(f"{PREFIX}:aaa", 1)
        pipe.set(f"{PREFIX}:bbb", 2)
        pipe.execute()
        print("    прошла")
    except RedisError as error:
        print(f"    отказ: {error}")
        print()
        print("    Число и адрес в конце - это редирект MOVED с отрезанным")
        print("    префиксом: 14522 - номер слота, дальше нода-владелец.")
        print("    Envoy не может перенаправить команду внутри MULTI и")
        print("    отдаёт ошибку клиенту как есть.")
    print()
    print("  То же самое, но с общим hash tag:")
    try:
        pipe = proxy.pipeline(transaction=True)
        pipe.set("{order:7}:status", "new")
        pipe.set("{order:7}:total", 1500)
        pipe.execute()
        print("    прошла - оба ключа в одном слоте")
    except RedisError as error:
        print(f"    отказ: {error}")
    print()
    print("  Прокси здесь не помогает и помочь не может: атомарность")
    print("  обеспечивает нода, а ключи лежат на разных нодах.")

    print_header("6. А вот межслотовый MGET через Envoy проходит")
    try:
        values = proxy.mget(scattered)
        print(f"  результат: {values}")
        print()
        print("  Envoy разбил запрос по нодам и склеил ответы, поэтому")
        print("  клиент ограничения не увидел.")
    except RedisError as error:
        print(f"  отказ: {error}")

    print()
    print("  Разница с транзакцией принципиальная: MGET можно разбить")
    print("  на независимые запросы и склеить ответы, а MULTI/EXEC -")
    print("  нельзя. Поэтому чтение прокси спасает, а атомарность нет,")
    print("  и схему именования ключей приходится проектировать заранее.")

    print_header("Убираю за собой")
    removed = 0
    for number in range(TOTAL_KEYS):
        removed += proxy.delete(f"{PREFIX}:{number}")
    for key in tagged:
        removed += proxy.delete(key)
    for key in (f"{PREFIX}:aaa", f"{PREFIX}:bbb",
                "{order:7}:status", "{order:7}:total"):
        try:
            removed += proxy.delete(key)
        except RedisError:
            pass
    print(f"  удалено {removed} ключей")
    proxy.close()
    print()


if __name__ == "__main__":
    main()
