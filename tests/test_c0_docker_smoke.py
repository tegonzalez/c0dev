# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Opt-in smoke test against Docker; uses only a cached image and disposable data.

C0_DOCKER_SMOKE=1 C0_DOCKER_SMOKE_IMAGE=<cached-runtime-image> \
    python3 -m unittest discover -s tests -p test_c0_docker_smoke.py -v
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import uuid
from c0_fixture import Fixture, REPO

SOURCE = (REPO/'bin/c0').read_text()
FUNCTIONS = '\n'.join(re.search(r'^'+name+r'\(\) \{\n.*?^\}', SOURCE, re.M|re.S).group()
    for name in ('c0_list_instance_containers', 'c0_list_workspace_containers', 'get_c0_container_id_any', 'get_c0_container_id',
                 'get_c0_container_state', 'get_tools_hash_label', 'resolve_volume_host_path',
                 'is_docker_volume', 'to_display_path', 'parse_folder_mappings', 'parse_file_mappings',
                 'c0_validate_overlay_volume', 'c0_overlay_volume_for_container',
                 'c0_discover_home_storage', 'c0_validate_container_mounts', 'c0_require_docker', 'c0_stop_instance',
                 'c0_validate_overlay_row', 'c0_mount_home_overlay'))


@unittest.skipUnless(os.environ.get('C0_DOCKER_SMOKE') == '1', 'opt-in: cached image and Docker daemon required')
class DockerSmoke(unittest.TestCase):
    def test_oneoff_identity_mount_validation_broken_link_and_stop(self):
        docker = shutil.which('docker')
        self.assertTrue(docker)
        def call(*args, **kwargs):
            return subprocess.run([docker, *args], capture_output=True, text=True, timeout=30, **kwargs)
        cached = call('image', 'inspect', 'alpine:latest')
        if cached.returncode: self.skipTest('alpine:latest not cached; refusing to pull')
        runtime = os.environ.get('C0_DOCKER_SMOKE_IMAGE')
        if not runtime: self.skipTest('set C0_DOCKER_SMOKE_IMAGE to a cached c0 runtime image')
        cached = call('image', 'inspect', runtime)
        if cached.returncode: self.skipTest('runtime image not cached; refusing to pull')
        f = Fixture()
        # The disposable host copy is writable by the guest UID by mode, so
        # read-only mount isolation is exercised independently of UID mapping.
        (f.checkout/'bin/c0').chmod(0o777)
        (f.home/'.gitconfig').chmod(0o666)
        prefix = 'c0-smoke-'+uuid.uuid4().hex[:12]
        tools = prefix+'-tools'
        overlays = f.instance+'-home-overlays'
        cid = None
        try:
            for name in (tools, overlays):
                result = call('volume', 'create', '--label', 'c0dev.test_run='+prefix, name)
                self.assertEqual(result.returncode, 0, result.stderr)
            result = call('run', '--rm', '--pull=never', '--network=none', '-v', tools+':/tools',
                          'alpine:latest', 'sh', '-ec',
                          'mkdir -p /tools/opt/'+f.tools+'; touch /tools/opt/'+f.tools+'/.c0dev-complete')
            self.assertEqual(result.returncode, 0, result.stderr)
            args = ['run', '-d', '--pull=never', '--network=none', '--name', prefix,
                    '--label', 'c0dev.instance='+f.instance,
                    '--label', 'c0dev.test_run='+prefix,
                    '--label', 'c0dev.tools_hash='+f.tools,
                    '--label', 'com.docker.compose.oneoff=True']
            for mount in f.container()['mounts']:
                if mount['type'] == 'bind':
                    value = 'type=bind,src='+mount['source']+',dst='+mount['target']
                    if not mount['rw']: value += ',readonly'
                elif mount['target'] == '/tools/current':
                    value = 'type=volume,src='+tools+',dst=/tools/current,readonly,volume-subpath=opt/'+f.tools
                else:
                    value = 'type=volume,src='+overlays+',dst=/run/c0/overlay-state'
                args += ['--mount', value]
            result = call(*args, '--user', '0', '--entrypoint', '/bin/sleep', runtime, '120')
            self.assertEqual(result.returncode, 0, result.stderr)
            cid = result.stdout.strip()
            script = f.root/'verify.sh'
            script.write_text('set -e\n'+FUNCTIONS+'''
C0ROOT="$TEST_ROOT"
C0_INSTANCE_ID="$TEST_INSTANCE"
SHARED_TOOLS_VOLUME="$TEST_TOOLS_VOLUME"
TOOLS_PREFIX=/tools/current
TOOLS_ID="$TEST_TOOLS_ID"
VOLUMES_FOLDERS_FILE="$C0ROOT/docker/volumes-folders.yaml"
VOLUMES_FILES_FILE="$C0ROOT/docker/volumes-files.yaml"
case "$1" in
    identity) get_c0_container_id ;;
    validate) c0_validate_container_mounts "$2" true ;;
    overlay) c0_mount_home_overlay "$2" bin /run/c0/host-bin ;;
    stop) c0_stop_instance ;;
esac
''')
            env = dict(os.environ, TEST_ROOT=str(f.checkout), HOME=str(f.home),
                       TEST_INSTANCE=f.instance, TEST_TOOLS_ID=f.tools,
                       TEST_TOOLS_VOLUME=tools)
            def verify(*args):
                return subprocess.run(['/bin/bash', str(script), *args], env=env,
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(verify('identity').stdout.strip(), cid)
            result = verify('overlay', cid)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = verify('validate', cid)
            self.assertEqual(result.returncode, 0, result.stderr)
            original = (f.checkout/'bin/c0').read_bytes()
            result = call('exec', '-u', '1000', cid, '/bin/sh', '-ec',
                          'printf "\\nguest override\\n" >>/home/dev/bin/c0; '
                          'rm /home/dev/bin/docker-hash; '
                          'test ! -e /home/dev/bin/docker-hash; '
                          '! touch /run/c0/host-bin/guest-write; '
                          '! sh -c "echo guest >>/home/dev/.gitconfig"')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((f.checkout/'bin/c0').read_bytes(), original)
            self.assertTrue((f.checkout/'bin/docker-hash').exists())
            self.assertFalse((f.checkout/'bin/guest-write').exists())
            self.assertEqual((f.home/'.gitconfig').read_text(), '[user]\n name = fixture\n')
            result = call('exec', cid, 'ln', '-s', '/missing-target', '/home/dev/packages')
            self.assertEqual(result.returncode, 0, result.stderr)
            result = verify('validate', cid)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('broken guest home link: /home/dev/packages', result.stderr)
            result = verify('stop')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotEqual(call('inspect', cid).returncode, 0)
            self.assertEqual(verify('identity').stdout.strip(), '')
            self.assertEqual(call('volume', 'inspect', overlays).returncode, 0)
        finally:
            if cid:
                metadata = call('inspect', cid)
                if metadata.returncode == 0 and json.loads(metadata.stdout)[0]['Config']['Labels'].get('c0dev.test_run') == prefix:
                    call('rm', '-f', cid)
            for volume in (tools, overlays):
                metadata = call('volume', 'inspect', volume)
                if metadata.returncode == 0 and (json.loads(metadata.stdout)[0].get('Labels') or {}).get('c0dev.test_run') == prefix:
                    call('volume', 'rm', volume)
            f.close()


if __name__ == '__main__': unittest.main()
