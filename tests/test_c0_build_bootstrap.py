# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Build bootstrap with real SSH preparation and inert downstream build peers.

Oracle: docs/spec.md#attachments requires fresh management-key preparation and
retained guest server/auth state; c0 build is a supported artifact-construction
command. These checks cover its host preconditions, not Docker image contents.
All generated keys and paths belong to disposable synthetic checkouts.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'bin/c0').read_text()
FUNCTIONS = '\n'.join(
    re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE, re.M | re.S).group()
    for name in ('cmd_build', 'c0_build_steps', 'c0_build_wait_group',
                 'c0_build_cancel_group', 'c0_host_io', 'c0_ssh_ensure_keys',
                 'c0_ssh_write_sshd_config')
)


class BuildBootstrap(unittest.TestCase):
    def setUp(self):
        if not shutil.which('ssh-keygen'):
            self.skipTest('local ssh-keygen required for temporary fixture keys')
        temporary = tempfile.TemporaryDirectory(prefix='c0-build-bootstrap-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / 'checkout ; literal $ name'
        self.checkout.mkdir()
        self.guest = self.checkout / 'auth/ssh'
        self.client = self.checkout / 'auth/ssh-client'
        self.trace = self.root / 'build.trace'
        self.script = self.root / 'build.sh'
        self.script.write_text('set -e\n' + FUNCTIONS + r'''
require_host() { :; }
verify_moby_seccomp_profile() { :; }
maybe_notify_seccomp_update_available() { :; }
validate_host_paths() { :; }
c0_prepare_build_context() { mkdir -p "$C0_BUILD_CONTEXT"; }
c0_resolve_toolchain() { echo releases >> "$TEST_BUILD_TRACE"; }
c0_build_base_image() { echo base >> "$TEST_BUILD_TRACE"; }
build_tools_volume() { echo tools >> "$TEST_BUILD_TRACE"; }
c0_prepare_terminfo() { :; }
c0_prepare_runtime_dockerfile() { :; }
c0_build_runtime_image() { echo runtime >> "$TEST_BUILD_TRACE"; }
gc_tools_hashes() { echo gc >> "$TEST_BUILD_TRACE"; }
cmd_build
''')
        self.env = dict(os.environ, C0ROOT=str(self.checkout),
                        C0_HOST_IO=str(ROOT / 'bin/c0-host-io'),
                        C0_SSH_DIR=str(self.guest),
                        C0_SSH_CLIENT_DIR=str(self.client),
                        C0_INSTANCE_ID='synthetic-build-bootstrap',
                        C0_SSH_AUTH_SOCK_PATH='/tmp/c0-synthetic-agent.sock',
                        IN_CONTAINER='false', TEST_BUILD_TRACE=str(self.trace))

    def build(self):
        return subprocess.run(['/bin/bash', str(self.script)], env=self.env,
                              cwd=self.root, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=10)

    def assert_completed(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.trace.read_text().splitlines(),
                         ['releases', 'base', 'tools', 'runtime', 'gc'])
        self.assertIn('Build complete', result.stdout)

    def test_fresh_checkout_build_bootstraps_missing_ssh_directories(self):
        self.assertFalse((self.checkout / 'auth').exists())
        self.assert_completed(self.build())

    def test_build_with_existing_empty_guest_auth_directory(self):
        # The existing suites always supplied this otherwise hidden precondition.
        self.guest.mkdir(parents=True)
        self.assert_completed(self.build())

    def test_build_refuses_redirected_guest_auth_before_artifact_work(self):
        outside = self.root / 'outside-auth'
        outside.mkdir()
        sentinel = outside / 'retained-file'
        sentinel.write_text('synthetic retained material\n')
        self.guest.parent.mkdir()
        self.guest.symlink_to(outside, target_is_directory=True)
        before_mode = outside.stat().st_mode
        result = self.build()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('Build complete', result.stdout)
        self.assertFalse(self.trace.exists())
        self.assertEqual(sentinel.read_text(), 'synthetic retained material\n')
        self.assertEqual(set(path.name for path in outside.iterdir()),
                         {'retained-file'})
        self.assertEqual(outside.stat().st_mode, before_mode)


if __name__ == '__main__':
    unittest.main()
