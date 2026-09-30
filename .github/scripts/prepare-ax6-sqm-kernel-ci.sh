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
before_ifb=$(ip -j link show type ifb)
printf 'Host IFB inventory before: %s\n' "$before_ifb"
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
after_ifb=$(ip -j link show type ifb)
printf 'Host IFB inventory after: %s\n' "$after_ifb"
[[ "$before_ifb" == "$after_ifb" ]] || {
  echo 'Preparation unexpectedly changed host IFB inventory' >&2
  exit 1
}
if [[ -r /sys/module/ifb/parameters/numifbs ]]; then
  printf 'IFB numifbs='; cat /sys/module/ifb/parameters/numifbs
else
  echo 'IFB numifbs is not exported through sysfs; recorded load arguments and host inventory are the evidence'
fi
uname -r
ip -Version
tc -Version
