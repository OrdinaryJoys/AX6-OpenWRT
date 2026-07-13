#!/bin/sh

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERIFY="$ROOT/.github/scripts/verify-device-manifest.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

cat > "$TMP/status" <<'EOF'
Package: package-b
Version: 2.0-r1
Status: install ok installed

Package: package-a
Version: 1.0-r2
Status: install hold installed

Package: package-old
Version: 0.1
Status: deinstall ok config-files
EOF

cat > "$TMP/manifest" <<'EOF'
package-a - 1.0-r2
package-b - 2.0-r1
EOF

"$VERIFY" "$TMP/manifest" "$TMP/status"

cat > "$TMP/manifest-bad" <<'EOF'
package-a - 1.0-r2
package-b - 2.0-r2
EOF

if "$VERIFY" "$TMP/manifest-bad" "$TMP/status" >/dev/null 2>&1; then
	echo 'mismatched manifest unexpectedly passed' >&2
	exit 1
fi

if "$VERIFY" "$TMP/missing" "$TMP/status" >/dev/null 2>&1; then
	echo 'missing manifest unexpectedly passed' >&2
	exit 1
fi

echo 'device manifest tests: PASS'
