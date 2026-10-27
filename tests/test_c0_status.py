# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Status must work with no images and use only Docker metadata queries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

C0 = Path(__file__).resolve().parents[1] / 'bin/c0'
SNAPSHOT = 'a' * 64
DOCKER = '''
import json, os, sys
args = sys.argv[1:]
with open(os.environ['TEST_DOCKER_LOG'], 'a') as log:
    log.write(json.dumps(args)+'\\n')
state = os.environ['TEST_CONTAINER_STATE']
if args[0] == 'version':
    print('test-server')
elif args[:2] == ['volume', 'inspect']:
    sys.exit(0 if os.environ['TEST_VOLUME_EXISTS'] == '1' else 1)
elif args[0] == 'ps':
    if '--format' in args:
        if state: print('test-runtime (test-instance, '+state+'; tools='+'a'*64+')')
    elif state and ('-aq' in args or state == 'running'):
        print('test-container-id')
elif args[0] == 'inspect':
    fmt = args[args.index('-f')+1] if '-f' in args else args[args.index('--format')+1]
    if 'c0dev.tools_hash' in fmt: print('a'*64)
    elif 'c0dev.security_mode' in fmt: print('guest-admin')
    elif '.State.Status' in fmt: print(state)
    elif '.Name' in fmt: print('/test-runtime')
    elif '3000/tcp' in fmt: print('3001')
    elif '2222/tcp' in fmt: print('2223')
    elif '.NetworkSettings.Networks' in fmt: print('192.0.2.10')
    else: sys.exit(98)
else:
    # No image exists in this fake daemon. Running any helper, even with
    # --pull=never, is a contract violation, as are exec/compose mutations.
    print('FORBIDDEN Docker operation: '+repr(args), file=sys.stderr)
    sys.exit(99)
'''


class Status(unittest.TestCase):
    def check_status(self, state='', volume=True, command='status'):
        with tempfile.TemporaryDirectory(prefix='c0-status-') as temp:
            root = Path(temp)
            docker = root / 'docker'
            docker.write_text('#!' + sys.executable + '\n' + DOCKER)
            docker.chmod(0o755)
            log = root / 'docker.log'
            env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ['PATH'],
                       TEST_DOCKER_LOG=str(log), TEST_CONTAINER_STATE=state,
                       TEST_VOLUME_EXISTS='1' if volume else '0',
                       C0_MODE='', C0_SECURITY='guest-admin', C0_SSH_AGENT='0')
            args = ['/bin/bash', str(C0)] + ([command] if command else [])
            result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertTrue(calls)
            for call in calls:
                self.assertTrue(call[0] in ('version', 'ps', 'inspect') or
                                call[:2] == ['volume', 'inspect'], call)
            self.assertIn('snapshot completeness:', result.stdout)
            self.assertIn('(not checked)', result.stdout)
            self.assertNotIn('volume: complete', result.stdout)
            self.assertNotIn('FORBIDDEN', result.stderr)
            return result.stdout

    def test_volume_present_without_container_or_images(self):
        output = self.check_status()
        self.assertIn('present', output)
        self.assertIn('selected snapshot unknown', output)
        self.assertIn('container tools id:', output)
        self.assertIn('(unknown)', output)

    def test_missing_volume_without_container_or_images(self):
        output = self.check_status(volume=False)
        self.assertIn('missing', output)
        self.assertIn('(none)', output)

    def test_running_container_uses_its_snapshot_and_ports(self):
        output = self.check_status(state='running')
        self.assertIn(SNAPSHOT, output)
        self.assertIn('host:3001', output)
        self.assertIn('127.0.0.1:2223', output)
        self.assertIn('test-runtime: running', output)
        self.assertNotIn('selected snapshot unknown', output)

    def test_stopped_container_needs_no_execution(self):
        output = self.check_status(state='exited')
        self.assertIn('test-runtime: exited', output)
        self.assertIn(SNAPSHOT, output)

    def test_default_command_is_also_observational(self):
        self.check_status(command='')


if __name__ == '__main__':
    unittest.main()
