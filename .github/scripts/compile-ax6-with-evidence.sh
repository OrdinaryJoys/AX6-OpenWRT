#!/usr/bin/env bash
# Compile in the caller's OpenWrt tree; preserve BOTH attempts and tee failures.
set -euo pipefail

jobs=${1:?usage: bash compile-ax6-with-evidence.sh JOBS NEW_EVIDENCE_DIR}
output_dir=${2:?usage: bash compile-ax6-with-evidence.sh JOBS NEW_EVIDENCE_DIR}
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || { echo 'invalid compile job count' >&2; exit 2; }
test ! -e "$output_dir" && test ! -L "$output_dir" || {
    echo 'compile evidence directory must be new; preserve previous attempts' >&2
    exit 2
}
mkdir -p "$output_dir"

MAKE_RC=0
TEE_RC=0
run_attempt() {
    local kind=$1 threads=$2
    local -a results
    printf '{"event":"begin","attempt":"%s","jobs":%s,"utc":"%s"}\n' \
        "$kind" "$threads" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$output_dir/attempts.jsonl"
    if make -j"$threads" V=s 2>&1 | tee "$output_dir/compile-$kind.log"; then
        results=("${PIPESTATUS[@]}")
    else
        results=("${PIPESTATUS[@]}")
    fi
    MAKE_RC=${results[0]}
    TEE_RC=${results[1]}
    printf '{"event":"end","attempt":"%s","make_rc":%s,"tee_rc":%s,"utc":"%s"}\n' \
        "$kind" "$MAKE_RC" "$TEE_RC" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$output_dir/attempts.jsonl"
    # Lost evidence is a hard failure, not a reason to retry compilation blindly.
    if [ "$TEE_RC" -ne 0 ]; then
        echo "compile evidence writer failed: $TEE_RC" >&2
        exit "$TEE_RC"
    fi
}

run_attempt parallel "$jobs"
parallel_rc=$MAKE_RC
if [ "$parallel_rc" -eq 0 ]; then
    printf '{"event":"summary","parallel_rc":0,"serial_rc":null,"overall_rc":0}\n' \
        >> "$output_dir/attempts.jsonl"
    exit 0
fi

echo "::warning::Parallel compilation exited $parallel_rc; preserving evidence and retrying serially once"
run_attempt serial 1
printf '{"event":"summary","parallel_rc":%s,"serial_rc":%s,"overall_rc":%s}\n' \
    "$parallel_rc" "$MAKE_RC" "$MAKE_RC" >> "$output_dir/attempts.jsonl"
exit "$MAKE_RC"
