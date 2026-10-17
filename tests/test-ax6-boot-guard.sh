#!/bin/sh
set -eu
ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
# Stateful migration/idempotence plus read, mutation, commit and startup errors.
exec python3 "$ROOT/tests/test-startup-errors.py"
