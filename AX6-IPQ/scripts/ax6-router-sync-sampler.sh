#!/bin/sh
# Read-only AX6 runtime sampler. It is streamed over SSH by the LAN-LAN
# runner, so it never needs to be installed on or write files to the router.

set -u

INTERVAL="${1:-2}"
SAMPLES="${2:-1}"

case "$INTERVAL" in ''|*[!0-9]*) exit 2 ;; esac
case "$SAMPLES" in ''|*[!0-9]*) exit 2 ;; esac
[ "$INTERVAL" -ge 1 ] && [ "$SAMPLES" -ge 1 ] || exit 2

BOOT_ID="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)"
printf '@@READY schema=ax6-sync-v1 interval_s=%s samples=%s boot_id=%s\n' \
    "$INTERVAL" "$SAMPLES" "$BOOT_ID"

emit() {
    printf '%s\t%s\t%s\t%s\t%s\n' \
        "$seq" "$epoch" "$uptime" "$1" "$2"
}

emit_nss_file() {
    prefix="$1"
    file="$2"
    pattern="$3"

    [ -r "$file" ] || return 0
    awk -F= -v prefix="$prefix" -v pattern="$pattern" '
        $1 ~ pattern {
            key=$1; value=$2
            gsub(/^[ \t]+|[ \t]+$/, "", key)
            gsub(/[^A-Za-z0-9_]+/, "_", key)
            gsub(/^[ \t]+/, "", value)
            sub(/[ \t]+.*$/, "", value)
            if (value ~ /^[0-9]+$/)
                print prefix "." key "\t" value
        }
    ' "$file" | while IFS="	" read -r metric value; do
        emit "$metric" "$value"
    done
}

emit_n2h_file() {
    file=/sys/kernel/debug/qca-nss-drv/stats/n2h
    [ -r "$file" ] || return 0
    awk -F= '
        /N2H [0-9]+/ {
            if (match($0, /N2H [0-9]+/))
                core=substr($0, RSTART + 4, RLENGTH - 4)
        }
        $1 ~ /n2h_(rx_queue.*drops|queue_drops|pbuf.*(free_count|alloc_fail)|payload_alloc_fails|n2h_enqueue_retries)/ {
            key=$1; value=$2
            gsub(/^[ \t]+|[ \t]+$/, "", key)
            gsub(/[^A-Za-z0-9_]+/, "_", key)
            gsub(/^[ \t]+/, "", value)
            sub(/[ \t]+.*$/, "", value)
            if (value ~ /^[0-9]+$/)
                print "nss.n2h.core" core "." key "\t" value
        }
    ' "$file" | while IFS="$(printf '\t')" read -r metric value; do
        emit "$metric" "$value"
    done
}

seq=0
while [ "$seq" -lt "$SAMPLES" ]; do
    epoch="$(date +%s)"
    sample_started="$epoch"
    uptime="$(cut -d' ' -f1 /proc/uptime 2>/dev/null)"
    printf '@@SAMPLE seq=%s epoch=%s uptime=%s\n' "$seq" "$epoch" "$uptime"

    if [ -r /proc/stat ]; then
        read -r _ user nice system idle iowait irq softirq steal _rest < /proc/stat
        emit cpu.user "$user"
        emit cpu.nice "$nice"
        emit cpu.system "$system"
        emit cpu.idle "$idle"
        emit cpu.iowait "$iowait"
        emit cpu.irq "$irq"
        emit cpu.softirq "$softirq"
        emit cpu.steal "$steal"
    fi

    for path in /proc/sys/dev/nss/n2hcfg/*; do
        [ -r "$path" ] || continue
        emit "pbuf.${path##*/}" "$(cat "$path")"
    done

    cpu=0
    while read -r processed dropped squeeze _rest; do
        emit "softnet.cpu${cpu}.processed_hex" "$processed"
        emit "softnet.cpu${cpu}.dropped_hex" "$dropped"
        emit "softnet.cpu${cpu}.time_squeeze_hex" "$squeeze"
        cpu=$((cpu + 1))
    done < /proc/net/softnet_stat

    grep -Ei 'edma_|nss_|nss-|ce[0-9]+|reo|wbm|ath11k' /proc/interrupts 2>/dev/null |
        while read -r irq c0 c1 c2 c3 _rest; do
            irq="${irq%:}"
            case "$irq" in ''|*[!0-9]*) continue ;; esac
            emit "irq.${irq}.cpu0" "$c0"
            emit "irq.${irq}.cpu1" "$c1"
            emit "irq.${irq}.cpu2" "$c2"
            emit "irq.${irq}.cpu3" "$c3"
            [ -r "/proc/irq/$irq/smp_affinity_list" ] &&
                emit "irq.${irq}.affinity" "$(cat "/proc/irq/$irq/smp_affinity_list")"
        done

    for dev in br-lan lan1 lan2 lan3 wan; do
        [ -d "/sys/class/net/$dev" ] || continue
        for counter in rx_bytes tx_bytes rx_packets tx_packets \
            rx_errors rx_dropped tx_errors tx_dropped; do
            path="/sys/class/net/$dev/statistics/$counter"
            [ -r "$path" ] && emit "net.${dev}.${counter}" "$(cat "$path")"
        done
        for path in "/sys/class/net/$dev"/queues/rx-*/rps_cpus \
            "/sys/class/net/$dev"/queues/rx-*/rps_flow_cnt \
            "/sys/class/net/$dev"/queues/tx-*/xps_cpus; do
            [ -r "$path" ] || continue
            value="$(cat "$path" 2>/dev/null)" || continue
            [ -n "$value" ] || continue
            queue="$(basename "$(dirname "$path")")"
            emit "queue.${dev}.${queue}.$(basename "$path")" "$value"
        done
    done

    emit_n2h_file
    emit_nss_file nss.drv /sys/kernel/debug/qca-nss-drv/stats/drv \
        'drv_(nbuf_alloc_errors|paged_buf_alloc_errors|tx_queue_full|rx_bad_desciptor|invalid_|tx_buffers_empty|rx_buffers_empty|tx_skb_fraglist|rx_skb_fraglist)'
    emit_nss_file nss.edma /sys/kernel/debug/qca-nss-drv/stats/edma/err_stats \
        'edma_err_'
    emit_nss_file nss.ppe /sys/kernel/debug/qca-nss-drv/stats/ppe/connection \
        '(routed flows|bridge flows|create fail|destroy fail|flow full|not responding)'

    for path in /proc/sys/dev/nss/clock/current_freq \
        /proc/sys/dev/nss/rps/enable; do
        [ -r "$path" ] || continue
        value="$(cat "$path" 2>/dev/null)" || continue
        [ -n "$value" ] && emit "nss.sysctl.${path##*/}" "$value"
    done

    printf '@@END_SAMPLE seq=%s\n' "$seq"
    seq=$((seq + 1))
    if [ "$seq" -lt "$SAMPLES" ]; then
        sample_elapsed=$(($(date +%s) - sample_started))
        sample_delay=$((INTERVAL - sample_elapsed))
        [ "$sample_delay" -gt 0 ] && sleep "$sample_delay"
    fi
done

printf '@@DONE samples=%s boot_id=%s\n' "$SAMPLES" "$BOOT_ID"
