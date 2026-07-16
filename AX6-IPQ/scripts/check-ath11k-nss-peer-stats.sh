#!/bin/sh

set -eu

patch_file="${1:-}"

if [ -z "$patch_file" ] || [ ! -r "$patch_file" ]; then
    echo "usage: $0 <ath11k NSS interface patch>" >&2
    exit 64
fi

if ! grep -Fq '+	u64 tx_packets, tx_bytes, tx_dropped;' "$patch_file"; then
    echo "ath11k NSS peer stats must not initialize tx_dropped outside the peer loop" >&2
    exit 1
fi

awk '
    /^\+\tfor \(i = 0; i < stats->npeers; i\+\+\) \{/ {
        in_peer_loop = 1
        next
    }
    in_peer_loop && /^\+\t\ttx_dropped = 0;$/ {
        reset_line = NR
    }
    in_peer_loop && /^\+\t\tfor \(j = 0; j < NSS_WIFILI_TQM_RR_MAX; j\+\+\)$/ {
        sum_line = NR
    }
    in_peer_loop && /^\+\t\tpeer->nss.nss_stats->tx_failed \+= tx_dropped;$/ {
        add_line = NR
        exit
    }
    END {
        if (!reset_line || !sum_line || !add_line ||
            !(reset_line < sum_line && sum_line < add_line)) {
            print "ath11k NSS peer tx_dropped must reset before each peer drop sum" > "/dev/stderr"
            exit 1
        }
    }
' "$patch_file"

echo "ath11k NSS peer statistics gate: PASS"
