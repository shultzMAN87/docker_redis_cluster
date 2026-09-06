"""Тот же пример, но настоящим кластерным клиентом, без прокси.

Запускается ТОЛЬКО внутри docker-сети: RedisCluster следует за
редиректами MOVED, а те указывают на внутренние адреса нод,
недостижимые с хоста.

    docker compose --profile client up -d
    docker compose exec client python /app/main_native.py

Сравните с main.py: здесь клиент обязан быть кластерным, зато видит
настоящую семантику кластера, включая ошибки CROSSSLOT.
"""

import sys

from redis.cluster import ClusterNode, RedisCluster
from redis.exceptions import RedisClusterException, RedisError

NODES = [
    ("redis-node-1", 7000),
    ("redis-node-2", 7001),
    ("redis-node-3", 7002),
    ("redis-node-4", 7003),
    ("redis-node-5", 7004),
    ("redis-node-6", 7005),
]


def main() -> int:
    print("Подключаюсь напрямую к нодам внутри docker-сети")

    cluster = None
    try:
        cluster = RedisCluster(
            startup_nodes=[ClusterNode(host=h, port=p) for h, p in NODES],
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )

        cluster.set("greeting", "Привет из Redis Cluster")
        print(f"greeting = {cluster.get('greeting')}")

        print()
        print("Мастера кластера:")
        for node in cluster.get_primaries():
            print(f"  {node.host}:{node.port}")

        print()
        print("Межслотовый MGET настоящим кластерным клиентом:")
        try:
            cluster.mget(["alpha", "beta", "gamma"])
            print("  неожиданно отработал")
        except (RedisError, RedisClusterException) as error:
            print(f"  отказ: {error}")
        print()
        print("Через Envoy такой запрос прошёл бы - прокси разбил бы его")
        print("по нодам. Ценой потери атомарности.")

        cluster.delete("greeting")
        return 0

    except (RedisError, RedisClusterException) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        print("Запускать нужно внутри docker-сети, см. docstring.", file=sys.stderr)
        return 1
    finally:
        if cluster is not None:
            cluster.close()


if __name__ == "__main__":
    sys.exit(main())
