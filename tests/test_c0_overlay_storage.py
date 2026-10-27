# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Home storage is derived from Docker objects, without a saved selector."""
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import uuid
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'bin/c0').read_text()


def function(name):
    return re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE, re.M | re.S).group()


class OverlayStorage(unittest.TestCase):
    def discover(self, volumes):
        with tempfile.TemporaryDirectory(prefix='c0-docker-storage-') as directory:
            root = Path(directory)
            binary = root / 'docker'
            binary.write_text('#!' + sys.executable + '\n' + r'''
import json, os, sys
args = sys.argv[1:]
volumes = json.loads(os.environ['TEST_VOLUMES'])
if args[:2] == ['volume', 'ls']:
    print('\n'.join(volumes))
elif args[:2] == ['volume', 'inspect']:
    labels = volumes[args[-1]]
    expression = args[3]
    for key in ('c0dev.instance', 'c0dev.overlay_generation', 'c0dev.overlay_source'):
        if key in expression:
            print(labels.get(key, '<no value>'))
            break
    else: sys.exit(2)
else: sys.exit('unexpected mutation: '+repr(args))
''')
            binary.chmod(0o755)
            script = '\n'.join(function(name) for name in
                               ('c0_validate_overlay_volume', 'c0_discover_home_storage'))
            script += '\nC0_WORKSPACE_ID=workspace\nC0_INSTANCE_ID=build-workspace\nc0_discover_home_storage\n'
            result = subprocess.run(['/bin/bash', '-c', script], capture_output=True,
                                    text=True, timeout=5,
                                    env=dict(os.environ, PATH=directory + os.pathsep + os.environ['PATH'],
                                             TEST_VOLUMES=json.dumps(volumes)), cwd=root)
            self.assertEqual(sorted(path.name for path in root.iterdir()), ['docker'])
            return result

    def test_first_creation_uses_deterministic_workspace_name(self):
        result = self.discover({})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'workspace-home-overlays\tfalse\n')

    def test_existing_canonical_volume_is_external(self):
        result = self.discover({'workspace-home-overlays': {}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'workspace-home-overlays\ttrue\n')

    def test_existing_lineage_selects_unique_leaf_without_recency(self):
        first = 'workspace-home-overlays-' + 'a' * 32
        second = 'workspace-home-overlays-' + 'b' * 32
        volumes = {'workspace-home-overlays': {},
                   first: {'c0dev.instance': 'workspace', 'c0dev.overlay_generation': 'a' * 32,
                           'c0dev.overlay_source': 'workspace-home-overlays'},
                   second: {'c0dev.instance': 'workspace', 'c0dev.overlay_generation': 'b' * 32,
                            'c0dev.overlay_source': first}}
        result = self.discover(volumes)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, second + '\ttrue\n')

    def test_ambiguous_branches_preserve_every_volume(self):
        volumes = {'workspace-home-overlays': {}}
        for suffix in ('a' * 32, 'b' * 32):
            volumes['workspace-home-overlays-' + suffix] = {
                'c0dev.instance': 'workspace', 'c0dev.overlay_generation': suffix,
                'c0dev.overlay_source': 'workspace-home-overlays'}
        result = self.discover(volumes)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ambiguous home storage', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_foreign_volume_is_not_adopted(self):
        result = self.discover({'workspace-home-overlays-' + 'a' * 32: {
            'c0dev.instance': 'another-workspace', 'c0dev.overlay_generation': 'a' * 32}})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('another checkout', result.stderr)


@unittest.skipUnless(os.environ.get('C0_BUILD_DOCKER_TESTS') == '1', 'opt-in owned Docker volumes')
class DockerStorage(unittest.TestCase):
    def test_legacy_volume_data_is_derived_after_container_removal(self):
        docker = shutil.which('docker')
        self.assertTrue(docker)
        def call(*args, **kwargs):
            return subprocess.run([docker, *args], capture_output=True, text=True, timeout=30, **kwargs)
        if call('image', 'inspect', 'alpine:latest').returncode:
            self.skipTest('cached alpine required; refusing to pull')
        token = uuid.uuid4().hex
        workspace = 'c0-storage-proof-' + token
        canonical = workspace + '-home-overlays'
        generation = uuid.uuid4().hex
        leaf = canonical + '-' + generation
        volumes = [canonical, leaf]
        containers = []
        def check(result):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout.strip()
        try:
            check(call('volume', 'create', '--label', 'c0dev.storage_test=' + token, canonical))
            check(call('volume', 'create', '--label', 'c0dev.storage_test=' + token,
                       '--label', 'c0dev.instance=' + workspace,
                       '--label', 'c0dev.overlay_generation=' + generation,
                       '--label', 'c0dev.overlay_source=' + canonical, leaf))
            for volume, marker in ((canonical, 'backup'), (leaf, 'guest-stage-and-launcher')):
                check(call('run', '--rm', '--pull=never', '--network', 'none',
                           '-v', volume + ':/state', 'alpine:latest', 'sh', '-ec',
                           'printf "%s" "$1" >/state/data', 'write-data', marker))
            backup = check(call('create', '--pull=never', '--network', 'none',
                                '--label', 'c0dev.storage_test=' + token,
                                '-v', canonical + ':/state', 'alpine:latest', 'true'))
            containers.append(backup)
            backup_before = check(call('inspect', backup))
            old = check(call('create', '--pull=never', '--network', 'none',
                             '--label', 'c0dev.storage_test=' + token,
                             '-v', leaf + ':/state', 'alpine:latest', 'true'))
            containers.append(old)
            script = '\n'.join(function(name) for name in
                               ('c0_validate_overlay_volume', 'c0_discover_home_storage'))
            script += '\nC0_WORKSPACE_ID="$TEST_WORKSPACE"\nC0_INSTANCE_ID=build-workspace\nc0_discover_home_storage\n'
            env = dict(os.environ, TEST_WORKSPACE=workspace)
            with tempfile.TemporaryDirectory(prefix='c0-derived-storage-proof-') as temporary:
                for remove in (False, True):
                    if remove:
                        check(call('rm', old))
                        containers.remove(old)
                    selected = subprocess.run(['/bin/bash', '-c', script], env=env, cwd=temporary,
                                              capture_output=True, text=True, timeout=30)
                    self.assertEqual(selected.returncode, 0, selected.stderr)
                    self.assertEqual(selected.stdout, leaf + '\ttrue\n')
                    self.assertEqual(list(Path(temporary).iterdir()), [])
                data = check(call('run', '--rm', '--pull=never', '--network', 'none',
                                  '-v', leaf + ':/state:ro', 'alpine:latest', 'cat', '/state/data'))
                self.assertEqual(data, 'guest-stage-and-launcher')
                self.assertEqual(check(call('inspect', backup)), backup_before)
                self.assertEqual(check(call('run', '--rm', '--pull=never', '--network', 'none',
                     '-v', canonical + ':/state:ro', 'alpine:latest', 'cat', '/state/data')), 'backup')
        finally:
            for cid in containers:
                ownership = call('inspect', '--format', '{{index .Config.Labels "c0dev.storage_test"}}', cid)
                if ownership.returncode == 0 and ownership.stdout.strip() == token:
                    call('rm', '-f', cid)
            for volume in volumes:
                ownership = call('volume', 'inspect', '--format', '{{index .Labels "c0dev.storage_test"}}', volume)
                if ownership.returncode == 0 and ownership.stdout.strip() == token:
                    call('volume', 'rm', volume)


if __name__ == '__main__':
    unittest.main()
