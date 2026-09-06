"""Пример работы с кластером через Envoy - обычным клиентом Redis.

Главное здесь: класс Redis, а не RedisCluster. Прокси держит топологию
у себя и отрабатывает редиректы сам, поэтому приложению не нужна
кластерная библиотека и оно не знает о существовании шести нод.

Запуск с хоста:
    python app/main.py
"""

import os
import sys

from redis import Redis
from redis.exceptions import RedisError


def main() -> int:
    host = os.environ.get("REDIS_LAB_HOST", "127.0.0.1")
    port = int(os.environ.get("REDIS_LAB_PORT", "6379"))
    print(f"Подключаюсь через Envoy: {host}:{port}")

    client = None
    try:
        client = Redis(
            host=host,
            port=port,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )

        client.set("greeting", "Привет из Redis Cluster через Envoy")
        print(f"greeting = {client.get('greeting')}")

        # Ключи с одинаковым hash tag лежат в одном слоте, поэтому
        # к ним применимы мультиключевые операции по-настоящему.
        client.mset({
            "{user:100}:name": "Иван",
            "{user:100}:email": "ivan@example.com",
        })
        name, email = client.mget(["{user:100}:name", "{user:100}:email"])
        print(f"user:100 = {name}, {email}")

        client.delete("greeting", "{user:100}:name", "{user:100}:email")
        print()
        print("Клиент ни разу не упомянул кластер: ни списка нод,")
        print("ни обработки MOVED. Всё это взял на себя Envoy.")
        return 0

    except RedisError as error:
        print(f"Ошибка работы с Redis: {error}", file=sys.stderr)
        print(file=sys.stderr)
        print("Проверьте, что стенд поднят: docker compose ps", file=sys.stderr)
        print("И что Envoy готов: curl http://localhost:9901/ready", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
