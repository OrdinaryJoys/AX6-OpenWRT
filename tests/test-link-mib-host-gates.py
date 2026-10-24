#!/usr/bin/env python3
"""Offline CI binding regression; never execute workflow commands or host helpers.

This deliberately recognizes the workflow's literal step/selector format, not
arbitrary YAML or Bash. A formatting/selector redesign needs a reviewed update.
Prepared-tree freshness, source correctness and Actions execution are not proved.
All negative controls edit strings in memory, never the workflow on disk.
"""
from pathlib import Path, PurePosixPath
import posixpath
import re
import shlex
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/build-AX6-NSS.yml'
GATE = 'Fast gate \u2014 NSS patch prepare (P0-D.6)'
MARKER = '      - name: ' + GATE + '\n'
WIFI = 'test-ath11k-nss-link-return.py'
QCOM = 'test-qcom-mib-width.py'
N2H = 'test-nss-n2h-sysctl-errors.py'
PBUF = 'test-qca-nss-pbuf-reload.py'
PBUF_START = 'test-qca-nss-pbuf-start.py'
IGS = 'test-nss-igs-interface-errors.py'
ADMISSION = 'test-nss-igs-action-admission.py'
SYNC = 'test-nss-igs-sync-completion.py'
EVIDENCE = '$GITHUB_WORKSPACE/core-flow-evidence/'
DESTINATIONS = {WIFI: 'wifi-nss-link-return', QCOM: 'qcom-mib-width',
                N2H: 'nss-n2h-sysctl-errors', PBUF: 'pbuf-reload',
                PBUF_START: 'pbuf-start', IGS: 'nss-igs-interface-errors',
                ADMISSION: 'nss-igs-action-admission', SYNC: 'nss-igs-sync-completion'}
CONSUMERS = {'backports_dir': WIFI, 'ssdk_dir': QCOM, 'nss_dp_dir': QCOM,
             'nss_drv_dir': N2H, 'nss_clients_dir': SYNC}
CALLS = {
    PBUF: ('python3 tests/' + PBUF + ' --mutations '
           '--output "' + EVIDENCE + 'pbuf-reload"'),
    PBUF_START: ('python3 tests/' + PBUF_START + ' --mutations '
                '--output "' + EVIDENCE + 'pbuf-start"'),
    WIFI: ('python3 tests/' + WIFI + ' "$backports_dir" --mutations --sanitize '
           '--output "' + EVIDENCE + 'wifi-nss-link-return"'),
    QCOM: ('python3 tests/' + QCOM + ' "$nss_dp_dir" --ssdk "$ssdk_dir" '
           '--mutations --sanitize --output "' + EVIDENCE + 'qcom-mib-width"'),
    N2H: ('python3 tests/' + N2H + ' "$nss_drv_dir" --mutations --sanitize '
          '--output "' + EVIDENCE + 'nss-n2h-sysctl-errors"'),
    IGS: ('python3 tests/' + IGS + ' "$nss_clients_dir" --driver "$nss_drv_dir" --mutations --sanitize '
          '--output "' + EVIDENCE + 'nss-igs-interface-errors"'),
    ADMISSION: ('python3 tests/' + ADMISSION + ' "$nss_clients_dir" --cc cc --mutations --sanitize '
                '--output "' + EVIDENCE + 'nss-igs-action-admission"'),
    SYNC: ('python3 tests/' + SYNC + ' "$nss_clients_dir" --cc cc --mutations --sanitize '
           '--output "' + EVIDENCE + 'nss-igs-sync-completion"'),
}
# Each producer includes the real prepare, NUL selector, exact-one guard and
# assignment in one contiguous sequence. A comment/echo elsewhere cannot supply it.
PRODUCERS = {
    'backports_dir': '''
        make package/kernel/mac80211/prepare V=s
        mapfile -d '' ath11k_core_files < <(
        find build_dir -type f -path '*/backports-*/drivers/net/wireless/ath/ath11k/core.c' -print0
        )
        if [ "${#ath11k_core_files[@]}" -ne 1 ]; then
        echo "::error::Expected one prepared ath11k core source; found ${#ath11k_core_files[@]}"
        exit 1
        fi
        backports_dir=${ath11k_core_files[0]%/drivers/net/wireless/ath/ath11k/core.c}
    ''',
    'ssdk_dir': '''
        make package/qca-nss/qca-ssdk/prepare V=s
        mapfile -d '' ssdk_mib_files < <(find build_dir -type f -path '*/qca-ssdk-*/src/fal/fal_mib.c' -print0)
        test "${#ssdk_mib_files[@]}" -eq 1
        ssdk_dir=${ssdk_mib_files[0]%/src/fal/fal_mib.c}
    ''',
    'nss_dp_dir': '''
        make package/qca-nss/qca-nss-dp/prepare V=s
        mapfile -d '' nss_dp_dirs < <(
        find build_dir -type d -name 'qca-nss-dp-*' -print0
        )
        if [ "${#nss_dp_dirs[@]}" -ne 1 ]; then
        echo "::error::Expected one prepared NSS dataplane directory; found ${#nss_dp_dirs[@]}"
        exit 1
        fi
        nss_dp_dir=${nss_dp_dirs[0]}
        test -s "$nss_dp_dir/nss_dp_main.c"
    ''',
    'nss_drv_dir': '''
        make package/qca-nss/qca-nss-drv/prepare V=s
        mapfile -d '' nss_drv_dirs < <(
        find build_dir -type d -name 'qca-nss-drv-*' -print0
        )
        if [ "${#nss_drv_dirs[@]}" -ne 1 ]; then
        echo "::error::Expected one prepared NSS driver directory; found ${#nss_drv_dirs[@]}"
        exit 1
        fi
        nss_drv_dir=${nss_drv_dirs[0]}
        test -s "$nss_drv_dir/nss_core.c"
    ''',
    'nss_clients_dir': '''
        make package/qca-nss/qca-nss-clients/prepare V=s
        mapfile -d '' nss_clients_files < <(
        find build_dir -type f -path '*/qca-nss-clients-*/nss_qdisc/igs/nss_ifb.c' -print0
        )
        test "${#nss_clients_files[@]}" -eq 1
        nss_clients_dir=${nss_clients_files[0]%/nss_qdisc/igs/nss_ifb.c}
    ''',
}
ARRAYS = {'backports_dir': 'ath11k_core_files', 'ssdk_dir': 'ssdk_mib_files',
          'nss_dp_dir': 'nss_dp_dirs', 'nss_drv_dir': 'nss_drv_dirs',
          'nss_clients_dir': 'nss_clients_files'}
# Non-test shell syntax already surrounding the protected producers. Keeping the
# prefix closed prevents entire valid-looking chains hidden in strings/functions.
ADJACENT_SHELL = '''
    set -eo pipefail
    make package/network/services/hostapd/prepare V=s
    mapfile -d '' hostapd_apup_files < <(
    find build_dir -type f -path '*/hostapd-*/src/ap/apup.c' -print0
    )
    if [ "${#hostapd_apup_files[@]}" -eq 0 ]; then
    exit 1
    fi
    for hostapd_apup_file in "${hostapd_apup_files[@]}"; do
    hostapd_dir=${hostapd_apup_file%/src/ap/apup.c}
    done
    make package/qca-nss/qca-nss-ecm/prepare V=s
    mapfile -d '' ecm_dscp_files < <(find build_dir -type f -path '*/qca-nss-ecm-*/ecm_classifier_dscp.c' -print0)
    test "${#ecm_dscp_files[@]}" -eq 1
    ecm_dir=${ecm_dscp_files[0]%/ecm_classifier_dscp.c}
'''


class BindingError(AssertionError):
    """An unsupported or regressed CI binding, not a YAML parser diagnostic."""


def require(condition, diagnostic):
    if not condition:
        raise BindingError(diagnostic)


def logical_lines(script):
    script = re.sub(r'[ \t]*\\\r?\n[ \t]*', ' ', script)
    return [line.strip() for line in script.splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def section(lines, heading):
    starts = [i for i, line in enumerate(lines) if line == heading]
    require(len(starts) == 1, 'step: expected unique ' + heading.strip())
    start = starts[0]
    indent = len(heading) - len(heading.lstrip())
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and not line.lstrip().startswith('#'):
            if len(line) - len(line.lstrip()) <= indent:
                break
        end += 1
    return lines[start:end]


def gate_script(workflow):
    lines = workflow.splitlines()
    jobs = section(lines, 'jobs:')
    build = section(jobs, '  build:')
    steps = section(build, '    steps:')
    header = build[:build.index('    steps:')]
    require(not any(re.match(r'    (if|continue-on-error|defaults):', line)
                    for line in header), 'step: conditional or altered build job')
    require(not any(re.match(r'defaults:', line) for line in lines),
            'step: unsupported inherited run defaults')
    starts = [i for i, line in enumerate(steps) if line.startswith('      - ')]
    matches = [i for i in starts if steps[i] == MARKER.rstrip('\n')]
    require(len(matches) == 1 and workflow.count(MARKER) == 1,
            'step: expected unique named Fast gate in build job')
    start = matches[0]
    compile_steps = [i for i in starts if steps[i] == '      - name: Compile firmware']
    require(len(compile_steps) == 1 and start < compile_steps[0],
            'order: Fast gate must precede full compilation')
    end = next((i for i in starts if i > start), len(steps))
    block = steps[start:end]
    require(block.count('        run: |') == 1, 'step: literal run block required')
    run = block.index('        run: |')
    metadata = [line.strip() for line in block[:run + 1]
                if line.strip() and not line.lstrip().startswith('#')]
    require(metadata == ['- name: ' + GATE, 'working-directory: ./openwrt', 'run: |'],
            'step: changed directory, execution policy or step metadata')
    require(all(not line.strip() or line.startswith('          ')
                for line in block[run + 1:]), 'step: unexpected properties after run')
    return '\n'.join(line[10:] for line in block[run + 1:])


def unique_span(lines, fragment, label):
    expected = logical_lines(textwrap.dedent(fragment))
    starts = [i for i in range(len(lines) - len(expected) + 1)
              if lines[i:i + len(expected)] == expected]
    require(len(starts) == 1, 'producer: missing/ambiguous ' + label)
    start = starts[0]
    return start, start + len(expected) - 1


def recognize_command(line):
    """Allow only this prefix's simple test/log commands, without evaluating any."""
    if line == ('python3 tests/test-ssdk-mib-errors.py "$ssdk_dir" | tee "'
                + EVIDENCE + 'ssdk.log"'):
        return
    require('$(' not in line and '`' not in line, 'flow: command substitution')
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        argv = list(lexer)
    except ValueError as error:
        raise BindingError('flow: multiline/unsupported shell quoting') from error
    require(not any(re.fullmatch(r'[;&|<>()]+', arg) for arg in argv),
            'flow: unsupported shell operator')
    while argv and re.match(r'^[A-Z_]+=', argv[0]):
        require(argv.pop(0) in ('RPS_TEST_SHELL=busybox ash', 'ECM_TEST_SHELL=busybox ash',
                               'PYTHONDONTWRITEBYTECODE=1'), 'flow: unexpected command environment')
    test_script = (len(argv) >= 2 and argv[0] in ('python3', 'sh')
                   and re.fullmatch(r'tests/[\w/.-]+\.(?:py|sh)', argv[1]))
    discovery = argv[:4] == ['python3', '-m', 'unittest', 'discover']
    log = len(argv) == 2 and argv[0] == 'echo'
    directory = argv in (['mkdir', '-p', '$GITHUB_WORKSPACE/core-flow-evidence'],
                         ['mkdir', '-p', '../nss-containment-evidence'])
    require(test_script or discovery or log or directory,
            'flow: unsupported prefix command ' + line)


def validate(workflow):
    """Fail closed on changes to the literal, same-shell producer/call contract."""
    lines = logical_lines(gate_script(workflow))
    require(lines and lines[0] == 'set -eo pipefail', 'flow: errexit/pipefail required')
    spans = {name: unique_span(lines, fragment, name)
             for name, fragment in PRODUCERS.items()}
    calls = {}
    for filename, expected in CALLS.items():
        pattern = r'^\s*python3 tests/' + re.escape(filename) + r'(?:\s|$)'
        # Whole-workflow check catches a second real invocation in another step.
        require(len(re.findall(pattern, workflow, re.M)) == 1,
                'call: missing/duplicate workflow invocation ' + filename)
        indices = [i for i, line in enumerate(lines)
                   if re.match(pattern, line)]
        require(len(indices) == 1, 'call: not in prepared Fast gate ' + filename)
        index = indices[0]
        require(lines[index] == expected, 'call: changed argv/flags/output ' + filename)
        calls[filename] = index
    require(spans['backports_dir'][1] < calls[PBUF] < calls[PBUF_START] < calls[WIFI] < spans['ssdk_dir'][0]
            <= spans['ssdk_dir'][1] < spans['nss_dp_dir'][0]
            <= spans['nss_dp_dir'][1] < calls[QCOM] < spans['nss_drv_dir'][0]
            <= spans['nss_drv_dir'][1] < calls[N2H] < spans['nss_clients_dir'][0]
            <= spans['nss_clients_dir'][1] < calls[IGS] < calls[ADMISSION] < calls[SYNC],
            'order: require prepare/unique selection/assignment before consumers')

    # A second producer or write must not silently replace the selected input.
    for name, array in ARRAYS.items():
        start, end = spans[name]
        assignment = next(i for i in range(start, end + 1) if lines[i].startswith(name + '='))
        for variable, allowed in ((name, assignment), (array, start + 1)):
            write = re.compile(r'(?<![\w])' + re.escape(variable)
                               + r'(?:\[[^\]]*\])?\s*\+?=')
            builtin = re.compile(r'^(?:mapfile|readarray|read|unset|declare|typeset|'
                                 r'local|export|readonly|printf)\b.*\b'
                                 + re.escape(variable) + r'\b')
            for i, line in enumerate(lines):
                if write.search(line) or builtin.search(line):
                    require(i == allowed, 'binding: extra write to ' + variable)
        prepare = lines[start]
        require(lines.count(prepare) == 1, 'binding: repeated prepare for ' + name)

    # Critical commands must be at shell top level, not inside a disabled branch
    # or loop. This is a bounded recognizer of this prefix, not a Bash evaluator.
    critical = set(calls.values())
    known_syntax = set(logical_lines(ADJACENT_SHELL))
    for start, end in spans.values():
        critical.update((start, start + 1, end))
        known_syntax.update(lines[start:end + 1])
    stack = []
    for i, line in enumerate(lines[:max(calls.values()) + 1]):
        if line not in known_syntax:
            recognize_command(line)
        if i in critical:
            require(not stack, 'flow: conditional producer or consumer')
        if re.match(r'^if .+; then$', line):
            stack.append('fi')
        elif re.match(r'^(?:for|while) .+; do$', line):
            stack.append('done')
        elif line in ('fi', 'done'):
            require(stack and stack.pop() == line, 'flow: unbalanced control structure')
        elif re.match(r'^(?:if|for|while|until|case|select|function|else|elif)\b', line):
            raise BindingError('flow: unsupported control structure')
        elif re.match(r'^(?:eval|source|\.|trap|exec|return|cd|pushd|popd)\s', line):
            raise BindingError('flow: unsupported shell state change')
        elif re.match(r'^set\b', line):
            require(i == 0, 'flow: changed shell failure policy')
        elif re.match(r'^exit\b', line):
            require(line == 'exit 1' and stack, 'flow: early exit')
        require(not re.search(r'\|\|\s*(?:true|:)(?:\s|$)', line),
                'flow: swallowed failure')
    require(not stack, 'flow: incomplete control structure')

    outputs = {}
    for i, line in enumerate(lines):
        if not re.match(r'^(?:\w+=\S+\s+)*python3\s', line):
            continue
        argv = shlex.split(line, comments=True)
        for j, arg in enumerate(argv):
            if arg == '--output':
                require(j + 1 < len(argv), 'outputs: missing value')
                value = argv[j + 1]
            elif arg.startswith('--output='):
                value = arg.partition('=')[2]
            else:
                continue
            value = re.sub(r'^\$\{GITHUB_WORKSPACE\}(?=/|$)', '$GITHUB_WORKSPACE', value)
            outputs.setdefault(i, []).append(PurePosixPath(posixpath.normpath(value)))
    for index in calls.values():
        require(len(outputs.get(index, [])) == 1, 'outputs: require one output')
        own = outputs[index][0]
        for other, paths in outputs.items():
            if other != index:
                require(all(own != path and own not in path.parents
                            and path not in own.parents for path in paths),
                        'outputs: shared or nested output directory')
    return {'step': GATE, 'producers': spans, 'calls': calls}


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise AssertionError('negative-control fixture drift: ' + repr(old))
    return text.replace(old, new, 1)


def physical_call(filename):
    return CALLS[filename].replace(' --output ', ' ' + chr(92) + '\n            --output ')


def edit_call(filename, old, new):
    return lambda text: replace_once(text, physical_call(filename),
                                    physical_call(filename).replace(old, new, 1))


def move_call(filename, before):
    def mutate(text):
        call = '          ' + physical_call(filename) + '\n'
        text = replace_once(text, call, '')
        return replace_once(text, before, call + before)
    return mutate


def insert_before_call(filename, command):
    anchor = '          python3 tests/' + filename
    return lambda text: replace_once(text, anchor, '          ' + command + '\n' + anchor)


def wrap_chain(opening, closing):
    def mutate(text):
        text = replace_once(text, '          make package/kernel/mac80211/prepare V=s',
                            '          ' + opening + '\n          make package/kernel/mac80211/prepare V=s')
        return replace_once(text, '          ' + physical_call(QCOM),
                            '          ' + physical_call(QCOM) + '\n          ' + closing)
    return mutate


class HostGateBindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text()
        validate(cls.workflow)

    def test_actual_workflow_positive(self):
        result = validate(self.workflow)
        self.assertEqual(set(result['producers']), set(ARRAYS))
        self.assertEqual(set(result['calls']), {PBUF, PBUF_START, WIFI, QCOM, N2H, IGS, ADMISSION, SYNC})

    def test_comments_are_not_executable_producers_or_calls(self):
        decoys = '\n'.join('          # ' + line for line in
                           (*CALLS.values(), 'ssdk_dir=/old/baseline')) + '\n'
        text = replace_once(self.workflow, '          make package/kernel/mac80211/prepare V=s',
                            decoys + '          make package/kernel/mac80211/prepare V=s')
        validate(text)

    def test_output_mutations_preserve_script_and_other_arguments(self):
        for filename, short in ((PBUF, 'pbuf'), (PBUF_START, 'pbuf_start'), (WIFI, 'wifi'),
                                (QCOM, 'qcom'), (N2H, 'n2h'), (IGS, 'igs'),
                                (ADMISSION, 'admission'), (SYNC, 'sync')):
            modified = MUTATIONS[short + '_shared_output'](self.workflow)
            prefix = 'python3 tests/' + filename + ' '
            calls = [line for line in logical_lines(gate_script(modified)) if line.startswith(prefix)]
            self.assertEqual(len(calls), 1, short)
            before, after = shlex.split(CALLS[filename]), shlex.split(calls[0])
            output = before.index('--output') + 1
            self.assertNotEqual(before[output], after[output], short)
            after[output] = before[output]
            self.assertEqual(before, after, short)


MUTATIONS = {
    'wrong_working_directory': lambda t: replace_once(
        t, MARKER + '        working-directory: ./openwrt',
        MARKER + '        working-directory: ./baseline'),
    'disabled_step': lambda t: replace_once(t, MARKER, MARKER + '        if: false\n'),
    'allowed_step_failure': lambda t: replace_once(
        t, MARKER, MARKER + '        continue-on-error: true\n'),
    'folded_run_block': lambda t: replace_once(
        t, MARKER + '        working-directory: ./openwrt\n        run: |',
        MARKER + '        working-directory: ./openwrt\n        run: >'),
    'disabled_build_job': lambda t: replace_once(t, '  build:\n', '  build:\n    if: false\n'),
    'inherited_shell': lambda t: replace_once(
        t, 'jobs:\n', 'defaults:\n  run:\n    shell: sh\njobs:\n'),
    'duplicate_gate': lambda t: t + '\n' + MARKER + '        run: |\n          true\n',
    'lost_pipefail': lambda t: replace_once(
        t, MARKER + '        working-directory: ./openwrt\n        run: |\n          set -eo pipefail',
        MARKER + '        working-directory: ./openwrt\n        run: |\n          set -e'),
    'disable_errexit': insert_before_call(QCOM, 'set +e'),
    'early_success_exit': insert_before_call(WIFI, 'exit 0'),
    'hidden_variable_source': insert_before_call(QCOM, '. old-prepared.env'),
    'changed_directory_mid_step': insert_before_call(WIFI, 'cd ../baseline'),
    'conditional_call': lambda t: replace_once(
        t, '          ' + physical_call(WIFI),
        '          if false; then\n          ' + physical_call(WIFI) + '\n          fi'),
    'conditional_entire_chain': lambda t: replace_once(
        replace_once(t, '          make package/kernel/mac80211/prepare V=s',
                     '          if false; then\n          make package/kernel/mac80211/prepare V=s'),
        '          ' + physical_call(QCOM), '          ' + physical_call(QCOM) + '\n          fi'),
    'heredoc_decoy_chain': wrap_chain("cat <<'NOT_COMMANDS'", 'NOT_COMMANDS'),
    'noop_heredoc_decoy_chain': wrap_chain(": <<'NOT_COMMANDS'", 'NOT_COMMANDS'),
    'uncalled_function_decoy_chain': wrap_chain('unused_gate() {', '}'),
    'multiline_string_decoy_chain': wrap_chain("echo '", "'"),
    'wifi_before_prepare': move_call(WIFI, '          make package/kernel/mac80211/prepare V=s\n'),
    'qcom_before_dp_prepare': move_call(QCOM, '          make package/qca-nss/qca-nss-dp/prepare V=s\n'),
    'qcom_before_ssdk_prepare': move_call(QCOM, '          make package/qca-nss/qca-ssdk/prepare V=s\n'),
    'n2h_before_drv_prepare': move_call(N2H, '          make package/qca-nss/qca-nss-drv/prepare V=s\n'),
    'n2h_before_drv_file_guard': move_call(N2H, '          test -s "$nss_drv_dir/nss_core.c"\n'),
    'fast_gate_after_compile': lambda t: replace_once(
        replace_once(t, MARKER, '      - name: SWAP_GATE\n'),
        '      - name: Compile firmware\n', MARKER).replace(
            '      - name: SWAP_GATE\n', '      - name: Compile firmware\n', 1),
    'ssdk_selection_from_prior_step': lambda t: replace_once(
        t, '          make package/qca-nss/qca-ssdk/prepare V=s\n', ''),
    'shared_outputs_with_another_gate': lambda t: replace_once(
        t, EVIDENCE + 'dp-statistics"', EVIDENCE + 'qcom-mib-width"'),
    'nested_output_from_another_gate': lambda t: replace_once(
        t, EVIDENCE + 'dp-statistics"', EVIDENCE + 'qcom-mib-width/child"'),
    'n2h_shared_output_with_another_gate': lambda t: replace_once(
        t, EVIDENCE + 'dp-statistics"', EVIDENCE + 'nss-n2h-sysctl-errors"'),
    'aliased_workspace_output_collision': lambda t: replace_once(
        t, EVIDENCE + 'dp-statistics"', '${GITHUB_WORKSPACE}/core-flow-evidence/nss-n2h-sysctl-errors"'),
    'dotdot_output_collision': lambda t: replace_once(
        t, EVIDENCE + 'dp-statistics"', EVIDENCE + 'unrelated/../qcom-mib-width"'),
    'equals_output_collision': lambda t: replace_once(
        t, '--output "' + EVIDENCE + 'dp-statistics"', '--output="' + EVIDENCE + 'qcom-mib-width"'),
    'qcom_without_ssdk': edit_call(QCOM, ' --ssdk "$ssdk_dir"', ''),
    'qcom_wrong_ssdk_variable': edit_call(QCOM, '"$ssdk_dir"', '"$nss_dp_dir"'),
    'qcom_old_ssdk': edit_call(QCOM, '"$ssdk_dir"', '"/old/prepared/ssdk"'),
}

for filename, short, source in ((WIFI, 'wifi', 'backports_dir'), (QCOM, 'qcom', 'nss_dp_dir'),
                                (N2H, 'n2h', 'nss_drv_dir'), (IGS, 'igs', 'nss_clients_dir'),
                                (ADMISSION, 'admission', 'nss_clients_dir'),
                                (SYNC, 'sync', 'nss_clients_dir')):
    for flag in ('--mutations', '--sanitize'):
        MUTATIONS[short + '_missing_' + flag[2:]] = edit_call(filename, ' ' + flag, '')
    for label, old, new in (
            ('baseline_instead_of_prepared', '"$' + source + '"', '"/old/baseline"'),
            ('unquoted_prepared', '"$' + source + '"', '$' + source),
            ('extra_baseline', ' --mutations', ' --baseline /old/prepared --mutations'),
            ('missing_output', ' --output ', ' --missing-output '),
            ('duplicate_output_flag', ' --mutations', ' --output /old/prepared --mutations'),
            ('swallowed_failure', physical_call(filename), physical_call(filename) + ' || true'),
            ('output_in_old_audit', EVIDENCE, '/old/audit/'),
            ('shared_output', EVIDENCE + DESTINATIONS[filename],
             EVIDENCE + ('qcom-mib-width' if short == 'wifi' else 'wifi-nss-link-return')),
            ('echo_instead_of_call', 'python3 tests/', 'echo python3 tests/')):
        MUTATIONS[short + '_' + label] = edit_call(filename, old, new)
    MUTATIONS[short + '_deleted_call'] = edit_call(filename, physical_call(filename), '')
    MUTATIONS[short + '_comment_only_call'] = edit_call(filename, 'python3 ', '# python3 ')
    MUTATIONS[short + '_duplicate_call'] = insert_before_call(filename, CALLS[filename])
    MUTATIONS[short + '_duplicate_in_other_step'] = (
        lambda t, f=filename: replace_once(t, MARKER,
            '      - name: Decoy host gate\n        run: |\n          ' + CALLS[f] + '\n\n' + MARKER))
    MUTATIONS[short + '_moved_to_other_step'] = (
        lambda t, f=filename: replace_once(
            replace_once(t, '          ' + physical_call(f) + '\n', ''), MARKER,
            '      - name: Stale shell variables\n        run: |\n          ' + CALLS[f] + '\n\n' + MARKER))

# PBUF reads the installed init in its own source tree, not a prepared backports
# directory. Protect that actual argv rather than inventing a directory argument
# or a sanitizer flag the shell-only runner does not support.
for label, old, new in (
        ('missing_mutations', ' --mutations', ''),
        ('extra_baseline', ' --mutations', ' --baseline /old/prepared --mutations'),
        ('wrong_script', 'tests/' + PBUF, 'tests/old/' + PBUF),
        ('missing_output', ' --output ', ' --missing-output '),
        ('duplicate_output', ' --mutations', ' --output /old/prepared --mutations'),
        ('old_output', EVIDENCE, '/old/audit/'),
        ('shared_output', EVIDENCE + 'pbuf-reload', EVIDENCE + 'wifi-nss-link-return'),
        ('nested_output', EVIDENCE + 'pbuf-reload', EVIDENCE + 'wifi-nss-link-return/child'),
        ('echo', 'python3 tests/', 'echo python3 tests/'),
        ('quoted_echo', physical_call(PBUF), 'echo "' + CALLS[PBUF].replace('"', chr(92) + '"') + '"'),
        ('comment', 'python3 ', '# python3 '),
        ('deleted', physical_call(PBUF), ''),
        ('swallowed_failure', physical_call(PBUF), physical_call(PBUF) + ' || true')):
    MUTATIONS['pbuf_' + label] = edit_call(PBUF, old, new)
MUTATIONS['pbuf_duplicate_call'] = insert_before_call(PBUF, CALLS[PBUF])
MUTATIONS['pbuf_before_prepare'] = move_call(PBUF, '          make package/kernel/mac80211/prepare V=s\n')
MUTATIONS['pbuf_after_wifi'] = move_call(PBUF, '          make package/qca-nss/qca-ssdk/prepare V=s\n')
MUTATIONS['pbuf_moved_to_other_step'] = lambda t: replace_once(
    replace_once(t, '          ' + physical_call(PBUF) + '\n', ''), MARKER,
    '      - name: Wrong source tree\n        run: |\n          ' + CALLS[PBUF] + '\n\n' + MARKER)
MUTATIONS['pbuf_duplicate_in_other_step'] = lambda t: replace_once(
    t, MARKER, '      - name: Duplicate PBUF\n        run: |\n          ' + CALLS[PBUF] + '\n\n' + MARKER)
MUTATIONS['pbuf_known_false_branch'] = lambda t: replace_once(
    t, '          ' + physical_call(PBUF),
    '          if [ "${#ath11k_core_files[@]}" -ne 1 ]; then\n          ' + physical_call(PBUF) + '\n          fi')
for label, opening, closing in (
        ('uncalled_function', 'unused_pbuf() {', '}'),
        ('heredoc', "cat <<'PBUF_NOT_EXECUTED'", 'PBUF_NOT_EXECUTED'),
        ('quoted_string', "echo '", "'")):
    MUTATIONS['pbuf_' + label] = lambda t, a=opening, b=closing: replace_once(
        t, '          ' + physical_call(PBUF),
        '          ' + a + '\n          ' + physical_call(PBUF) + '\n          ' + b)
for label, replacement in (
        ('same_output', EVIDENCE + 'pbuf-reload'),
        ('nested_output', EVIDENCE + 'pbuf-reload/child'),
        ('parent_output', '$GITHUB_WORKSPACE/core-flow-evidence'),
        ('aliased_output', '${GITHUB_WORKSPACE}/core-flow-evidence/pbuf-reload'),
        ('dotdot_output', EVIDENCE + 'unrelated/../pbuf-reload')):
    MUTATIONS['pbuf_neighbor_' + label] = lambda t, value=replacement: replace_once(
        t, EVIDENCE + 'dp-statistics"', value + '"')
MUTATIONS['pbuf_neighbor_equals_output'] = lambda t: replace_once(
    t, '--output "' + EVIDENCE + 'dp-statistics"', '--output="' + EVIDENCE + 'pbuf-reload"')

for label, old, new in (
        ('missing_mutations', ' --mutations', ''),
        ('extra_sanitizer', ' --mutations', ' --mutations --sanitize'),
        ('extra_prepared', ' --mutations', ' "$backports_dir" --mutations'),
        ('missing_output', ' --output ', ' --missing-output '),
        ('duplicate_output', ' --mutations', ' --output /old/audit --mutations'),
        ('old_output', EVIDENCE, '/old/audit/'),
        ('shared_output', EVIDENCE + 'pbuf-start', EVIDENCE + 'wifi-nss-link-return'),
        ('comment', 'python3 ', '# python3 '),
        ('echo', 'python3 tests/', 'echo python3 tests/'),
        ('deleted', physical_call(PBUF_START), ''),
        ('swallowed_failure', physical_call(PBUF_START), physical_call(PBUF_START) + ' || true')):
    MUTATIONS['pbuf_start_' + label] = edit_call(PBUF_START, old, new)
MUTATIONS['pbuf_start_duplicate'] = insert_before_call(PBUF_START, CALLS[PBUF_START])
MUTATIONS['pbuf_start_before_reload'] = move_call(PBUF_START, '          ' + physical_call(PBUF) + '\n')
MUTATIONS['pbuf_start_false_branch'] = lambda t: replace_once(
    t, '          ' + physical_call(PBUF_START),
    '          if false; then\n          ' + physical_call(PBUF_START) + '\n          fi')
for label, replacement in (('same', EVIDENCE + 'pbuf-start'),
                           ('nested', EVIDENCE + 'pbuf-start/child'),
                           ('alias', '${GITHUB_WORKSPACE}/core-flow-evidence/pbuf-start')):
    MUTATIONS['pbuf_start_neighbor_' + label] = lambda t, value=replacement: replace_once(
        t, EVIDENCE + 'dp-statistics"', value + '"')
for label, old, new in (
        ('missing_driver', ' --driver "$nss_drv_dir"', ''),
        ('wrong_driver', ' --driver "$nss_drv_dir"', ' --driver "$nss_clients_dir"'),
        ('old_driver', ' --driver "$nss_drv_dir"', ' --driver /old/prepared'),
        ('unquoted_driver', ' --driver "$nss_drv_dir"', ' --driver $nss_drv_dir')):
    MUTATIONS['igs_' + label] = edit_call(IGS, old, new)

MUTATIONS['admission_before_clients_prepare'] = move_call(
    ADMISSION, '          make package/qca-nss/qca-nss-clients/prepare V=s\n')
MUTATIONS['admission_before_interface_gate'] = move_call(
    ADMISSION, '          ' + physical_call(IGS) + '\n')
MUTATIONS['admission_false_branch'] = lambda t: replace_once(
    t, '          ' + physical_call(ADMISSION),
    '          if false; then\n          ' + physical_call(ADMISSION) + '\n          fi')

MUTATIONS['sync_before_clients_prepare'] = move_call(
    SYNC, '          make package/qca-nss/qca-nss-clients/prepare V=s\n')
MUTATIONS['sync_before_admission_gate'] = move_call(
    SYNC, '          ' + physical_call(ADMISSION) + '\n')
MUTATIONS['sync_false_branch'] = lambda t: replace_once(
    t, '          ' + physical_call(SYNC),
    '          if false; then\n          ' + physical_call(SYNC) + '\n          fi')

for filename, short in ((ADMISSION, 'admission'), (SYNC, 'sync')):
    MUTATIONS[short + '_missing_host_compiler'] = edit_call(filename, ' --cc cc', '')
    MUTATIONS[short + '_mac_compiler'] = edit_call(filename, ' --cc cc', ' --cc /opt/homebrew/bin/gcc-16')
    MUTATIONS[short + '_target_compiler'] = edit_call(filename, ' --cc cc', ' --cc aarch64-openwrt-linux-gcc')

for name, array in ARRAYS.items():
    filename = CONSUMERS[name]
    prepare = logical_lines(PRODUCERS[name])[0]
    MUTATIONS[name + '_reassigned_old_input'] = insert_before_call(filename, name + '=/old/prepared')
    MUTATIONS[name + '_array_overridden'] = insert_before_call(filename, array + '[0]=/old/prepared')
    MUTATIONS[name + '_unset'] = insert_before_call(filename, 'unset ' + name)
    MUTATIONS[name + '_read_override'] = insert_before_call(filename, 'read -r ' + name)
    MUTATIONS[name + '_duplicate_selector'] = insert_before_call(filename, "mapfile -d '' " + array + ' < old.list')
    MUTATIONS[name + '_prepare_only_in_echo'] = (
        lambda t, p=prepare: replace_once(t, '          ' + p, '          echo "' + p + '"'))
    MUTATIONS[name + '_duplicate_prepare'] = insert_before_call(filename, prepare)

for label, old, new in (
        ('wifi_old_discovery_root', 'find build_dir -type f ' + chr(92), 'find old-prepared -type f ' + chr(92)),
        ('ssdk_old_discovery_root', "find build_dir -type f -path '*/qca-ssdk-", "find baseline -type f -path '*/qca-ssdk-"),
        ('dp_old_discovery_root', "find build_dir -type d -name 'qca-nss-dp-*'", "find old-prepared -type d -name 'qca-nss-dp-*'"),
        ('drv_old_discovery_root', "find build_dir -type d -name 'qca-nss-drv-*'", "find old-prepared -type d -name 'qca-nss-drv-*'"),
        ('wifi_missing_unique_guard', '"${#ath11k_core_files[@]}" -ne 1', '"${#ath11k_core_files[@]}" -eq 0'),
        ('ssdk_ambiguous_selection', 'test "${#ssdk_mib_files[@]}" -eq 1', 'test "${#ssdk_mib_files[@]}" -gt 0'),
        ('dp_missing_unique_guard', '"${#nss_dp_dirs[@]}" -ne 1', '"${#nss_dp_dirs[@]}" -eq 0'),
        ('drv_missing_unique_guard', '"${#nss_drv_dirs[@]}" -ne 1', '"${#nss_drv_dirs[@]}" -eq 0'),
        ('wifi_wrong_selected_slot', 'backports_dir=${ath11k_core_files[0]%', 'backports_dir=${ath11k_core_files[1]%'),
        ('ssdk_wrong_selected_slot', 'ssdk_dir=${ssdk_mib_files[0]%', 'ssdk_dir=${ssdk_mib_files[1]%'),
        ('dp_wrong_selected_slot', 'nss_dp_dir=${nss_dp_dirs[0]}', 'nss_dp_dir=${nss_dp_dirs[1]}'),
        ('drv_wrong_selected_slot', 'nss_drv_dir=${nss_drv_dirs[0]}', 'nss_drv_dir=${nss_drv_dirs[1]}'),
        ('drv_missing_file_guard', '          test -s "$nss_drv_dir/nss_core.c"\n', ''),
        ('dp_missing_file_guard', '          test -s "$nss_dp_dir/nss_dp_main.c"\n', ''),
        ('wifi_non_nul_selector', "mapfile -d '' ath11k_core_files", 'mapfile -t ath11k_core_files'),
        ('ssdk_non_nul_selector', "mapfile -d '' ssdk_mib_files", 'mapfile -t ssdk_mib_files'),
        ('dp_non_nul_selector', "mapfile -d '' nss_dp_dirs", 'mapfile -t nss_dp_dirs'),
        ('drv_non_nul_selector', "mapfile -d '' nss_drv_dirs", 'mapfile -t nss_drv_dirs')):
    MUTATIONS[label] = lambda t, a=old, b=new: replace_once(t, a, b)

for label, old, new in (
        ('clients_old_discovery', "find build_dir -type f -path '*/qca-nss-clients-", "find old-prepared -type f -path '*/qca-nss-clients-"),
        ('clients_non_unique', 'test "${#nss_clients_files[@]}" -eq 1', 'test "${#nss_clients_files[@]}" -gt 0'),
        ('clients_wrong_slot', 'nss_clients_dir=${nss_clients_files[0]%', 'nss_clients_dir=${nss_clients_files[1]%'),
        ('clients_non_nul', "mapfile -d '' nss_clients_files", 'mapfile -t nss_clients_files')):
    MUTATIONS[label] = lambda t, a=old, b=new: replace_once(t, a, b)


def mutation_test(mutate):
    def test(self):
        modified = mutate(self.workflow)
        self.assertNotEqual(modified, self.workflow, 'inactive negative control')
        with self.assertRaises(BindingError):
            validate(modified)
    return test


for label, mutate in MUTATIONS.items():
    setattr(HostGateBindings, 'test_reject_' + label, mutation_test(mutate))


if __name__ == '__main__':
    unittest.main()
