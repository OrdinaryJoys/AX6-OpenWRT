#!/usr/bin/env python3
"""Execute the real DNS helper with offline service, clock and query fixtures."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HELPER = Path(os.environ.get(
    "DNS_HEALTH_SCRIPT", ROOT / "AX6-IPQ/files/usr/sbin/ax6-openclash-dns-health"
))


class PolicyProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ax6-dns-policy-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = {
            "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "STATE_FILE": str(self.root / "state"),
            "QUERY_LOG": str(self.root / "queries"),
            "RESTART_LOG": str(self.root / "restarts"),
            "LOGGER_LOG": str(self.root / "messages"),
            "QUERY_PID": str(self.root / "query.pid"),
            "STARTUP_GRACE": "0", "FAILURE_THRESHOLD": "3",
            "RESTART_COOLDOWN": "300", "QUERY_TIMEOUT": "1",
        }
        self.write("uci", '''case "$*" in
  '-q get openclash.config.enable') echo "${OC_ENABLED:-1}" ;;
  '-q get openclash.config.enable_redirect_dns') echo "${REDIRECT_MODE:-1}" ;;
  '-q get openclash.config.dns_port') echo 7874 ;;
  '-q get dhcp.@dnsmasq[0].server') echo "${DNSMASQ_SERVER:-127.0.0.1#7874}" ;;
  *) exit 1 ;;
esac
''')
        self.write("pidof", '[ "${CORE_PID:-1234}" != missing ] || exit 1\necho "${CORE_PID:-1234}"\n')
        self.write("cut", 'echo "${TEST_UPTIME:-1000}"\n')
        self.write("logger", 'printf "%s\\n" "$*" >> "$LOGGER_LOG"\n')
        self.env["PROBE_BIN"] = str(self.write("probe", '''printf '%s %s\n' "$1" "$2" >> "$QUERY_LOG"
[ "$2" != "${FAIL_NAME:-}" ]
'''))
        self.env["OPENCLASH_INIT"] = str(self.write("openclash-init", '''printf '%s\n' "$*" >> "$RESTART_LOG"
[ "${RESTART_OK:-1}" = 1 ]
'''))

    def write(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return path

    def run_helper(self, mode="--once", **values):
        return subprocess.run(
            ["/bin/sh", str(HELPER), mode], env={**self.env, **values},
            text=True, capture_output=True, timeout=5,
        ).returncode

    def contents(self, name):
        path = self.root / name
        return path.read_text() if path.exists() else ""

    def test_both_queries_required_and_healthy(self):
        self.assertEqual(self.run_helper(), 0)
        self.assertEqual(self.contents("queries").splitlines(), [
            "7874 openwrt.org", "7874 services.googleapis.cn"
        ])
        self.assertEqual(self.contents("state"), "1234 1000 0 0\n")
        self.assertEqual(self.contents("restarts"), "")

    def test_policy_failure_is_not_hidden_by_ordinary_success(self):
        (self.root / "state").write_text("1234 500 2 0\n")
        self.assertEqual(self.run_helper("--probe", FAIL_NAME="services.googleapis.cn"), 1)
        self.assertEqual(len(self.contents("queries").splitlines()), 2)
        self.assertEqual(self.contents("state"), "1234 500 2 0\n")
        self.assertEqual(self.contents("restarts"), "")

    def test_ordinary_failure_is_not_hidden_by_policy_success(self):
        self.assertEqual(self.run_helper("--probe", FAIL_NAME="openwrt.org"), 1)
        self.assertEqual(self.contents("queries"), "7874 openwrt.org\n")
        self.assertEqual(self.contents("state"), "")
        self.assertEqual(self.contents("restarts"), "")

    def test_policy_failure_threshold_and_new_pid_cooldown(self):
        for expected in (1, 1, 0):
            self.assertEqual(self.run_helper(FAIL_NAME="services.googleapis.cn"), expected)
        self.assertEqual(self.contents("restarts"), "restart\n")
        self.assertIn("services.googleapis.cn", self.contents("messages"))
        for now in (1010, 1011, 1012):
            self.assertEqual(self.run_helper(
                CORE_PID="4321", TEST_UPTIME=str(now), FAIL_NAME="services.googleapis.cn"
            ), 1)
        self.assertEqual(self.contents("restarts"), "restart\n")
        self.assertIn("cooldown", self.contents("messages"))
        self.assertEqual(self.run_helper(CORE_PID="4321", TEST_UPTIME="1013"), 0)
        self.assertEqual(self.contents("state"), "4321 1010 0 1000\n")

    def test_cooldown_expires_and_restart_error_is_reported(self):
        (self.root / "state").write_text("1234 1000 2 1000\n")
        self.assertEqual(self.run_helper(
            TEST_UPTIME="1300", FAIL_NAME="services.googleapis.cn", RESTART_OK="0"
        ), 1)
        self.assertEqual(self.contents("restarts"), "restart\n")
        self.assertIn("restart command failed", self.contents("messages"))
        self.assertEqual(self.contents("state"), "0 1300 0 1300\n")

    def test_disabled_or_foreign_owner_does_not_query_or_restart(self):
        for values in (
            {"OC_ENABLED": "0"}, {"REDIRECT_MODE": "2"},
            {"DNSMASQ_SERVER": "1.1.1.1"},
        ):
            (self.root / "state").write_text("1234 1000 2 0\n")
            self.assertEqual(self.run_helper(FAIL_NAME="services.googleapis.cn", **values), 0)
            self.assertEqual(self.contents("state"), "")
        self.assertEqual(self.contents("queries"), "")
        self.assertEqual(self.contents("restarts"), "")

    def test_missing_core_owned_by_openclash_watchdog(self):
        self.assertEqual(self.run_helper(CORE_PID="missing"), 0)
        self.assertEqual(self.contents("queries"), "")
        self.assertEqual(self.contents("restarts"), "")

    def test_startup_grace_preserves_cooldown(self):
        (self.root / "state").write_text("1 500 2 900\n")
        self.assertEqual(self.run_helper(STARTUP_GRACE="60"), 0)
        self.assertEqual(self.contents("state"), "1234 1000 0 900\n")
        self.assertEqual(self.contents("queries"), "")

    def test_dry_run_has_no_persistent_side_effect(self):
        (self.root / "state").write_text("1234 500 2 0\n")
        self.assertEqual(self.run_helper("--dry-run", FAIL_NAME="services.googleapis.cn"), 1)
        self.assertEqual(self.contents("state"), "1234 500 2 0\n")
        self.assertEqual(self.contents("restarts"), "")
        self.assertIn("would restart", self.contents("messages"))

    def test_custom_probe_names(self):
        self.assertEqual(self.run_helper(
            "--probe", PROBE_NAME="normal.example", POLICY_PROBE_NAME="policy.example"
        ), 0)
        self.assertEqual(self.contents("queries").splitlines(), [
            "7874 normal.example", "7874 policy.example"
        ])

    def test_native_query_timeout_kills_and_reaps_probe(self):
        nslookup = self.write("nslookup", '''echo "$$" > "$QUERY_PID"
exec sleep 10
''')
        self.env.pop("PROBE_BIN")
        self.assertEqual(self.run_helper("--probe", NSLOOKUP_BIN=str(nslookup)), 1)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(self.contents("query.pid")), 0)
        self.assertEqual(self.contents("state"), "")
        self.assertEqual(self.contents("restarts"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
