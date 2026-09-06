from redis.cluster import RedisCluster, ClusterNode
from redis.exceptions import RedisClusterException, ConnectionError

try:
    # Список начальных нод
    startup_nodes = [
        ClusterNode(host="redis-node-1", port=7000),
        ClusterNode(host="redis-node-2", port=7001),
        ClusterNode(host="redis-node-3", port=7002),
        ClusterNode(host="redis-node-4", port=7003),
        ClusterNode(host="redis-node-5", port=7004),
        ClusterNode(host="redis-node-6", port=7005),
    ]

    # Подключение к кластеру
    rc = RedisCluster(startup_nodes=startup_nodes, decode_responses=True)

    # Пример записи и чтения
    rc.set("key", "value")
    print(rc.get("key"))  # Выведет: value

except (RedisClusterException, ConnectionError) as e:
    print(f"Ошибка подключения или работы с кластером: {e}")
finally:
    rc.close()