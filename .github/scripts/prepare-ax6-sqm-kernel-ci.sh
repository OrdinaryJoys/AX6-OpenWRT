#!/usr/bin/env bash
# Explicit shared-kernel preparation, restricted to disposable GitHub runners.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_ENVIRONMENT:-}" == github-hosted ]] || {
  echo 'Refusing module preparation outside a GitHub-hosted Actions runner' >&2
  exit 2
}
[[ "$(uname -s)" == Linux && "$EUID" == 0 ]] || {
  echo 'Linux root preparation is required' >&2
  exit 2
}
command -v ip
command -v tc
command -v modprobe
command -v python3
uname -r
ip -Version
tc -Version
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
host_inventory() {
  # Filtered JSON can contain empty placeholders; obtain every real identity.
  local raw_links
  raw_links=$(ip -d -j link show) || return "$?"
  printf 'Host raw link inventory (%s): %s\n' "$1" "$raw_links" >&2
  printf '%s\n' "$raw_links" | python3 "$script_dir/ax6-sqm-link-inventory.py"
}
before_links=$(host_inventory before)
printf 'Host link inventory before: %s\n' "$before_links"
if [[ -d /sys/module/ifb ]]; then
  echo 'IFB module already prepared; existing host devices remain untouched'
else
  # The module default numifbs=2 would create legacy devices in init_net.
  modprobe ifb numifbs=0
fi
modprobe sch_cake
[[ -d /sys/module/ifb && -d /sys/module/sch_cake ]] || {
  echo 'Required IFB/CAKE modules are unavailable' >&2
  exit 2
}
after_links=$(host_inventory after)
printf 'Host link inventory after: %s\n' "$after_links"
[[ "$before_links" == "$after_links" ]] || {
  echo 'Preparation unexpectedly changed host link inventory' >&2
  exit 1
}
if [[ -r /sys/module/ifb/parameters/numifbs ]]; then
  printf 'IFB numifbs='; cat /sys/module/ifb/parameters/numifbs
else
  echo 'IFB numifbs is not exported through sysfs; recorded load arguments and host inventory are the evidence'
fi
