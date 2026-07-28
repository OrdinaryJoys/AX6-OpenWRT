#!/bin/sh

set -eu

CLASSIFIER=${NSS_PBUF_CLASSIFIER:-./AX6-IPQ/files/usr/libexec/ax6-nss-pbuf-classify}
[ -x "$CLASSIFIER" ] || {
    echo "FAIL: pbuf classifier is missing or not executable: $CLASSIFIER" >&2
    exit 1
}

assert_result() {
    expected=$1
    shift
    actual=$($CLASSIFIER "$@")
    if [ "$actual" != "$expected" ]; then
        echo "FAIL: $*" >&2
        echo "  expected: $expected" >&2
        echo "  actual:   $actual" >&2
        exit 1
    fi
}

assert_result 'ok|1GB|10000000|65536|32768|98304' \
    1024 916088 10000000 65536 32768

assert_result 'warn|1GB|10000000|65536|32768|65536' \
    auto 916088 10002432 28672 36864

assert_result 'fail|1GB|10000000|65536|32768|65536' \
    1g 916088 9000000 28672 36864

assert_result 'invalid-values|1GB|10000000|65536|32768|' \
    1024 916088 invalid 65536 32768

assert_result 'invalid-values|1GB|10000000|65536|32768|' \
    1024 916088 '' 65536 32768

assert_result 'ok|512MB|8000000|32768|16384|49152' \
    auto 500000 8000000 32768 16384

assert_result 'ok|256MB|4000000|16384|8192|24576' \
    auto 250000 4000000 16384 8192

assert_result 'invalid-memory|||||' auto invalid 1 1 1
assert_result 'invalid-profile|||||' wrong 916088 1 1 1
assert_result 'disabled|||||' off 916088 '' '' ''

echo "test-pbuf-fixture: PASS"
