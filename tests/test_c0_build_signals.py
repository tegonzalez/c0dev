# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Exercise c0's real Bash supervisor without a Docker daemon or image pulls."""
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import shutil
import subprocess
import tempfile
import time
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'bin/c0').read_text()
FUNCTIONS = '\n'.join(
    re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE, re.M | re.S).group()
    for name in ('c0_build_wait_group', 'c0_build_cancel_group', 'cmd_build')
)
MOCK = '''
import json, os, signal, subprocess, sys, time
path, mode = sys.argv[1:3]
def event(kind, **values):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.write(fd, (json.dumps(dict(kind=kind, pid=os.getpid(), **values))+'\\n').encode())
    os.close(fd)
def handle(sig, frame):
    event('signal', signal=sig)
    if '--child' in sys.argv:
        if mode != 'stubborn': sys.exit(0)
    elif mode == 'stubborn': sys.exit(0)
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, handle)
if '--child' in sys.argv:
    event('child-ready')
    while True: time.sleep(.05)
else:
    child = subprocess.Popen([sys.executable, __file__, path, mode, '--child'])
    event('client-ready')
    child.wait()
'''


class BuildSignals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='c0-signals-')
        self.root = Path(self.tmp.name)
        self.events = self.root / 'events'
        self.mock = self.root / 'mock.py'
        self.mock.write_text(MOCK)
        self.children = []

    def tearDown(self):
        for proc in self.children:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGCONT)
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            for stream in (proc.stdout, proc.stderr):
                if stream: stream.close()
        # Clean up any test descendants even when an assertion fails.
        for event in self.read_events():
            if event['kind'] in ('client-ready', 'child-ready'):
                try: os.kill(event['pid'], signal.SIGKILL)
                except ProcessLookupError: pass
        self.tmp.cleanup()

    def read_events(self):
        return [json.loads(line) for line in self.events.read_text().splitlines()] if self.events.exists() else []

    def harness(self, mode='normal', steps=None):
        script = self.root / 'harness.sh'
        script.write_text('set -e\n' + FUNCTIONS + '''
require_host() { :; }
c0_build_cleanup() { echo cleanup >> "$TEST_CLEANUP"; }
c0_build_steps() { printf '%s' "$C0_BUILD_CONTEXT" > "$TEST_CONTEXT_PATH"; ''' + (steps or '"$TEST_PYTHON" "$TEST_MOCK" "$TEST_EVENTS" "$TEST_MODE"') + '''; }
cmd_build "$@"
''')
        env = dict(os.environ, TEST_PYTHON=os.sys.executable, TEST_MOCK=str(self.mock),
                   TEST_EVENTS=str(self.events), TEST_MODE=mode,
                   TEST_CLEANUP=str(self.root / 'cleanup'),
                   TEST_CONTEXT_PATH=str(self.root / 'context-path'))
        return script, env

    def start(self, mode='normal', steps=None):
        script, env = self.harness(mode, steps)
        proc = subprocess.Popen(['/bin/bash', str(script)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
        self.children.append(proc)
        return proc

    def ready(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            events = self.read_events()
            if sum(e['kind'].endswith('-ready') for e in events) == 2:
                return events
            time.sleep(.02)
        self.fail('mock Docker/buildx tree did not become ready')

    def finish(self, proc, expected):
        out, err = proc.communicate(timeout=16)
        self.assertEqual(proc.returncode, expected, (out, err))
        self.assertEqual((self.root / 'cleanup').read_text(), 'cleanup\n')
        self.assertIn(b'build interrupted', err)
        self.assertFalse(Path((self.root/'context-path').read_text()).parent.exists())
        for event in self.read_events():
            if event['kind'].endswith('-ready'):
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    try: os.kill(event['pid'], 0)
                    except ProcessLookupError: break
                    time.sleep(.02)
                else: self.fail(f"descendant {event['pid']} survived cleanup")

    def test_parent_only_signals_cancel_whole_tree(self):
        for sig, status in ((signal.SIGINT, 130), (signal.SIGTERM, 143), (signal.SIGHUP, 129)):
            with self.subTest(signal=sig):
                self.events.unlink(missing_ok=True)
                (self.root / 'cleanup').unlink(missing_ok=True)
                proc = self.start()
                self.ready()
                os.kill(proc.pid, sig)
                self.finish(proc, status)

    def test_stopped_descendants_are_resumed_and_cancelled(self):
        proc = self.start()
        events = self.ready()
        for event in events: os.kill(event['pid'], signal.SIGSTOP)
        os.kill(proc.pid, signal.SIGINT)
        self.finish(proc, 130)

    def test_stubborn_grandchild_is_killed_without_harming_other_jobs(self):
        unrelated = subprocess.Popen(['/bin/sleep', '30'], start_new_session=True)
        self.children.append(unrelated)
        proc = self.start('stubborn')
        self.ready()
        os.kill(proc.pid, signal.SIGINT)
        self.finish(proc, 130)
        self.assertIsNone(unrelated.poll())

    def test_exit_status_and_no_cleanup_on_normal_exit(self):
        for status in (0, 42):
            proc = self.start(steps=f'return {status}')
            proc.communicate(timeout=3)
            self.assertEqual(proc.returncode, status)
            self.assertFalse((self.root / 'cleanup').exists())
            self.assertFalse(Path((self.root/'context-path').read_text()).parent.exists())

    def test_terminal_stop_bg_fg_ctrl_c(self):
        docker = shutil.which('docker')
        if docker:
            # Exercise the installed Docker CLI's real terminal/plugin handling.
            # Override buildx so this cannot contact a daemon or start a build.
            plugins = self.root / 'cli-plugins'
            plugins.mkdir()
            plugin = plugins / 'docker-buildx'
            plugin.write_text('#!' + os.sys.executable + '\n' +
                'import json, os, sys\n' +
                "if 'docker-cli-plugin-metadata' in sys.argv:\n" +
                "    print(json.dumps(dict(SchemaVersion='0.1.0', Vendor='c0 test', Version='0.0.0', ShortDescription='signal test')))\n" +
                'else:\n' +
                f'    os.execv({os.sys.executable!r}, [{os.sys.executable!r}, {str(self.mock)!r}, {str(self.events)!r}, "normal"])\n')
            plugin.chmod(0o755)
            script, env = self.harness(steps='"$TEST_DOCKER" build .')
            env.update(DOCKER_CONFIG=str(self.root), TEST_DOCKER=docker,
                       DOCKER_BUILDKIT='1')
        else:
            script, env = self.harness()
        pid, fd = pty.fork()
        if pid == 0:
            os.environ.update(env, PS1='TEST_PROMPT> ', BASH_SILENCE_DEPRECATION_WARNING='1')
            os.execv('/bin/bash', ['/bin/bash', '--noprofile', '--norc', '-i'])
        output = b''
        supervisor = None
        def drain(seconds):
            nonlocal output
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                if not select.select([fd], [], [], max(0, end-time.monotonic()))[0]: break
                try: data = os.read(fd, 65536)
                except OSError: break
                if not data: break
                output += data
        try:
            drain(.2)
            os.write(fd, f'/bin/bash {script}\n'.encode())
            self.ready()
            supervisor = os.tcgetpgrp(fd)
            self.assertNotEqual(supervisor, pid)
            os.killpg(supervisor, signal.SIGSTOP)
            drain(.2)
            os.write(fd, b'bg\n'); drain(.2)
            os.write(fd, b'fg\n'); drain(.2)
            os.write(fd, b'\x03'); drain(3)
            self.assertEqual(os.tcgetpgrp(fd), pid, output)
            self.assertIn(b'build interrupted', output)
            self.assertEqual((self.root / 'cleanup').read_text(), 'cleanup\n')
        finally:
            os.write(fd, b'exit\n')
            drain(.2)
            done, _ = os.waitpid(pid, os.WNOHANG)
            if not done:
                if supervisor is not None:
                    try: os.killpg(supervisor, signal.SIGKILL)
                    except ProcessLookupError: pass
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            os.close(fd)


if __name__ == '__main__':
    unittest.main()
