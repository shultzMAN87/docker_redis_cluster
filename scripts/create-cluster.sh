#!/bin/sh
# Собирает кластер из шести нод внутри docker-сети и проверяет результат.
#
# Все адреса - имена контейнеров, поэтому шина кластера и репликация
# никогда не выходят на хост. HOST_IP этому стенду не нужен.
#
# Идемпотентен: если кластер уже в рабочем состоянии, ничего не делает.
set -eu

NODES="redis-node-1:7000 redis-node-2:7001 redis-node-3:7002 redis-node-4:7003 redis-node-5:7004 redis-node-6:7005"
ENTRY="redis-node-1"
ENTRY_PORT=7000
CREATE_TIMEOUT=120
MAX_ATTEMPTS=3

entry_cli() {
    redis-cli -h "${ENTRY}" -p "${ENTRY_PORT}" "$@"
}

cluster_nodes() {
    for spec in ${NODES}; do
        host=${spec%%:*}
        port=${spec##*:}
        out=$(redis-cli -h "${host}" -p "${port}" cluster nodes 2>/dev/null) || continue
        if [ -n "${out}" ]; then
            echo "${out}"
            return 0
        fi
    done
    return 1
}

# Кластер готов, только если выполнено всё сразу:
# состояние ok, шесть нод, три мастера со слотами, три реплики.
cluster_ready() {
    info=$(entry_cli cluster info 2>/dev/null) || return 1
    echo "${info}" | grep -q "cluster_state:ok" || return 1

    known=$(echo "${info}" | grep "cluster_known_nodes:" | tr -d '\r' | cut -d: -f2)
    [ "${known}" = "6" ] || return 1

    nodes=$(cluster_nodes) || return 1
    masters=$(echo "${nodes}" | awk '$3 ~ /master/ && NF > 8' | wc -l | tr -d ' ')
    replicas=$(echo "${nodes}" | awk '$3 ~ /slave/' | wc -l | tr -d ' ')

    [ "${masters}" = "3" ] || return 1
    [ "${replicas}" = "3" ] || return 1
    return 0
}

report() {
    entry_cli cluster info 2>/dev/null \
        | grep -E "cluster_state|cluster_known_nodes|cluster_size" || true
}

wait_for_nodes() {
    echo "==> Проверяю доступность нод внутри docker-сети"
    for spec in ${NODES}; do
        host=${spec%%:*}
        port=${spec##*:}
        attempt=0
        until [ "$(redis-cli -h "${host}" -p "${port}" ping 2>/dev/null)" = "PONG" ]; do
            attempt=$((attempt + 1))
            if [ "${attempt}" -ge 30 ]; then
                echo "!!! Нода ${host}:${port} недоступна."
                exit 1
            fi
            echo "    жду ${host}:${port} (${attempt}/30)"
            sleep 1
        done
        echo "    ${host}:${port} - PONG"
    done
}

# Добивает ноды, до которых не дошёл MEET.
# Внутри сети это почти не встречается, но проверка дешёвая.
repair_membership() {
    nodes=$(cluster_nodes) || return 1
    missing=""
    for spec in ${NODES}; do
        port=${spec##*:}
        if ! echo "${nodes}" | grep -q ":${port}@"; then
            missing="${missing} ${spec}"
        fi
    done

    if [ -z "${missing}" ]; then
        return 0
    fi

    echo "==> В кластере не хватает нод:${missing}"
    for spec in ${missing}; do
        host=${spec%%:*}
        port=${spec##*:}
        bus=$((port + 10000))
        ip=$(getent hosts "${host}" | awk '{print $1}' | head -n 1)
        if [ -z "${ip}" ]; then
            echo "    не удалось определить адрес ${host}"
            continue
        fi
        echo "    зову ${host} (${ip}:${port}, шина ${bus})"
        entry_cli cluster meet "${ip}" "${port}" "${bus}" >/dev/null 2>&1 || true
    done

    attempt=0
    while [ "${attempt}" -lt 20 ]; do
        sleep 2
        known=$(entry_cli cluster info 2>/dev/null \
            | grep "cluster_known_nodes:" | tr -d '\r' | cut -d: -f2)
        if [ "${known}" = "6" ]; then
            echo "    все шесть нод в кластере"
            return 0
        fi
        attempt=$((attempt + 1))
    done
    echo "    не удалось собрать все шесть нод"
    return 1
}

# Делает репликами ноды, оставшиеся мастерами без слотов.
repair_replicas() {
    nodes=$(cluster_nodes) || return 1

    master_ids=$(echo "${nodes}" | awk '$3 ~ /master/ && NF > 8 {print $1}')
    orphans=$(echo "${nodes}" | awk '$3 ~ /master/ && NF <= 8 {print $2}')

    if [ -z "${orphans}" ]; then
        return 0
    fi
    if [ -z "${master_ids}" ]; then
        return 1
    fi

    echo "==> Назначаю реплики нодам без слотов"
    index=1
    for endpoint in ${orphans}; do
        addr=$(echo "${endpoint}" | sed 's/@.*//')
        target=$(echo "${master_ids}" | sed -n "${index}p")
        if [ -z "${target}" ]; then
            index=1
            target=$(echo "${master_ids}" | sed -n "1p")
        fi
        orphan_host=${addr%:*}
        orphan_port=${addr##*:}
        echo "    ${addr} -> реплика ${target}"
        redis-cli -h "${orphan_host}" -p "${orphan_port}" \
            cluster replicate "${target}" >/dev/null 2>&1 || true
        index=$((index + 1))
    done
    sleep 5
    return 0
}

reset_all() {
    echo "==> Сбрасываю состояние всех нод перед повторной попыткой"
    for spec in ${NODES}; do
        host=${spec%%:*}
        port=${spec##*:}
        redis-cli -h "${host}" -p "${port}" flushall >/dev/null 2>&1 || true
        redis-cli -h "${host}" -p "${port}" cluster reset hard >/dev/null 2>&1 || true
    done
    sleep 3
}

build_cluster() {
    echo "==> Собираю кластер: 3 мастера + 3 реплики"
    # shellcheck disable=SC2086
    timeout "${CREATE_TIMEOUT}" redis-cli --cluster create ${NODES} \
        --cluster-replicas 1 --cluster-yes || true
}

wait_for_nodes

if cluster_ready; then
    echo "==> Кластер уже собран и в порядке, ничего не делаю."
    report
    exit 0
fi

attempt=1
while [ "${attempt}" -le "${MAX_ATTEMPTS}" ]; do
    echo
    echo "===== Попытка ${attempt} из ${MAX_ATTEMPTS} ====="

    build_cluster

    echo "==> Проверяю состав кластера"
    repair_membership || true
    repair_replicas || true

    echo "==> Жду согласования состояния между нодами"
    settle=0
    while [ "${settle}" -lt 30 ]; do
        if cluster_ready; then
            echo
            echo "==> Готово"
            report
            exit 0
        fi
        settle=$((settle + 1))
        sleep 2
    done

    echo "!!! Кластер не пришёл в рабочее состояние."
    report

    attempt=$((attempt + 1))
    if [ "${attempt}" -le "${MAX_ATTEMPTS}" ]; then
        reset_all
    fi
done

echo
echo "!!! Не удалось собрать кластер за ${MAX_ATTEMPTS} попытки."
exit 1
