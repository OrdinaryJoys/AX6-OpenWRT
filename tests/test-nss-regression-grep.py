#!/usr/bin/env python3
"""Run the actual Lint literal-check command against private text, not source C."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DP = '--candidate-only --candidate "$nss_dp_dir"'
DRV = '--candidate-only --candidate "$nss_drv_dir"'


class LiteralRegressionGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = (ROOT / '.github/workflows/lint.yml').read_text()
        marker = '      - name: AX6 NSS build lock check\n'
        if workflow.count(marker) != 1:
            raise ValueError('Expected one actual Lint build-lock step')
        step = workflow.split(marker, 1)[1].split('\n      - ', 1)[0]
        matches = re.findall(
            r'^\s*(grep -Fq -- "\$regression_gate" "\$workflow") \|\| \{$',
            step, re.M)
        if len(matches) != 1:
            raise ValueError('Actual literal gate lost its quoted option terminator')
        cls.command = matches[0]

    def check_literal(self, pattern, content, command=None):
        with tempfile.TemporaryDirectory(prefix='ax6-literal-grep-') as folder:
            path = Path(folder) / 'candidate workflow.yml'
            path.write_text(content)
            env = {**os.environ, 'regression_gate': pattern, 'workflow': str(path)}
            return subprocess.run(['sh', '-c', command or self.command], env=env,
                                  capture_output=True, text=True, timeout=5)

    def test_dp_literal_present(self):
        self.assertEqual(self.check_literal(DP, '  ' + DP + ' \\\n').returncode, 0)

    def test_drv_literal_present(self):
        self.assertEqual(self.check_literal(DRV, '  ' + DRV + ' \\\n').returncode, 0)

    def test_non_option_literal_present(self):
        self.assertEqual(self.check_literal('python3 tests/check.py',
                                            'python3 tests/check.py\n').returncode, 0)

    def test_missing_dp_is_rejected(self):
        self.assertEqual(self.check_literal(DP, 'unrelated command\n').returncode, 1)

    def test_tampered_candidate_is_rejected(self):
        self.assertEqual(self.check_literal(DP, DP.replace('$nss_dp_dir', '$other_dir')).returncode, 1)

    def test_literal_dollar_is_not_expanded(self):
        self.assertEqual(self.check_literal(DP, '--candidate-only --candidate "/tmp/prepared"').returncode, 1)

    def test_option_like_help_remains_a_pattern(self):
        self.assertEqual(self.check_literal('--help', 'unrelated text\n').returncode, 1)
        self.assertEqual(self.check_literal('--help', '--help\n').returncode, 0)

    def test_old_missing_terminator_reproduces_option_error(self):
        result = self.check_literal(DP, DP, self.command.replace(' -Fq -- ', ' -Fq ', 1))
        self.assertEqual(result.returncode, 2)
        self.assertIn('grep:', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
