# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Portable host terminal capture and nonroot synchronization for later attaches."""
import os
from pathlib import Path
import pty
import select
import shutil
import struct
import subprocess
import tempfile
import termios
import time
import unittest
import uuid
import fcntl

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / 'bin/c0-terminfo'


class Terminfo(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='c0-terminfo-')
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        TEST_ROOT=str(self.root))

    def tearDown(self):
        self.temp.cleanup()

    def executable(self, name, contents):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + contents)
        path.chmod(0o755)

    def test_headless_build_captures_only_baseline_and_caller(self):
        self.executable('infocmp', 'for terminal; do :; done\nprintf "%s|test terminal, cols#80,\\n" "$terminal"\n')
        self.env['TERM'] = 'dumb'
        directory = self.root / 'definitions'
        result = subprocess.run([str(HELPER), 'prepare', str(directory)], env=self.env,
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({path.name for path in directory.iterdir()}, {'xterm-256color', 'dumb'})
        self.assertTrue(all(path.stat().st_size for path in directory.iterdir()))

    def test_unknown_caller_does_not_leave_empty_source(self):
        self.executable('infocmp', '''for terminal; do :; done
test "$terminal" = xterm-256color || exit 1
printf 'xterm-256color|test terminal, cols#80,\\n'
''')
        self.env['TERM'] = 'unknown-test-terminal'
        directory = self.root / 'definitions'
        result = subprocess.run([str(HELPER), 'prepare', str(directory)], env=self.env,
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('unknown-test-terminal', result.stderr)
        self.assertEqual({path.name for path in directory.iterdir()}, {'xterm-256color'})

    def test_prepare_refreshes_previous_empty_baseline(self):
        self.executable('infocmp', 'printf "xterm-256color|test terminal, cols#80,\\n"\n')
        self.env['TERM'] = 'xterm-256color'
        directory = self.root / 'definitions'
        directory.mkdir()
        (directory / 'xterm-256color').touch()
        result = subprocess.run([str(HELPER), 'prepare', str(directory)], env=self.env,
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((directory / 'xterm-256color').stat().st_size)

    def test_missing_baseline_fails_and_invalid_term_cannot_write_paths(self):
        self.executable('infocmp', 'exit 1\n')
        self.env['TERM'] = '../../outside'
        directory = self.root / 'definitions'
        result = subprocess.run([str(HELPER), 'prepare', str(directory)], env=self.env,
                                text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('xterm-256color', result.stderr)
        self.assertEqual(list(directory.iterdir()), [])
        self.assertFalse((self.root / 'outside').exists())

    def test_noninteractive_sync_does_not_invoke_docker(self):
        self.executable('docker', 'touch "$TEST_ROOT/docker-called"\nexit 91\n')
        self.env['TERM'] = 'test-terminal'
        result = subprocess.run([str(HELPER), 'sync', 'test-container'], env=self.env,
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'docker-called').exists())

    def test_interactive_sync_compiles_actual_synthetic_definition_as_dev(self):
        if not shutil.which('tic') or not shutil.which('infocmp'):
            self.skipTest('host ncurses tools required')
        name = 'c0-synthetic-' + uuid.uuid4().hex[:12]
        source = subprocess.check_output(['infocmp', '-x', 'xterm-256color'], text=True)
        lines = source.splitlines()
        for index, line in enumerate(lines):
            if line and not line.startswith('#'):
                lines[index] = name + '|portable synthetic terminal,'
                break
        definition = self.root / 'source'
        definition.write_text('\n'.join(lines) + '\n')
        host_db = self.root / 'host-db'
        subprocess.run(['tic', '-x', '-o', str(host_db), str(definition)], check=True,
                       text=True, capture_output=True)
        self.env.update(TERM=name, TERMINFO=str(host_db))
        # The transport stand-in verifies the actual Docker exec privileges and
        # compiles transferred source with real tic in an isolated guest DB.
        self.executable('docker', '''printf '%s\\n' "$@" > "$TEST_ROOT/docker-args"
test "$1" = exec && test "$2" = -u && test "$3" = 1000 && test "$4" = -i || exit 90
test "$5" = test-container && test "$6" = tic && test "$7" = -x || exit 91
test "$8" = -o && test "$9" = /home/dev/.terminfo/ || exit 92
tic -x -o "$TEST_ROOT/guest-db" -
''')
        master, slave = pty.openpty()
        try:
            result = subprocess.run([str(HELPER), 'sync', 'test-container'], env=self.env,
                                    stdin=slave, stdout=slave, stderr=subprocess.PIPE,
                                    text=True, timeout=10)
        finally:
            os.close(slave)
            os.close(master)
        self.assertEqual(result.returncode, 0, result.stderr)
        copied = subprocess.run(['infocmp', '-A', str(self.root / 'guest-db'), name],
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(copied.returncode, 0, copied.stderr)
        self.assertIn('portable synthetic terminal', copied.stdout)


@unittest.skipUnless(os.environ.get('C0_TERMINFO_SMOKE_IMAGE'),
                     'opt-in: set C0_TERMINFO_SMOKE_IMAGE to a cached runtime image')
class TerminfoDockerSmoke(unittest.TestCase):
    def test_real_guest_pager_with_caller_definition_and_no_host_credentials(self):
        image = os.environ['C0_TERMINFO_SMOKE_IMAGE']
        name = 'c0-terminfo-smoke-' + uuid.uuid4().hex[:12]
        terminal = 'c0-term-' + uuid.uuid4().hex[:12]
        def docker(*args):
            return subprocess.run(['docker', *args], text=True, capture_output=True, timeout=30)
        def checked(result):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout.strip()
        checked(docker('image', 'inspect', image))
        cid = None
        try:
            cid = checked(docker('run', '-d', '--pull=never', '--network=none', '--name', name,
                                 '--user', '1000:1000', '--cap-drop', 'ALL',
                                 '--security-opt', 'no-new-privileges:true',
                                 '--entrypoint', '/bin/sleep', image, '300'))
            missing = docker('exec', '-u', '1000', cid, 'infocmp', terminal)
            self.assertNotEqual(missing.returncode, 0)
            with tempfile.TemporaryDirectory(prefix='c0-terminfo-real-') as temporary:
                root = Path(temporary)
                lines = subprocess.check_output(['infocmp', '-x', 'xterm-256color'],
                                                text=True).splitlines()
                for index, line in enumerate(lines):
                    if line and not line.startswith('#'):
                        lines[index] = terminal + '|portable terminal smoke test,'
                        break
                source = root / 'source'
                source.write_text('\n'.join(lines) + '\n')
                subprocess.run(['tic', '-x', '-o', str(root / 'db'), str(source)],
                               check=True, text=True, capture_output=True)
                env = dict(os.environ, TERM=terminal, TERMINFO=str(root / 'db'))
                master, slave = pty.openpty()
                try:
                    sync = subprocess.run([str(HELPER), 'sync', cid], env=env, stdin=slave,
                                          stdout=slave, stderr=subprocess.PIPE,
                                          text=True, timeout=15)
                finally:
                    os.close(slave)
                    os.close(master)
                self.assertEqual(sync.returncode, 0, sync.stderr)
            definition = checked(docker('exec', '-u', '1000', cid, 'infocmp', terminal))
            self.assertIn('/home/dev/.terminfo/', definition)
            script = r'''
set -eu
repo=$(mktemp -d /tmp/c0-pager.XXXXXX)
trap 'rm -rf "$repo"' EXIT
git init --template= -q "$repo"
git -C "$repo" -c user.name=C0TerminalTest -c user.email=terminal@example.invalid \
    -c commit.gpgsign=false -c core.hooksPath=/dev/null commit --allow-empty -qm pager-test
GIT_PAGER='less -FX' git -C "$repo" --paginate log --oneline -1
echo C0_TERMINFO_PAGER_OK
'''
            master, slave = pty.openpty()
            process = None
            captured = bytearray()
            try:
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
                process = subprocess.Popen(['docker', 'exec', '-it', '-u', '1000',
                                            '-e', 'TERM=' + terminal, cid,
                                            '/bin/bash', '--noprofile', '--norc', '-c', script],
                                           stdin=slave, stdout=slave, stderr=subprocess.PIPE)
                os.close(slave)
                slave = None
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            block = os.read(master, 65536)
                        except OSError:
                            break
                        if not block:
                            break
                        captured.extend(block)
                status = process.wait(timeout=2)
                error = process.stderr.read().decode()
                output = captured.decode(errors='replace')
                self.assertEqual(status, 0, output + error)
                self.assertIn('C0_TERMINFO_PAGER_OK', output)
                self.assertNotIn('terminal is not fully functional', output + error)
                self.assertNotIn('Press RETURN', output + error)
            finally:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                if process is not None and process.stderr is not None:
                    process.stderr.close()
                if slave is not None:
                    os.close(slave)
                os.close(master)
        finally:
            docker('rm', '-f', cid or name)
