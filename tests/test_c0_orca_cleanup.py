# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Orca commands must never signal host processes using guest-writable state."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


C0 = Path(__file__).resolve().parents[1] / 'bin/c0'


class OrcaCleanup(unittest.TestCase):
    def test_orca_commands_ignore_legacy_host_forward_pid(self):
        source = C0.read_text()
        # Exercise the production command bodies with guest SSH stubbed. A
        # malicious PID file must neither cause host signals nor get consumed.
        names = ('cmd_orca_status', 'cmd_orca_start', 'cmd_orca_stop')
        functions = '\n'.join(
            re.search(r'^' + name + r'\(\) \{\n.*?^\}', source,
                      re.MULTILINE | re.DOTALL).group(0)
            for name in names
        )
        legacy = re.search(
            r'^c0_orca_drop_stale_localhost_forward\(\) \{\n.*?^\}',
            source, re.MULTILINE | re.DOTALL)
        if legacy:
            functions += '\n' + legacy.group(0)
        stubs = r'''
c0_ssh_ensure_keys() { :; }
c0_require_container_running() { :; }
c0_auth_env_load_exec_args() { :; }
c0_auth_env_export_for_sendenv() { :; }
get_c0_container_ip() { echo 192.0.2.10; }
print_orca_endpoint() { :; }
c0_orca_guest_listening() { [[ "$TEST_ORCA_COMMAND" != cmd_orca_stop ]]; }
c0_orca_print_serve_output() { :; }
c0_orca_ssh() { printf '%s' "$1" > "$C0ROOT/guest-script"; }
kill() { echo kill >> "$C0ROOT/host-signals"; }
pkill() { echo pkill >> "$C0ROOT/host-signals"; }
'''
        for command in names:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / '.local').mkdir()
                pidfile = root / '.local/c0-orca-forward.pid'
                pidfile.write_text(str(os.getpid()))
                env = dict(os.environ, C0ROOT=temp, TEST_ORCA_COMMAND=command,
                           C0DEV_ORCA_GUEST_PORT='3000',
                           C0_ORCA_PID_GUEST='/tmp/orca.pid',
                           CONTAINER_DEV_HOME='/home/dev')
                result = subprocess.run(
                    ['/bin/bash', '-c', functions + '\n' + stubs + '\n' + command],
                    env=env, text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((root / 'host-signals').exists())
                self.assertEqual(pidfile.read_text(), str(os.getpid()))
                if command == 'cmd_orca_stop':
                    self.assertIn('kill', (root / 'guest-script').read_text())


if __name__ == '__main__':
    unittest.main()
