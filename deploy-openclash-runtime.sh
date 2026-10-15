#!/bin/sh
# Host-only staged restore. Default and --check never contact the router.
# Usage: ./deploy-openclash-runtime.sh --check BACKUP
# A separately approved maintenance window is required for --apply.
set -eu
umask 077
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
exec python3 -B "$SCRIPT_DIR/tools/ax6-openclash-restore.py" "$@"
