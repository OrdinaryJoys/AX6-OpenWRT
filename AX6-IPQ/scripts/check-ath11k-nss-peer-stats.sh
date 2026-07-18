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

git apply --numstat "$patch_file" >/dev/null || {
    echo "ath11k NSS interface patch is structurally invalid" >&2
    exit 1
}

patch_dir="$(dirname "$patch_file")"
wds_patch="$patch_dir/235-003-ath11k-add-AP_VLAN-vif-support-for-WDS-offload-in-NSS-offload.patch"
debug_patch="$patch_dir/999-921-ath11k-nss-expose-wifili-peer-stats-in-debugfs.patch"
for related_patch in "$wds_patch" "$debug_patch"; do
    [ -r "$related_patch" ] || {
        echo "required ath11k NSS peer statistics patch is missing: $related_patch" >&2
        exit 1
    }
    git apply --numstat "$related_patch" >/dev/null || {
        echo "ath11k NSS peer statistics patch is structurally invalid: $related_patch" >&2
        exit 1
    }
done

if ! grep -Fq '+	u32 tx_dropped;' "$patch_file"; then
    echo "ath11k NSS peer statistics must keep firmware queue drops separate" >&2
    exit 1
fi

if grep -Fq 'peer->nss.nss_stats->tx_failed += tx_dropped;' "$patch_file"; then
    echo "ath11k NSS firmware queue drops must not be reported as cfg80211 tx_failed" >&2
    exit 1
fi

grep -Fq 'peer->nss.nss_stats->tx_dropped += tx_dropped;' "$wds_patch" || {
    echo "ath11k NSS WDS patch context does not match the separated drop counter" >&2
    exit 1
}
if grep -Fq 'peer->nss.nss_stats->tx_failed += tx_dropped;' "$wds_patch"; then
    echo "ath11k NSS WDS patch restored the invalid tx_failed mapping" >&2
    exit 1
fi
grep -Fq '"tx_dropped %u\n", stats.tx_dropped' "$debug_patch" || {
    echo "ath11k NSS debugfs must expose firmware queue drops separately" >&2
    exit 1
}
if grep -Fq 'tx_failed_retries' "$debug_patch"; then
    echo "ath11k NSS debugfs must not duplicate the cfg80211 tx_failed counter" >&2
    exit 1
fi

awk '
    /^\+\+\+ b\/drivers\/net\/wireless\/ath\/ath11k\/nss\.c$/ {
        in_nss_file = 1
        next
    }
    in_nss_file && /^@@ -0,0 \+1,[0-9]+ @@$/ {
        declared = $0
        sub(/^.*\+1,/, "", declared)
        sub(/ .*/, "", declared)
        in_nss_hunk = 1
        next
    }
    in_nss_hunk && /^--- / {
        in_nss_hunk = 0
        in_nss_file = 0
        next
    }
    in_nss_hunk && /^\+/ && !/^\+\+\+/ {
        added++
        last_added = $0
    }
    END {
        if (!declared || added != declared || last_added != "+}") {
            print "ath11k NSS nss.c patch hunk length or closing brace is invalid" > "/dev/stderr"
            exit 1
        }
    }
' "$patch_file"

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
    in_peer_loop && /^\+\t\tpeer->nss.nss_stats->tx_dropped \+= tx_dropped;$/ {
        drop_line = NR
    }
    in_peer_loop && /^\+\t\tpeer->nss.nss_stats->tx_failed \+=$/ {
        failed_line = NR
    }
    in_peer_loop && /^\+\t\t\tpstats->retry.tx_failed_retry_count;$/ {
        failed_source_line = NR
        exit
    }
    END {
        if (!reset_line || !sum_line || !drop_line ||
            !failed_line || !failed_source_line ||
            !(reset_line < sum_line && sum_line < drop_line &&
              drop_line < failed_line && failed_line < failed_source_line)) {
            print "ath11k NSS peer drops and no-ACK failures must remain separate" > "/dev/stderr"
            exit 1
        }
    }
' "$patch_file"

echo "ath11k NSS peer statistics gate: PASS"
