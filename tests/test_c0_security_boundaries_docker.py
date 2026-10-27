# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Opt-in kernel smoke using only newly owned, labeled Docker resources.

C0_SECURITY_BOUNDARY_DOCKER_TESTS=1 python3 -B -m unittest discover -s tests \\
    -p test_c0_security_boundaries_docker.py -v

Requires the exact cached Alpine image below. Never pulls, builds, enumerates
existing resources, or mounts shared tools, auth, or a production workspace.
"""
import os
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from test_c0_security_boundaries import ROOT, definitions


CACHED_IMAGE = 'sha256:be2656061b536c1883c4034790e21d0a09c5aaaf51968b89368a3c0371ea2c9a'
LABEL = 'c0dev.security_boundary_test'


@unittest.skipUnless(os.environ.get('C0_SECURITY_BOUNDARY_DOCKER_TESTS') == '1',
                     'opt-in isolated kernel overlay smoke')
class SecurityBoundariesDocker(unittest.TestCase):
    def test_stopped_extraction_and_fixed_publisher_preserve_links_and_neighbor_ownership(self):
        docker = shutil.which('docker')
        self.assertTrue(docker)

        def call(*args, **kwargs):
            return subprocess.run([docker, *args], capture_output=True, text=True,
                                  timeout=30, **kwargs)

        if call('image', 'inspect', CACHED_IMAGE).returncode:
            self.skipTest('exact cached Alpine image unavailable; refusing to pull')
        token = uuid.uuid4().hex
        containers = []
        volume = None
        image = None
        identity = 'a' * 64
        selected = 'opt/' + 'b' * 64 + '/selected'
        manifest = '{"fixture":"native-extraction"}'

        def check(result):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout.strip()

        def created(*args):
            cid = check(call('create', '--pull=never', '--network', 'none',
                             '--label', LABEL + '=' + token, *args))
            self.assertRegex(cid, r'^[0-9a-f]{64}$')
            containers.append(cid)
            return cid

        def short_job(*args):
            cid = created('--read-only', '--cap-drop', 'ALL', *args)
            return check(call('start', '-a', cid))

        with tempfile.TemporaryDirectory(prefix='c0-native-extraction-') as temporary:
            root = Path(temporary)
            payload = root / 'dev'
            context = root / 'context'
            context.mkdir()
            for name in ('.cargo/bin', '.rustup/toolchains', '.local/share/c0'):
                (payload / name).mkdir(parents=True)
            executable = payload / '.cargo/bin/tool'
            executable.write_text('synthetic tool data\n')
            executable.chmod(0o755)
            os.utime(executable, (1234567890, 1234567890))
            (payload / '.cargo/bin/tool-link').symlink_to('tool')
            (payload / '.local/store-link').symlink_to('/tools/' + selected)
            (payload / '.rustup/toolchains/proof').write_text('synthetic rustup data\n')
            (payload / '.local/share/c0/toolchain.json').write_text(manifest + '\n')
            (payload / 'excluded-input').write_text('synthetic excluded input\n')
            (payload / 'startup-hook').write_text(
                '#!/bin/sh\n'
                'echo hook-ran >/tools/hook-marker\n'
                'echo overwritten >/tools/' + selected + '\nexit 99\n')
            (payload / 'startup-hook').chmod(0o755)
            journal = root / 'docker.jsonl'
            try:
                name = 'c0-security-extract-' + token
                volume = check(call('volume', 'create', '--label', LABEL + '=' + token, name))
                self.assertEqual(volume, name)
                short_job(
                    '--cap-add', 'CHOWN',
                    '--mount', 'type=volume,src=' + volume + ',dst=/tools',
                    '--entrypoint', '/bin/sh', CACHED_IMAGE, '-eu', '-c',
                    'mkdir -p /tools/tmp/' + identity + '.partial /tools/opt/' + 'b' * 64 + '; '
                    'chmod 1777 /tools/tmp; chmod 0777 /tools/tmp/' + identity + '.partial; '
                    'printf "%s\\n" "selected neighbor kept" >/tools/' + selected + '; '
                    'chmod 0644 /tools/' + selected + '; '
                    'chown 2001:2001 /tools/' + selected)

                # Commit only newly owned, stopped fixture data. No image code,
                # Dockerfile build, network, or user image tag is involved.
                template = created('--entrypoint', '/bin/false', CACHED_IMAGE)
                check(call('cp', str(payload), template + ':/home/'))
                image = check(call(
                    'commit', '--change', 'LABEL ' + LABEL + '=' + token,
                    '--change', 'ENTRYPOINT ["/bin/sh","/home/dev/startup-hook"]',
                    '--change', 'CMD []', template))
                self.assertRegex(image, r'^sha256:[0-9a-f]{64}$')

                # Keep production command arguments observable. Every created
                # helper gets a task label/cidfile for exact cleanup, and a
                # missing network restriction fails closed before execution.
                peer = root / 'extraction-docker.py'
                peer.write_text(r'''
import json, os, sys, uuid
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['TEST_JOURNAL'], 'a') as output:
    output.write(json.dumps(args) + '\n')
if args[:1] in (['create'], ['run']):
    if not any(value in args for value in (os.environ['TEST_FIXTURE_IMAGE'], os.environ['TEST_CACHED_IMAGE'])):
        sys.exit('unexpected extraction image')
    network_none = '--network=none' in args or any(args[i:i+2] == ['--network', 'none'] for i in range(len(args)-1))
    if not network_none: sys.exit('extraction helper requires no network')
    cidfile = str(Path(os.environ['TEST_PRIVATE_ROOT']) / ('owned-' + uuid.uuid4().hex + '.cid'))
    args[1:1] = ['--pull=never', '--label', os.environ['TEST_TASK_LABEL'], '--cidfile', cidfile]
elif args[:1] not in (['inspect'], ['cp'], ['rm']):
    sys.exit('unexpected extraction operation')
os.execv(os.environ['TEST_DOCKER'], [os.environ['TEST_DOCKER'], *args])
''')
                script = root / 'extract.sh'
                script.write_text('set -e\n' + definitions() + r'''
docker() { "$TEST_PYTHON" -B "$TEST_PEER" "$@"; }
c0_extract_built_tools "$TEST_FIXTURE_IMAGE" "$TEST_TOOLS_ID"
''')
                result = subprocess.run(
                    ['/bin/bash', str(script)], capture_output=True, text=True, timeout=30,
                    env=dict(os.environ, TEST_PYTHON=sys.executable, TEST_PEER=str(peer),
                             TEST_DOCKER=docker, TEST_CACHED_IMAGE=CACHED_IMAGE,
                             TEST_FIXTURE_IMAGE=image, TEST_JOURNAL=str(journal),
                             TEST_PRIVATE_ROOT=str(root), TEST_TASK_LABEL=LABEL + '=' + token,
                             TEST_TOOLS_ID=identity, C0ROOT=str(ROOT),
                             C0_BUILD_CONTEXT=str(context), C0_BASE_IMAGE=CACHED_IMAGE,
                             SHARED_TOOLS_VOLUME=volume))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = [json.loads(line) for line in journal.read_text().splitlines()]
                sources = [args for args in calls if args[0] == 'create']
                self.assertEqual(len(sources), 1)
                self.assertIn(image, sources[0])
                self.assertFalse(any(volume in arg for arg in sources[0]))
                self.assertFalse(any(args[0] in ('run', 'start', 'exec') and image in args
                                     for args in calls))
                publishers = [args for args in calls if args[0] == 'run']
                self.assertEqual(len(publishers), 1)
                self.assertIn(CACHED_IMAGE, publishers[0])
                self.assertIn('--read-only', publishers[0])
                source_cids = [args[-1] for args in calls if args[0] == 'rm']
                self.assertEqual(len(source_cids), 1)
                self.assertRegex(source_cids[0], r'^[0-9a-f]{64}$')
                self.assertNotEqual(call('inspect', source_cids[0]).returncode, 0,
                                    'owned stopped extraction source must retire')
                self.assertEqual(list(context.iterdir()), [], 'private extraction copy must retire')

                observed = short_job(
                    '--user', '1000:1000',
                    '--mount', 'type=volume,src=' + volume + ',dst=/tools,readonly',
                    '--entrypoint', '/bin/sh', CACHED_IMAGE, '-eu', '-c',
                    'p=/tools/tmp/' + identity + '.partial; '
                    'cat "$p/.cargo/bin/tool"; '
                    'stat -c "%a:%Y:%u:%g" "$p/.cargo/bin/tool"; '
                    'test -L "$p/.cargo/bin/tool-link"; readlink "$p/.cargo/bin/tool-link"; '
                    'test -L "$p/.local/store-link"; readlink "$p/.local/store-link"; '
                    'cat "$p/.c0dev-toolchain.json"; '
                    'stat -c "%u:%g" "$p/.c0dev-toolchain.json" "$p/.c0dev-complete"; '
                    'cat "$p/.rustup/toolchains/proof" /tools/' + selected + '; '
                    'stat -c "%u:%g" /tools/' + selected + '; '
                    'test ! -e /tools/hook-marker; test ! -e "$p/excluded-input"; '
                    'test ! -e "$p/startup-hook"')
                self.assertEqual(observed.splitlines(), [
                    'synthetic tool data', '755:1234567890:1000:1000', 'tool',
                    '/tools/' + selected, manifest, '1000:1000', '1000:1000',
                    'synthetic rustup data', 'selected neighbor kept', '2001:2001'])
            finally:
                errors = []
                for cidfile in root.glob('owned-*.cid'):
                    cid = cidfile.read_text().strip()
                    if re.fullmatch(r'[0-9a-f]{64}', cid):
                        containers.append(cid)
                for cid in reversed(list(dict.fromkeys(containers))):
                    owner = call('inspect', '--format',
                                 '{{index .Config.Labels "' + LABEL + '"}}', cid)
                    if owner.returncode:
                        continue
                    if owner.stdout.strip() != token:
                        errors.append('retained uncertain extraction container: ' + cid)
                        continue
                    removed = call('rm', '-f', cid)
                    if removed.returncode:
                        errors.append(removed.stderr)
                if image:
                    owner = call('image', 'inspect', '--format',
                                 '{{index .Config.Labels "' + LABEL + '"}}', image)
                    if owner.returncode or owner.stdout.strip() != token:
                        errors.append('retained uncertain fixture image: ' + image)
                    else:
                        removed = call('image', 'rm', image)
                        if removed.returncode:
                            errors.append(removed.stderr)
                if volume:
                    owner = call('volume', 'inspect', '--format',
                                 '{{index .Labels "' + LABEL + '"}}', volume)
                    if owner.returncode or owner.stdout.strip() != token:
                        errors.append('retained uncertain extraction volume: ' + volume)
                    else:
                        removed = call('volume', 'rm', volume)
                        if removed.returncode:
                            errors.append(removed.stderr)
                self.assertEqual(errors, [], '\n'.join(errors))

    def test_helper_mounts_with_trusted_program_root_and_persistent_separate_uppers(self):
        docker = shutil.which('docker')
        self.assertTrue(docker, 'Docker CLI required for this opt-in test')

        def call(*args, **kwargs):
            return subprocess.run([docker, *args], capture_output=True, text=True,
                                  timeout=30, **kwargs)

        cached = call('image', 'inspect', CACHED_IMAGE)
        if cached.returncode:
            self.skipTest('exact cached Alpine image unavailable; refusing to pull')

        token = uuid.uuid4().hex
        containers = []
        volumes = []
        helper_cidfiles = []
        identity = 'a' * 64

        def check(result):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout.strip()

        def created(*args):
            cid = check(call('create', '--pull=never', '--network', 'none',
                             '--label', LABEL + '=' + token, *args))
            self.assertRegex(cid, r'^[0-9a-f]{64}$')
            containers.append(cid)
            return cid

        def short_job(*args):
            cid = created('--read-only', '--cap-drop', 'ALL', *args)
            return check(call('start', '-a', cid))

        with tempfile.TemporaryDirectory(prefix='c0-kernel-boundary-') as temporary:
            root = Path(temporary)
            guest_bin = root / 'guest-bin'
            guest_bin.mkdir()
            launchers = root / 'launchers'
            launchers.mkdir()
            (launchers / 'fixture-launcher').write_text('synthetic launcher lower\n')
            (launchers / 'fixture-launcher').chmod(0o755)
            tools = 'c0-security-tools-' + token
            overlays = 'c0-security-overlays-' + token
            try:
                for volume in (tools, overlays):
                    name = check(call('volume', 'create', '--label', LABEL + '=' + token, volume))
                    self.assertEqual(name, volume)
                    volumes.append(name)

                # A private /bin avoids Docker resolving Alpine's /bin/sh symlink
                # onto /bin/busybox when mounting the synthetic hostile shell.
                source = created('--entrypoint', '/bin/false', CACHED_IMAGE)
                check(call('cp', source + ':/bin/busybox', str(guest_bin / 'busybox')))
                (guest_bin / 'busybox').chmod(0o755)
                (guest_bin / 'sh').write_text(
                    '#!/bin/busybox sh\n'
                    'echo guest-shell-executed >/tmp/guest-shell-executed\n'
                    'exit 99\n')
                (guest_bin / 'sh').chmod(0o755)

                short_job('--mount', 'type=volume,src=' + tools + ',dst=/tools',
                          '--entrypoint', '/bin/busybox', CACHED_IMAGE, 'sh', '-ec',
                          'mkdir -p /tools/.local; '
                          'printf "%s\\n" "synthetic tools lower" >/tools/.local/packaged')

                target = created(
                    '--read-only', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges:true',
                    '--tmpfs', '/home/dev:rw,mode=0755', '--tmpfs', '/tmp:rw,mode=1777',
                    '--mount', 'type=bind,src=' + str(guest_bin) + ',dst=/bin,readonly',
                    '--mount', 'type=bind,src=' + str(launchers) + ',dst=/run/c0/host-bin,readonly',
                    '--mount', 'type=volume,src=' + tools + ',dst=/tools/current,readonly',
                    '--mount', 'type=volume,src=' + overlays + ',dst=/run/c0/overlay-state',
                    '--entrypoint', '/bin/busybox', CACHED_IMAGE, 'sh', '-ec',
                    '/bin/busybox mkdir -p /home/dev/bin /home/dev/.local; '
                    '/bin/busybox touch /tmp/fixture-ready; '
                    'exec /bin/busybox sleep 120')
                check(call('start', target))
                ready = False
                for _ in range(30):
                    probe = call('exec', target, '/bin/busybox', 'test', '-f', '/tmp/fixture-ready')
                    if probe.returncode == 0:
                        ready = True
                        break
                    time.sleep(0.1)
                self.assertTrue(ready, 'new isolated target did not initialize')

                # The actual production helper retains its implementation. Only
                # its literal cached image reference gains a no-pull task label
                # and cidfile so interrupted helper lifetimes remain attributable.
                peer = root / 'helper-docker.py'
                peer.write_text(r'''
import os, sys
args = sys.argv[1:]
if args[:1] != ['run'] or args.count('alpine') != 1:
    sys.exit('unexpected helper Docker operation')
args[args.index('alpine')] = os.environ['TEST_CACHED_IMAGE']
args[1:1] = ['--pull=never', '--label', os.environ['TEST_TASK_LABEL'],
             '--cidfile', os.environ['TEST_HELPER_CIDFILE']]
os.execv(os.environ['TEST_DOCKER'], [os.environ['TEST_DOCKER'], *args])
''')
                script = root / 'mount.sh'
                script.write_text('set -e\n' + definitions() + r'''
docker() { "$TEST_PYTHON" -B "$TEST_HELPER_PEER" "$@"; }
c0_mount_home_overlay "$TEST_TARGET" "$TEST_GUEST_REL" "$TEST_TOOLS_REL"
''')
                for index, (guest_rel, tools_rel) in enumerate(
                        (('bin', '/run/c0/host-bin'), ('.local', '.local'),
                         ('bin', '/run/c0/host-bin'), ('.local', '.local'))):
                    cidfile = root / ('helper-' + str(index) + '.cid')
                    helper_cidfiles.append(cidfile)
                    result = subprocess.run(
                        ['/bin/bash', str(script)], capture_output=True, text=True, timeout=30,
                        env=dict(os.environ, TEST_PYTHON=sys.executable, TEST_HELPER_PEER=str(peer),
                                 TEST_DOCKER=docker, TEST_CACHED_IMAGE=CACHED_IMAGE,
                                 TEST_TASK_LABEL=LABEL + '=' + token,
                                 TEST_HELPER_CIDFILE=str(cidfile), TEST_TARGET=target,
                                 TEST_GUEST_REL=guest_rel, TEST_TOOLS_REL=tools_rel,
                                 TOOLS_PREFIX='/tools/current', TOOLS_ID=identity))
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

                observed = check(call(
                    'exec', '--user', '1000:1000', target, '/bin/busybox', 'sh', '-ec',
                    '/bin/busybox cat /home/dev/bin/fixture-launcher /home/dev/.local/packaged; '
                    'printf "%s\\n" "persistent tool upper" >/home/dev/.local/staged; '
                    'printf "%s\\n" "persistent launcher upper" >/home/dev/bin/staged; '
                    '/bin/busybox test ! -e /tmp/guest-shell-executed'))
                self.assertEqual(observed, 'synthetic launcher lower\nsynthetic tools lower')
                durable = short_job(
                    '--user', '1000:1000',
                    '--mount', 'type=volume,src=' + overlays + ',dst=/state,readonly',
                    '--entrypoint', '/bin/busybox', CACHED_IMAGE, 'sh', '-ec',
                    'cat /state/upper/local/staged /state/launcher/upper/staged; '
                    'test -d /state/work/' + identity + '/local; '
                    'test -d /state/launcher/work; '
                    'test ! -e /state/upper/local/fixture-launcher; '
                    'test ! -e /state/launcher/upper/packaged')
                self.assertEqual(durable, 'persistent tool upper\npersistent launcher upper')
                lower = short_job('--mount', 'type=volume,src=' + tools + ',dst=/tools,readonly',
                                  '--entrypoint', '/bin/busybox', CACHED_IMAGE,
                                  'cat', '/tools/.local/packaged')
                self.assertEqual(lower, 'synthetic tools lower')
            finally:
                errors = []
                for cidfile in helper_cidfiles:
                    if cidfile.exists():
                        cid = cidfile.read_text().strip()
                        if re.fullmatch(r'[0-9a-f]{64}', cid):
                            containers.append(cid)
                for cid in reversed(list(dict.fromkeys(containers))):
                    owner = call('inspect', '--format',
                                 '{{index .Config.Labels "' + LABEL + '"}}', cid)
                    if owner.returncode:
                        continue  # --rm helpers have already retired themselves.
                    if owner.stdout.strip() != token:
                        errors.append('retained container with uncertain task ownership: ' + cid)
                        continue
                    removed = call('rm', '-f', cid)
                    if removed.returncode:
                        errors.append(removed.stderr)
                for volume in reversed(volumes):
                    owner = call('volume', 'inspect', '--format',
                                 '{{index .Labels "' + LABEL + '"}}', volume)
                    if owner.returncode or owner.stdout.strip() != token:
                        errors.append('retained volume with uncertain task ownership: ' + volume)
                        continue
                    removed = call('volume', 'rm', volume)
                    if removed.returncode:
                        errors.append(removed.stderr)
                self.assertEqual(errors, [], '\n'.join(errors))


if __name__ == '__main__':
    unittest.main()
