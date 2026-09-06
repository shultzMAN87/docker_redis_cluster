"""Подсказывает, какой HOST_IP положить в .env.

Запуск:  python scripts/detect_host_ip.py
"""

from common import detect_host_ip


def main() -> None:
    ip = detect_host_ip()
    print()
    print(f"IP этой машины в локальной сети: {ip}")
    print()
    print("Положите в файл .env рядом с compose.yml строку:")
    print()
    print(f"    HOST_IP={ip}")
    print()
    print("Если адрес выглядит неправдоподобно (127.0.0.1, 172.17.x.x,")
    print("адрес VPN или виртуального адаптера) - посмотрите вручную:")
    print("    Windows: ipconfig")
    print("    Linux:   ip -4 addr")
    print("    macOS:   ifconfig")
    print()
    print("Нужен адрес того интерфейса, через который машина видит")
    print("локальную сеть. Адрес docker-сети не подойдёт.")


if __name__ == "__main__":
    main()
