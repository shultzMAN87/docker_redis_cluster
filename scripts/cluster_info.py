"""Состояние кластера одной командой.

Запуск:  python scripts/cluster_info.py
"""

from common import any_node, connect_node, cluster_roles, print_header, redis_host


def main() -> None:
    print(f"Кластер на {redis_host()}, порты нод 7000-7005, Envoy 6379")

    print_header("Общее состояние")
    info = any_node().execute_command("CLUSTER", "INFO")
    pairs = {}
    for line in str(info).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            pairs[key.strip()] = value.strip()

    for key in ("cluster_state", "cluster_slots_assigned", "cluster_known_nodes",
                "cluster_size", "cluster_current_epoch"):
        if key in pairs:
            print(f"  {key:<24} {pairs[key]}")

    print_header("Ноды")
    roles = cluster_roles()
    masters = {node["id"]: node for node in roles if node["role"] == "master"}

    for node in roles:
        mark = "  FAIL" if node["failed"] else ""
        if node["role"] == "master":
            print(f"  {node['service']:<13} :{node['port']}  мастер   "
                  f"слоты {node['slots'] or '-'}{mark}")
        else:
            owner = masters.get(node["master_id"])
            owner_text = f":{owner['port']}" if owner else str(node["master_id"])[:8]
            print(f"  {node['service']:<13} :{node['port']}  реплика  "
                  f"мастера {owner_text}{mark}")

    print_header("Ключей на каждом мастере")
    total = 0
    for node in roles:
        if node["role"] != "master" or node["failed"]:
            continue
        try:
            size = connect_node(node["port"]).dbsize()
        except Exception as error:
            print(f"  :{node['port']}  недоступна ({type(error).__name__})")
            continue
        total += size
        print(f"  :{node['port']}  {size}")
    print(f"  всего  {total}")
    print()


if __name__ == "__main__":
    main()
