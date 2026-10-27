# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Synthetic regressions; no Docker daemon, SSH transport, or private user data.

Oracles: docs/spec.md#containment,#host-mounts,#private-data and
docs/tool-store-contract.md, admitted at 4580afa. Shell functions are the real
CLI implementation. Peers model orchestration only, not kernel isolation.
"""
import json
import hashlib
from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def definitions():
    source = (ROOT / 'bin/c0').read_text()
    functions = []
    # Inline helper scripts may themselves contain unindented closing braces.
    # Select the first *complete shell function*, without executing its body.
    for start in re.finditer(r'^\w+\(\) \{\n', source, re.M):
        for end in re.finditer(r'^\}', source[start.end():], re.M):
            candidate = source[start.start():start.end() + end.end()]
            parsed = subprocess.run(['/bin/bash', '-n'], input=candidate,
                                    capture_output=True, text=True, timeout=3)
            if parsed.returncode == 0:
                functions.append(candidate)
                break
        else:
            raise AssertionError('incomplete production function: ' + start.group())
    return '\n'.join(functions)


class HostPaths(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='c0-host-boundary-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'checkout ; literal $ name'
        self.ssh = self.workspace / 'auth/ssh'
        self.ssh.mkdir(parents=True)
        self.log = self.workspace / '.local-rw/orca-serve.log'
        self.log.parent.mkdir()
        self.neighbor = self.root / 'unrelated-private-file'
        self.neighbor.write_text('SYNTHETIC PRIVATE NEIGHBOR\nPairing URL: synthetic-neighbor\n')
        self.neighbor.chmod(0o600)
        self.original = self.neighbor.read_bytes()
        self.env = dict(os.environ, C0ROOT=str(self.workspace), C0_HOST_IO=str(ROOT / 'bin/c0-host-io'),
                        C0_SSH_DIR=str(self.ssh),
                        C0_ORCA_LOG_HOST=str(self.log), C0_SSH_AUTH_SOCK_PATH='/tmp/c0-agent.sock',
                        C0DEV_ORCA_GUEST_PORT='4555', CONTAINER_DEV_HOME='/home/dev',
                        C0_ORCA_LOG_GUEST='/home/dev/.local-rw/orca-serve.log',
                        C0_ORCA_PID_GUEST='/home/dev/.local-rw/orca-serve.pid',
                        C0_INSTANCE_ID='synthetic-security-fixture',
                        TEST_TRACE=str(self.root / 'trace'), PYTHONDONTWRITEBYTECODE='1')

    def call(self, command, setup=''):
        script = self.root / 'exercise.sh'
        script.write_text('set -e\n' + definitions() + r'''
c0_ssh_ensure_keys() { :; }
c0_require_container_running() { :; }
c0_auth_env_load_exec_args() { :; }
c0_auth_env_export_for_sendenv() { :; }
get_c0_container_ip() { echo 192.0.2.10; }
print_orca_endpoint() { :; }
c0_orca_guest_listening() { return 1; }
c0_orca_ssh() { echo launched >> "$TEST_TRACE"; }
orca_remote_display() { echo synthetic-peer; }
sleep() { :; }
''' + setup + '\n' + command + '\n')
        proc = subprocess.Popen(['/bin/bash', str(script)], cwd=self.root, env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        try:
            out, err = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            self.fail('host path operation blocked while opening untrusted file')
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)

    def preserved(self, result):
        self.assertEqual(self.neighbor.read_bytes(), self.original)
        self.assertEqual(self.neighbor.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('SYNTHETIC PRIVATE NEIGHBOR', result.stdout + result.stderr)
        self.assertNotIn('synthetic-neighbor', result.stdout + result.stderr)

    def redirect(self, target, kind):
        if kind == 'leaf':
            target.symlink_to(self.neighbor)
        elif kind == 'hardlink':
            os.link(self.neighbor, target)
        else:
            saved = target.parent.with_name(target.parent.name + '-outside')
            target.parent.rename(saved)
            target.parent.symlink_to(saved, target_is_directory=True)
            (saved / target.name).write_bytes(self.original)
            return saved / target.name
        return self.neighbor

    def cleanup_redirect(self, target, redirected):
        if target.exists() or target.is_symlink():
            target.unlink()
        if target.parent.is_symlink():
            target.parent.unlink()
            redirected.parent.rename(target.parent)
        self.neighbor.write_bytes(self.original)
        self.neighbor.chmod(0o600)
        (self.root / 'trace').unlink(missing_ok=True)

    def test_config_normal_path_preserves_content_mode_and_literal_punctuation(self):
        result = self.call('c0_ssh_write_sshd_config')
        self.assertEqual(result.returncode, 0, result.stderr)
        content = (self.ssh / 'sshd_config').read_text()
        for line in ('Port 2222', 'PasswordAuthentication no', 'AcceptEnv *',
                     'SetEnv SSH_AUTH_SOCK=/tmp/c0-agent.sock'):
            self.assertIn(line + '\n', content)
        self.assertEqual((self.ssh / 'sshd_config').stat().st_mode & 0o777, 0o644)
        self.preserved(result)

    def seed_existing_ssh_material(self):
        self.ssh.chmod(0o755)
        material = {}
        for name in ('id_ed25519', 'id_ed25519.pub', 'ssh_host_ed25519_key',
                     'ssh_host_ed25519_key.pub', 'authorized_keys'):
            content = 'synthetic existing ' + name + '\n'
            (self.ssh / name).write_text(content)
            (self.ssh / name).chmod(0o600)
            material[name] = content
        peer_bin = self.root / 'ssh-peers'
        peer_bin.mkdir(exist_ok=True)
        (peer_bin / 'ssh-keygen').write_text(
            '#!/bin/sh\necho unexpected-keygen >>"$TEST_TRACE"\nexit 91\n')
        (peer_bin / 'ssh-keygen').chmod(0o755)
        self.env['PATH'] = str(peer_bin) + os.pathsep + os.environ['PATH']
        return material

    def test_existing_ssh_keys_and_authorization_are_retained_without_key_generation(self):
        material = self.seed_existing_ssh_material()
        result = self.call('c0_ssh_keygen')
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, content in material.items():
            self.assertEqual((self.ssh / name).read_text(), content)
        self.assertFalse((self.root / 'trace').exists())
        self.preserved(result)

    def test_fresh_ssh_keys_are_created_privately_and_retained_on_repeat(self):
        if not shutil.which('ssh-keygen'):
            self.skipTest('local ssh-keygen required for temporary fixture keys')
        result = self.call('c0_ssh_keygen')
        self.assertEqual(result.returncode, 0, result.stderr)
        names = ('id_ed25519', 'id_ed25519.pub', 'ssh_host_ed25519_key',
                 'ssh_host_ed25519_key.pub', 'authorized_keys')
        digests = {}
        for name in names:
            path = self.ssh / name
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 0)
            digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(digests['authorized_keys'], digests['id_ed25519.pub'])
        self.assertEqual(self.ssh.stat().st_mode & 0o777, 0o700)
        for name in ('id_ed25519', 'ssh_host_ed25519_key', 'authorized_keys'):
            self.assertEqual((self.ssh / name).stat().st_mode & 0o777, 0o600)
        repeated = self.call('c0_ssh_keygen')
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        for name, digest in digests.items():
            self.assertEqual(hashlib.sha256((self.ssh / name).read_bytes()).hexdigest(), digest)
        self.preserved(result)
        self.preserved(repeated)

    def test_ssh_key_preparation_refuses_authorization_and_public_key_redirects(self):
        for name in ('authorized_keys', 'id_ed25519.pub'):
            for kind in ('leaf', 'ancestor'):
                with self.subTest(name=name, kind=kind):
                    self.seed_existing_ssh_material()
                    if name == 'id_ed25519.pub':
                        # Exercise the real missing-authorization copy path:
                        # redirected public material must never populate it.
                        (self.ssh / 'authorized_keys').write_text('')
                    target = self.ssh / name
                    target.unlink()
                    redirected = self.redirect(target, kind)
                    before = redirected.read_bytes()
                    directory_mode = self.ssh.stat().st_mode & 0o777
                    try:
                        result = self.call('c0_ssh_keygen')
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(redirected.read_bytes(), before)
                        self.assertEqual(self.ssh.stat().st_mode & 0o777, directory_mode)
                        self.assertFalse((self.root / 'trace').exists())
                        if name == 'id_ed25519.pub':
                            self.assertEqual((self.ssh / 'authorized_keys').read_text(), '')
                        self.preserved(result)
                    finally:
                        self.cleanup_redirect(target, redirected)

    def test_config_redirect_cannot_overwrite_neighbor(self):
        for kind in ('leaf', 'ancestor', 'hardlink'):
            with self.subTest(kind=kind):
                # Each variation owns all paths, including symlink targets.
                target = self.ssh / 'sshd_config'
                redirected = self.redirect(target, kind)
                try:
                    before = redirected.read_bytes()
                    result = self.call('c0_ssh_write_sshd_config')
                    self.assertEqual(redirected.read_bytes(), before)
                    self.preserved(result)
                    self.assertNotEqual(result.returncode, 0)
                finally:
                    self.cleanup_redirect(target, redirected)

    def test_log_reset_normal_path_keeps_launch_and_neighbor(self):
        self.log.write_text('old output\n')
        result = self.call('cmd_orca_start', 'c0_orca_wait_for_urls() { :; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text(), '')
        self.assertEqual((self.root / 'trace').read_text(), 'launched\n')
        self.preserved(result)

    def test_log_reset_refuses_redirect_before_guest_launch(self):
        for kind in ('leaf', 'ancestor', 'hardlink'):
            with self.subTest(kind=kind):
                redirected = self.redirect(self.log, kind)
                try:
                    before = redirected.read_bytes()
                    result = self.call('cmd_orca_start', 'c0_orca_wait_for_urls() { :; }')
                    self.assertEqual(redirected.read_bytes(), before)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((self.root / 'trace').exists())
                    self.preserved(result)
                finally:
                    self.cleanup_redirect(self.log, redirected)

    def test_log_read_normal_path_retains_output_and_pairing_detection(self):
        text = 'starting\nPairing URL: synthetic-intended\n'
        self.log.write_text(text)
        for command in ('c0_orca_print_serve_output', 'c0_orca_wait_for_urls'):
            with self.subTest(command=command):
                result = self.call(command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, text)
                self.preserved(result)

    def test_log_reads_never_disclose_redirected_neighbor(self):
        for kind in ('leaf', 'ancestor', 'hardlink'):
            with self.subTest(kind=kind):
                redirected = self.redirect(self.log, kind)
                try:
                    for command in ('c0_orca_print_serve_output', 'c0_orca_wait_for_urls'):
                        with self.subTest(command=command):
                            result = self.call(command)
                            self.preserved(result)
                            self.assertNotEqual(result.returncode, 0)
                finally:
                    self.cleanup_redirect(self.log, redirected)

    def test_nonregular_config_and_logs_refuse_without_opening_fifo(self):
        cases = ((self.ssh / 'sshd_config', 'c0_ssh_write_sshd_config'),
                 (self.log, 'c0_orca_print_serve_output'),
                 (self.log, 'cmd_orca_start'))
        for target, command in cases:
            with self.subTest(command=command):
                os.mkfifo(target)
                try:
                    result = self.call(command, 'c0_orca_wait_for_urls() { :; }')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((self.root / 'trace').exists())
                    self.preserved(result)
                finally:
                    target.unlink()


class OverlayBoundary(unittest.TestCase):
    def test_privileged_namespace_entry_preserves_helper_program_root(self):
        with tempfile.TemporaryDirectory(prefix='c0-helper-boundary-') as temp:
            root = Path(temp)
            peer = root / 'docker'
            peer.write_text('#!' + sys.executable + '\n' + r'''
import json, os, sys
from pathlib import Path
Path(os.environ['TEST_ARGS']).write_text(json.dumps(sys.argv[1:]))
''')
            peer.chmod(0o755)
            source = definitions() + '\nc0_mount_home_overlay inert-container .local .local\n'
            script = root / 'exercise.sh'
            script.write_text(source)
            result = subprocess.run(['/bin/bash', str(script)], capture_output=True, text=True,
                                    env=dict(os.environ, PATH=temp + os.pathsep + os.environ['PATH'],
                                             TEST_ARGS=str(root / 'args'), TOOLS_PREFIX='/tools/current',
                                             TOOLS_ID='a' * 64), timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            args = json.loads((root / 'args').read_text())
            namespace = args[args.index('nsenter') + 1:args.index('--')]
            self.assertTrue('-m' in namespace or '--mount' in namespace)
            roots = [arg.partition('=')[2] for arg in namespace if arg.startswith('--root=')]
            self.assertEqual(len(roots), 1)
            held = re.fullmatch(r'/proc/self/fd/([0-9]+)', roots[0])
            self.assertIsNotNone(held, 'executable root must be a held helper-root descriptor')
            working = [arg.partition('=')[2] for arg in namespace if arg.startswith('--wd=')]
            self.assertEqual(len(working), 1)
            held_proc = re.fullmatch(r'/proc/self/fd/([0-9]+)', working[0])
            self.assertIsNotNone(held_proc, 'working directory must be held original proc')
            self.assertNotEqual(held.group(1), held_proc.group(1))
            self.assertFalse(any(arg in ('-r', '-w', '--root', '--wd') or
                                 arg.startswith('--wd=/proc/1/root') for arg in namespace),
                             'guest root/cwd must not select helper executable or loader')
            self.assertIn('--read-only', args)
            self.assertEqual(args[args.index('--network') + 1], 'none')
            # Execute the actual pre-entry wrapper against an inert nsenter peer.
            # Opening / before the namespace transition must leave a directory
            # FD referring to this helper process's root, not the target root.
            namespace_peer = root / 'nsenter-peer'
            namespace_peer.write_text('#!' + sys.executable + '\n' + r'''
import json, os, stat, sys
from pathlib import Path
held = os.fstat(int(os.environ['TEST_ROOT_FD']))
current = os.stat('/')
held_proc = os.fstat(int(os.environ['TEST_PROC_FD']))
original_proc = os.stat(os.environ['TEST_PREENTRY_PROC'])
Path(os.environ['TEST_ROOT_PROOF']).write_text(json.dumps({
    'directory': stat.S_ISDIR(held.st_mode),
    'same_root': (held.st_dev, held.st_ino) == (current.st_dev, current.st_ino),
    'proc_directory': stat.S_ISDIR(held_proc.st_mode),
    'same_proc': (held_proc.st_dev, held_proc.st_ino) ==
                 (original_proc.st_dev, original_proc.st_ino)}))
''')
            namespace_peer.chmod(0o755)
            wrapper = args[args.index('alpine') + 1:]
            wrapper[wrapper.index('nsenter')] = str(namespace_peer)
            preentry_index = wrapper.index('-c') + 1
            proc_open = r'(?P<open>\bexec\s+' + held_proc.group(1) + r'\s*<\s*)/proc(?=\s*;|\s*$)'
            self.assertRegex(wrapper[preentry_index], proc_open)
            preentry_proc = Path('/proc')
            if not preentry_proc.is_dir():
                # macOS has no procfs. Substitute only this pre-entry directory
                # open; the native opt-in fixture verifies Linux procfs itself.
                preentry_proc = root / 'preentry-proc'
                preentry_proc.mkdir()
                wrapper[preentry_index] = re.sub(
                    proc_open, lambda match: match.group('open') + str(preentry_proc),
                    wrapper[preentry_index])
            proof = subprocess.run(wrapper, capture_output=True, text=True, timeout=5,
                                   env=dict(os.environ, TEST_ROOT_FD=held.group(1),
                                            TEST_PROC_FD=held_proc.group(1),
                                            TEST_PREENTRY_PROC=str(preentry_proc),
                                            TEST_ROOT_PROOF=str(root / 'root-proof')))
            self.assertEqual(proof.returncode, 0, proof.stderr)
            self.assertEqual(json.loads((root / 'root-proof').read_text()),
                             {'directory': True, 'same_root': True,
                              'proc_directory': True, 'same_proc': True})

    def test_overlay_checker_accepts_guest_root_prefix_and_rejects_other_lowers(self):
        with tempfile.TemporaryDirectory(prefix='c0-overlay-binding-') as temp:
            root = Path(temp)
            policy = root / 'policy'
            policy.write_text('.local|.local\n')
            peer = root / 'findmnt'
            peer.write_text('#!' + sys.executable + '\n' + r'''
import os, sys
args = sys.argv[1:]
if args[-1] == 'FSTYPE': print('overlay')
elif args[args.index('-T') + 1] == '/tools/current/.local': print('ro,relatime')
else: print('rw,lowerdir=' + os.environ['TEST_LOWER'] + ',upperdir=/state/upper/local')
''')
            peer.chmod(0o755)
            for lower, accepted in (('/tools/current/.local', True),
                                    ('/proc/1/root/tools/current/.local', True),
                                    ('1/root/tools/current/.local', True),
                                    ('/proc/2/root/tools/current/.local', False),
                                    ('2/root/tools/current/.local', False),
                                    ('/proc/1/root/tools/current/.local-foreign', False),
                                    ('1/root/tools/current/.local-foreign', False)):
                with self.subTest(lower=lower):
                    result = subprocess.run(['/bin/bash', str(ROOT / 'docker/c0-overlay-check')],
                                            capture_output=True, text=True, timeout=10,
                                            env=dict(os.environ, PATH=temp + os.pathsep + os.environ['PATH'],
                                                     HOME=str(root / 'home'), TOOLS_PREFIX='/tools/current',
                                                     C0_HOME_OVERLAYS_FILE=str(policy),
                                                     C0_OVERLAY_STATE_ROOT=str(root / 'state'), TEST_LOWER=lower))
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)


class SnapshotBoundary(unittest.TestCase):
    def test_snapshot_retains_helper_root_proc_metadata_and_resumes_same_guest_after_failure(self):
        for fail_capture in (False, True):
            with self.subTest(fail_capture=fail_capture), tempfile.TemporaryDirectory(
                    prefix='c0-snapshot-boundary-') as temporary:
                root = Path(temporary)
                snapshot = root / 'snapshot'
                snapshot.mkdir()
                policy = root / 'policy'
                policy.write_text('.local|.local\n')
                peer = root / 'docker'
                peer.write_text('#!' + sys.executable + '\n' + r'''
import io, json, os, sys, tarfile
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['TEST_CALLS'], 'a') as output:
    output.write(json.dumps(args) + '\n')
if args[0] in ('pause', 'unpause'): sys.exit(0)
if args[0] != 'run': sys.exit(98)
if os.environ['TEST_FAIL_CAPTURE'] == '1': sys.exit(29)
data = b'synthetic snapshot\n'
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
    member = tarfile.TarInfo('.local/packaged')
    member.size = len(data)
    archive.addfile(member, io.BytesIO(data))
''')
                peer.chmod(0o755)
                script = root / 'snapshot.sh'
                script.write_text('set -e\n' + definitions() +
                                  '\nc0_snapshot_home_overlays exact-owned-guest "$TEST_SNAPSHOT"\n')
                result = subprocess.run(
                    ['/bin/bash', str(script)], capture_output=True, text=True, timeout=10,
                    env=dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                             TEST_CALLS=str(root / 'calls'), TEST_FAIL_CAPTURE=str(int(fail_capture)),
                             TEST_SNAPSHOT=str(snapshot), HOME_OVERLAYS_FILE=str(policy),
                             C0_TOOLS_HELPER_IMAGE='synthetic-snapshot-helper',
                             PYTHONDONTWRITEBYTECODE='1'))
                calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
                self.assertEqual(calls[0], ['pause', 'exact-owned-guest'])
                self.assertEqual(calls[-1], ['unpause', 'exact-owned-guest'])
                self.assertEqual([args[0] for args in calls], ['pause', 'run', 'unpause'])
                args = calls[1]
                self.assertIn('--pid=container:exact-owned-guest', args)
                self.assertIn('--read-only', args)
                self.assertEqual(args[args.index('--network') + 1], 'none')
                self.assertFalse(any(arg in ('-v', '--mount') for arg in args))
                if fail_capture:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((snapshot / 'policy').exists())
                    continue
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((snapshot / 'policy').read_text(), '.local|.local|local.tar\n')
                with tarfile.open(snapshot / 'local.tar') as archive:
                    self.assertEqual(archive.getnames(), ['.local/packaged'])
                    self.assertEqual(archive.extractfile('.local/packaged').read(), b'synthetic snapshot\n')
                for flag in ('--xattrs', '--xattrs-include=*', '--acls', '--numeric-owner'):
                    self.assertIn(flag, args)
                self.assertEqual(args[-3:], ['-cf', '-', '.local'])
                namespace_start = args.index('/usr/bin/nsenter')
                namespace_end = args.index('--', namespace_start)
                namespace = args[namespace_start + 1:namespace_end]
                self.assertIn('-m', namespace)
                self.assertFalse(any(arg in ('-r', '-w', '--root', '--wd') for arg in namespace))
                held = {}
                for option in ('--root', '--wd'):
                    values = [arg.partition('=')[2] for arg in namespace if arg.startswith(option + '=')]
                    self.assertEqual(len(values), 1)
                    match = re.fullmatch(r'/proc/self/fd/([0-9]+)', values[0])
                    self.assertIsNotNone(match, 'snapshot programs must retain helper root and proc')
                    held[option] = match.group(1)
                self.assertNotEqual(held['--root'], held['--wd'])
                self.assertEqual(args[args.index('-C') + 1], '1/root/home/dev')

                # Replay only the protected pre-entry wrapper with an inert
                # namespace executable; never execute nsenter or captured tar.
                entrypoint = args[args.index('--entrypoint') + 1]
                self.assertEqual(entrypoint, '/bin/sh')
                wrapper = [entrypoint, *args[args.index('synthetic-snapshot-helper') + 1:]]
                namespace_peer = root / 'snapshot-nsenter-peer'
                namespace_peer.write_text('#!' + sys.executable + '\n' + r'''
import json, os, stat
from pathlib import Path
root = os.fstat(int(os.environ['TEST_ROOT_FD']))
proc = os.fstat(int(os.environ['TEST_PROC_FD']))
expected_root, expected_proc = os.stat('/'), os.stat(os.environ['TEST_ORIGINAL_PROC'])
Path(os.environ['TEST_PROOF']).write_text(json.dumps({
    'root': stat.S_ISDIR(root.st_mode) and (root.st_dev, root.st_ino) ==
            (expected_root.st_dev, expected_root.st_ino),
    'proc': stat.S_ISDIR(proc.st_mode) and (proc.st_dev, proc.st_ino) ==
            (expected_proc.st_dev, expected_proc.st_ino)}))
''')
                namespace_peer.chmod(0o755)
                wrapper[wrapper.index('/usr/bin/nsenter')] = str(namespace_peer)
                opener = wrapper.index('-c') + 1
                proc_open = r'(?P<open>\bexec\s+' + held['--wd'] + r'\s*<\s*)/proc(?=\s*;|\s*$)'
                self.assertRegex(wrapper[opener], proc_open)
                original_proc = Path('/proc')
                if not original_proc.is_dir():
                    original_proc = root / 'original-proc'
                    original_proc.mkdir()
                    wrapper[opener] = re.sub(proc_open, lambda match: match.group('open') +
                                            str(original_proc), wrapper[opener])
                proof = subprocess.run(
                    wrapper, capture_output=True, text=True, timeout=5,
                    env=dict(os.environ, TEST_ROOT_FD=held['--root'], TEST_PROC_FD=held['--wd'],
                             TEST_ORIGINAL_PROC=str(original_proc), TEST_PROOF=str(root / 'proof')))
                self.assertEqual(proof.returncode, 0, proof.stderr)
                self.assertEqual(json.loads((root / 'proof').read_text()), {'root': True, 'proc': True})


class ToolsExtractionBoundary(unittest.TestCase):
    """Docker is an inert peer which models a hostile image's startup effect.

    It never runs image code. The hook witness writes only our synthetic store
    sentinel if orchestration grants a constructed image a writable store.
    This verifies authority separation, not Docker copy or tar semantics.
    """
    def exercise(self, *, fail_copy=False, source_conflict='none'):
        temp = tempfile.TemporaryDirectory(prefix='c0-extraction-boundary-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        state = root / 'peer.json'
        sentinel = root / 'published-snapshot'
        sentinel.write_text('selected immutable payload\n')
        state.write_text(json.dumps(dict(calls=[], containers={
            'c0dev-tools-build': {'unrelated': True},
            'c0dev-tools': {'unrelated': True}})))
        peer = root / 'docker'
        peer.write_text('#!' + sys.executable + '\n' + r'''
import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
path = Path(os.environ['TEST_STATE'])
state = json.loads(path.read_text())
state['calls'].append(args)
def done(code=0, output=''):
    path.write_text(json.dumps(state))
    if output: print(output)
    sys.exit(code)
def values(flag): return [args[i+1] for i, v in enumerate(args[:-1]) if v == flag]
if args[0] == 'run':
    builder = any(a.startswith('c0dev-tools-builder-') for a in args)
    writable = any(':/' in v and not v.endswith(':ro') for v in values('-v'))
    writable |= any('dst=/tools' in v and 'readonly' not in v for v in values('--mount'))
    if builder and writable:
        Path(os.environ['TEST_SENTINEL']).write_text('startup hook overwrote neighbor\n')
    done()
if args[0] == 'create':
    labels = dict(v.split('=', 1) for v in values('--label'))
    cid = 'e' * 64
    state['containers'][cid] = dict(labels=labels, args=args)
    done(output=cid)
if args[0] == 'inspect':
    cid = next((a for a in args if a in state['containers']), None)
    if cid is None: done(1)
    c = state['containers'][cid]
    if os.environ['TEST_SOURCE_CONFLICT'] == 'foreign':
        c = dict(c, labels={'c0dev.extraction_operation': 'foreign-operation'})
    status = 'running' if os.environ['TEST_SOURCE_CONFLICT'] == 'running' else 'created'
    fmt = (values('--format') or values('-f') or [''])[0]
    if fmt:
        if '.Id' in fmt: done(output=cid)
        if '.State.Status' in fmt: done(output=status)
        import re
        keys = re.findall(r'"([^"]+)"', fmt)
        if keys: done(output=c.get('labels', {}).get(keys[-1], ''))
        if 'Labels' in fmt: done(output=json.dumps(c.get('labels', {})))
    done(output=json.dumps([dict(Id=cid, State=dict(Status=status, Running=status == 'running'),
                                Config=dict(Labels=c.get('labels', {})))]))
if args[0] == 'cp':
    if os.environ['TEST_FAIL_COPY'] == '1': done(29)
    dest = Path(args[-1])
    dest.mkdir(parents=True, exist_ok=True)
    # Only synthetic data; preserve a nested symlink as Docker's stopped copy would.
    for name in ('.cargo/bin', '.rustup', '.local/share/c0'):
        (dest / name).mkdir(parents=True, exist_ok=True)
    (dest / '.cargo/bin/tool').write_text('synthetic executable\n')
    (dest / '.cargo/bin/tool').chmod(0o755)
    (dest / '.cargo/bin/tool-link').symlink_to('tool')
    (dest / '.local/share/c0/toolchain.json').write_text('{}\n')
    done()
if args[0] == 'rm':
    for arg in args[1:]: state['containers'].pop(arg, None)
    done()
if args[0] in ('build', 'rmi') or args[:2] == ['volume', 'create']: done()
done(98, 'unexpected inert Docker request: ' + repr(args))
''')
        peer.chmod(0o755)
        script = root / 'build.sh'
        script.write_text('set -e\n' + definitions() + r'''
verify_moby_seccomp_profile() { :; }
maybe_promote_staged_next() { :; }
tools_volume_build_matches() { :; }
c0_prepare_tools_dockerfile() { :; }
tools_volume_admin_sh() { :; }
get_active_hashes() { :; }
C0_TOOLCHAIN_BUILD_ARGS=()
build_tools_volume true
''')
        result = subprocess.run(['/bin/bash', str(script)], cwd=root, capture_output=True,
                                text=True, timeout=10,
                                env=dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                                         C0ROOT=str(ROOT), C0_BUILD_CONTEXT=str(root),
                                         C0_BASE_IMAGE='fixed-publisher-image',
                                         DOCKERFILE_TOOLS_BUILD=str(root / 'Dockerfile'),
                                         TOOLS_BUILD_ID='a' * 64, SHARED_TOOLS_VOLUME='synthetic-store',
                                         MAIN_SERVICE='c0dev', C0_MODE_KEY='prod',
                                         TEST_STATE=str(state), TEST_SENTINEL=str(sentinel),
                                         TEST_FAIL_COPY=str(int(fail_copy)),
                                         TEST_SOURCE_CONFLICT=source_conflict,
                                         PYTHONDONTWRITEBYTECODE='1'))
        return result, json.loads(state.read_text()), sentinel.read_text()

    def test_constructed_image_is_copied_stopped_without_store_or_network_authority(self):
        result, state, sentinel = self.exercise()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sentinel, 'selected immutable payload\n')
        executions = [a for a in state['calls'] if a[0] in ('run', 'start', 'exec') and
                      any(v.startswith('c0dev-tools-builder-') for v in a)]
        self.assertEqual(executions, [], 'constructed image startup is not a trusted publisher')
        creates = [a for a in state['calls'] if a[0] == 'create']
        self.assertEqual(len(creates), 1)
        self.assertTrue('--network=none' in creates[0] or
                        any(creates[0][i:i+2] == ['--network', 'none']
                            for i in range(len(creates[0]) - 1)))
        self.assertFalse(any('synthetic-store' in v for v in creates[0]))
        self.assertTrue(any(a[0] == 'cp' for a in state['calls']))
        publishers = [a for a in state['calls'] if a[0] == 'run' and
                      any('synthetic-store' in v for v in a)]
        self.assertTrue(publishers, 'payload publication still runs through a trusted writer')
        for args in publishers:
            self.assertIn('--read-only', args)
            self.assertTrue('--network=none' in args or
                            any(args[i:i+2] == ['--network', 'none'] for i in range(len(args)-1)))

    def test_build_preserves_unattributed_fixed_name_containers(self):
        for fail_copy in (False, True):
            with self.subTest(fail_copy=fail_copy):
                result, state, sentinel = self.exercise(fail_copy=fail_copy)
                self.assertEqual(set(('c0dev-tools-build', 'c0dev-tools')) & set(state['containers']),
                                 {'c0dev-tools-build', 'c0dev-tools'})
                self.assertEqual(sentinel, 'selected immutable payload\n')
                if fail_copy:
                    self.assertNotEqual(result.returncode, 0)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(set(state['containers']), {'c0dev-tools-build', 'c0dev-tools'},
                                 'only the source created by this operation may be cleaned up')

    def test_cleanup_retains_source_when_ownership_or_stopped_state_is_uncertain(self):
        for conflict in ('foreign', 'running'):
            with self.subTest(conflict=conflict):
                result, state, sentinel = self.exercise(fail_copy=True, source_conflict=conflict)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('e' * 64, state['containers'])
                self.assertEqual(sentinel, 'selected immutable payload\n')
                removals = [a for a in state['calls'] if a[0] == 'rm']
                self.assertFalse(any('e' * 64 in a for a in removals))


class ToolsPayloadBoundary(unittest.TestCase):
    """Execute the fixed publisher script using owned directory mount mappings.

    The peer substitutes only /payload and /tools, then runs the literal script
    with real file-copy tools. chown is inert: this test proves file selection,
    links, metadata and completion, not Docker permissions or UID normalization.
    """
    def exercise(self, *, redirected_root=None):
        temp = tempfile.TemporaryDirectory(prefix='c0-publisher-boundary-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        payload = root / 'payload'
        store = root / 'store'
        for name in ('.cargo/bin', '.rustup/toolchains', '.local/share/c0'):
            (payload / name).mkdir(parents=True)
        tool = payload / '.cargo/bin/tool'
        tool.write_text('synthetic executable\n')
        tool.chmod(0o755)
        os.utime(tool, (1234567890, 1234567890))
        (payload / '.cargo/bin/tool-link').symlink_to('tool')
        (payload / '.rustup/toolchains/tool').write_text('synthetic rustup\n')
        manifest = '{"fixture":"synthetic manifest"}\n'
        (payload / '.local/share/c0/toolchain.json').write_text(manifest)
        (payload / 'private-auth').write_text('synthetic excluded input\n')
        selected = store / ('opt/' + 'b' * 64 + '/retained')
        selected.parent.mkdir(parents=True)
        selected.write_text('retained selected payload\n')
        (store / ('tmp/' + 'a' * 64 + '.partial')).mkdir(parents=True)
        cache = store / 'cache/retained'
        cache.parent.mkdir()
        cache.write_text('retained cache\n')
        outside = root / 'outside-local'
        if redirected_root:
            (payload / redirected_root).rename(outside)
            (outside / 'neighbor').write_text('SYNTHETIC OUTSIDE PRIVATE\n')
            (payload / redirected_root).symlink_to(outside, target_is_directory=True)
        bin_dir = root / 'peers'
        bin_dir.mkdir()
        (bin_dir / 'chown').write_text('#!/bin/sh\nexit 0\n')
        (bin_dir / 'chown').chmod(0o755)
        # The production publisher runs in Alpine; GNU cp gives the same command
        # options on developer hosts whose native cp lacks those flags.
        copy = shutil.which('gcp') or shutil.which('cp')
        (bin_dir / 'cp').symlink_to(copy)
        peer = bin_dir / 'docker'
        peer.write_text('#!' + sys.executable + '\n' + r'''
import json, os, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
Path(os.environ['TEST_ARGS']).write_text(json.dumps(args))
if args[0] != 'run': sys.exit(98)
def mapped(text):
    return text.replace('/payload', os.environ['TEST_PAYLOAD']).replace('/tools', os.environ['TEST_STORE'])
if '-s' in args:
    index = args.index('-s')
    script = mapped(sys.stdin.read())
    positional = args[index+1:]
    if positional[:1] == ['--']: positional = positional[1:]
    positional = ['c0-publisher', *positional]
elif '-c' in args:
    index = args.index('-c')
    script = mapped(args[index+1])
    positional = args[index+2:]
else: sys.exit(98)
sys.exit(subprocess.run(['/bin/sh', '-eu', '-c', script,
                         *[mapped(a) for a in positional]]).returncode)
''')
        peer.chmod(0o755)
        script = root / 'publish.sh'
        script.write_text('set -e\n' + definitions() +
                          '\nc0_publish_tools_payload "$TOOLS_BUILD_ID" "$TEST_PAYLOAD"\n')
        result = subprocess.run(['/bin/bash', str(script)], cwd=root,
                                capture_output=True, text=True, timeout=10,
                                env=dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ['PATH'],
                                         C0ROOT=str(ROOT), C0_BASE_IMAGE='fixed-publisher-image',
                                         SHARED_TOOLS_VOLUME='synthetic-store', TOOLS_BUILD_ID='a' * 64,
                                         TEST_ARGS=str(root / 'args'), TEST_PAYLOAD=str(payload),
                                         TEST_STORE=str(store), PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual(selected.read_text(), 'retained selected payload\n')
        self.assertEqual(cache.read_text(), 'retained cache\n')
        return result, store / ('tmp/' + 'a' * 64 + '.partial'), manifest, root

    def test_fixed_publisher_retains_executable_metadata_nested_links_and_manifest(self):
        result, target, manifest, root = self.exercise()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((target / '.cargo/bin/tool').read_text(), 'synthetic executable\n')
        self.assertEqual((target / '.cargo/bin/tool').stat().st_mode & 0o777, 0o755)
        self.assertEqual(int((target / '.cargo/bin/tool').stat().st_mtime), 1234567890)
        self.assertTrue((target / '.cargo/bin/tool-link').is_symlink())
        self.assertEqual(os.readlink(target / '.cargo/bin/tool-link'), 'tool')
        self.assertEqual((target / '.rustup/toolchains/tool').read_text(), 'synthetic rustup\n')
        self.assertEqual((target / '.c0dev-toolchain.json').read_text(), manifest)
        self.assertTrue((target / '.c0dev-complete').is_file())
        self.assertFalse((target / 'private-auth').exists())
        args = json.loads((root / 'args').read_text())
        self.assertIn('fixed-publisher-image', args)
        self.assertIn('--read-only', args)

    def test_fixed_publisher_refuses_top_level_symlink_without_importing_neighbor(self):
        for redirected in ('.cargo', '.cargo/bin', '.rustup', '.local'):
            with self.subTest(redirected=redirected):
                result, target, manifest, root = self.exercise(redirected_root=redirected)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((target / '.c0dev-complete').exists())
                self.assertFalse((target / redirected / 'neighbor').exists())
                self.assertNotIn('SYNTHETIC OUTSIDE PRIVATE', result.stdout + result.stderr)
                self.assertEqual((root / 'outside-local/neighbor').read_text(),
                                 'SYNTHETIC OUTSIDE PRIVATE\n')


if __name__ == '__main__':
    unittest.main()
