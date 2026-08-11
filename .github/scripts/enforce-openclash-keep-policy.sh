#!/bin/sh
set -eu

usage() {
    echo "usage: $0 apply|check <OpenClash uci-defaults file>" >&2
    exit 2
}

[ "$#" -eq 2 ] || usage
mode=$1
target=$2
marker='cat > "/lib/upgrade/keep.d/luci-app-openclash" <<-EOF'

[ -f "$target" ] || {
    echo "OpenClash uci-defaults file is missing: $target" >&2
    exit 2
}

extract_policy() {
    awk -v marker="$marker" '
        $0 == marker {
            blocks++
            inside = 1
            next
        }
        inside && $0 == "EOF" {
            inside = 0
            closed++
            next
        }
        inside { print }
        END {
            if (inside || blocks != 1 || closed != 1)
                exit 2
        }
    ' "$1"
}

check_policy() {
    actual=$(extract_policy "$1") || {
        echo "OpenClash keep-policy heredoc is missing or ambiguous: $1" >&2
        return 2
    }
    expected=$(printf '%s\n' \
        /etc/openclash/config/ \
        /etc/openclash/custom/ \
        /etc/openclash/overwrite/)
    [ "$actual" = "$expected" ] || {
        echo "OpenClash first-boot keep policy is not config/custom/overwrite" >&2
        return 2
    }
}

case "$mode" in
    check)
        check_policy "$target"
        ;;
    apply)
        tmp=$(mktemp "${target}.ax6.XXXXXX")
        cleanup() {
            status=$?
            trap - EXIT HUP INT TERM
            rm -f "$tmp"
            exit "$status"
        }
        trap cleanup EXIT HUP INT TERM
        awk -v marker="$marker" '
            $0 == marker {
                blocks++
                print
                print "/etc/openclash/config/"
                print "/etc/openclash/custom/"
                print "/etc/openclash/overwrite/"
                closed = 0
                while ((getline line) > 0) {
                    if (line == "EOF") {
                        print line
                        closed = 1
                        break
                    }
                }
                if (!closed)
                    exit 2
                next
            }
            { print }
            END {
                if (blocks != 1 || !closed)
                    exit 2
            }
        ' "$target" > "$tmp" || {
            echo "Unable to rewrite OpenClash first-boot keep policy: $target" >&2
            exit 2
        }
        cat "$tmp" > "$target"
        check_policy "$target"
        ;;
    *)
        usage
        ;;
esac
