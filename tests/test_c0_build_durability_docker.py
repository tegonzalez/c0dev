# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Opt-in real runtime build, publication, and failed-validation preservation.

C0_BUILD_DOCKER_TESTS=1 python3 -m unittest discover -s tests \\
    -p test_c0_build_durability_docker.py -v

Builds the actual runtime recipe with the Bun security-floor fixture release.
Does not create guest containers, touch shared tools, or change checkout pins.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT/'bin/c0').read_text()


def function(name):
    return re.search(r'^'+name+r'\(\) \{\n.*?^\}', SOURCE, re.M | re.S).group()


@unittest.skipUnless(os.environ.get('C0_BUILD_DOCKER_TESTS') == '1', 'opt-in real Docker build')
class BuildDurabilityDocker(unittest.TestCase):
    def test_dev_owned_private_manifest_probe(self):
        docker = shutil.which('docker')
        self.assertTrue(docker)
        if subprocess.run([docker, 'image', 'inspect', 'alpine:latest'],
                          capture_output=True).returncode:
            self.skipTest('alpine is not cached; refusing to pull')
        token = uuid.uuid4().hex
        volume = 'c0-build-metadata-audit-' + token
        label = 'c0dev.build_audit'
        identity = 'a'*64
        manifest = '{"schema":1,"versions":{"node":"22.23.4"}}\n'

        def call(*args, **kwargs):
            return subprocess.run([docker, *args], capture_output=True,
                                  text=True, timeout=30, **kwargs)

        self.assertNotEqual(call('volume', 'inspect', volume).returncode, 0)
        created = call('volume', 'create', '--label', label+'='+token, volume)
        self.assertEqual(created.returncode, 0, created.stderr)
        try:
            # Match the atomic resolver's actual permissions after COPY and tar:
            # UID1000 owns the private manifest, while its parent is traversable.
            setup = call('run', '--rm', '--pull=never', '--network', 'none', '-i',
                         '-v', volume+':/tools', 'alpine:latest', 'sh', '-ec',
                         'p=/tools/opt/'+identity+'; mkdir -p "$p"; '
                         'cat >"$p/.c0dev-toolchain.json"; '
                         'chmod 600 "$p/.c0dev-toolchain.json"; '
                         'chown 1000:1000 "$p/.c0dev-toolchain.json"; '
                         'touch "$p/.c0dev-complete"', input=manifest)
            self.assertEqual(setup.returncode, 0, setup.stderr)
            permissions = call('run', '--rm', '--pull=never', '--network', 'none',
                               '--read-only', '-v', volume+':/tools:ro', 'alpine:latest',
                               'stat', '-c', '%u:%g:%a',
                               '/tools/opt/'+identity+'/.c0dev-toolchain.json')
            self.assertEqual(permissions.stdout.strip(), '1000:1000:600')
            helpers = '\n'.join(function(name) for name in
                                ('c0_docker_run', 'tools_volume_build_matches'))
            script = helpers+'''
C0_BUILD_CONTEXT="$TEST_CONTEXT"
SHARED_TOOLS_VOLUME="$TEST_VOLUME"
tools_volume_build_matches "$TEST_ID"
'''
            with tempfile.TemporaryDirectory(prefix='c0-private-manifest-audit-') as temp:
                path = Path(temp)/'c0-toolchain.json'
                env = dict(os.environ, TEST_CONTEXT=temp, TEST_VOLUME=volume, TEST_ID=identity)
                for payload, expected in ((manifest, 0),
                                          (manifest.replace('22.23.4', '22.23.3'), 1)):
                    with self.subTest(payload=payload):
                        path.write_text(payload)
                        result = subprocess.run(['/bin/bash', '-c', script], env=env,
                                                capture_output=True, text=True, timeout=30)
                        self.assertEqual(result.returncode, expected, result.stderr)
                path.write_text(manifest)
                removed = call('run', '--rm', '--pull=never', '--network', 'none',
                               '-v', volume+':/tools', 'alpine:latest', 'rm',
                               '/tools/opt/'+identity+'/.c0dev-complete')
                self.assertEqual(removed.returncode, 0, removed.stderr)
                result = subprocess.run(['/bin/bash', '-c', script], env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0, result.stderr)
        finally:
            ownership = call('volume', 'inspect', '--format',
                             '{{index .Labels "'+label+'"}}', volume)
            self.assertEqual(ownership.returncode, 0, ownership.stderr)
            self.assertEqual(ownership.stdout.strip(), token,
                             'refusing to remove volume without this test ownership label')
            removed = call('volume', 'rm', volume)
            self.assertEqual(removed.returncode, 0, removed.stderr)

    def test_real_runtime_build_and_failed_validation_preserve_published_image(self):
        docker = shutil.which('docker')
        self.assertTrue(docker)
        instance = 'c0-build-audit-' + uuid.uuid4().hex[:10]
        published = instance+'-c0dev:latest'
        tags = [published]
        with tempfile.TemporaryDirectory(prefix='c0-runtime-audit-') as temporary:
            root = Path(temporary)
            context = root/'context'
            context.mkdir()
            wrapper = root/'bin'
            wrapper.mkdir()
            (wrapper/'docker').write_text('#!'+sys.executable+'\n'+'''
import os, sys
if sys.argv[1] == 'run' and os.environ.get('TEST_FAIL_SMOKE') == '1':
    print('injected Docker image launch failure', file=sys.stderr)
    sys.exit(29)
os.execv('''+repr(docker)+', ['+repr(docker)+']+sys.argv[1:])\n')
            (wrapper/'docker').chmod(0o755)
            helpers = '\n'.join(function(name) for name in (
                'c0_prepare_build_context', 'c0_prepare_runtime_dockerfile',
                'c0_prepare_terminfo', 'dc_build', 'c0_docker_content_failure',
                'c0_validate_runtime_image', 'c0_build_runtime_image'))
            script = root/'build.sh'
            script.write_text('set -e\n'+helpers+'''
C0ROOT="$TEST_CHECKOUT"
C0_BUILD_CONTEXT="$TEST_CONTEXT"
DOCKERFILE_BASE="$C0ROOT/docker/Dockerfile.base"
DOCKERFILE_RUNTIME="$C0ROOT/docker/Dockerfile.runtime"
DOCKERFILE_RUNTIME_BUILD="$C0_BUILD_CONTEXT/Dockerfile.runtime.build"
C0_INSTANCE_ID="$TEST_INSTANCE"
MAIN_SERVICE=c0dev
SHARED_TOOLS_VOLUME=unused-build-audit
TOOLS_ID=unused-build-audit
TOOLS_PREFIX=/tools/current
VOLUMES_FOLDERS_FILE="$C0ROOT/docker/volumes-folders.yaml"
VOLUMES_FILES_FILE="$C0ROOT/docker/volumes-files.yaml"
COMPOSE_PUBLIC_FILE="$C0ROOT/docker/docker-compose.public.yaml"
C0_TOOLCHAIN_BUILD_ARGS=(--build-arg BUN_VERSION=1.4.4)
c0_prepare_build_context
c0_prepare_runtime_dockerfile
c0_prepare_terminfo
c0_build_runtime_image ''
''')
            env = dict(os.environ, PATH=str(wrapper)+os.pathsep+os.environ['PATH'],
                       TEST_CHECKOUT=str(ROOT), TEST_CONTEXT=str(context),
                       TEST_INSTANCE=instance, TERM='xterm-256color')
            try:
                result = subprocess.run(['/bin/bash', str(script)], env=env,
                                        capture_output=True, text=True, timeout=900)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                tags.append(instance+'-build:'+root.name)
                image = subprocess.check_output([docker, 'image', 'inspect', '--format', '{{.Id}}', published], text=True).strip()
                # Docker really launches this immutable image with no network and
                # no writable image filesystem in the production validator above.
                self.assertEqual(image, (context/'.runtime-image-id').read_text().strip())
                result = subprocess.run(['/bin/bash', str(script)],
                                        env=dict(env, TEST_FAIL_SMOKE='1'),
                                        capture_output=True, text=True, timeout=900)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('previous published image and tools selection retained', result.stderr)
                retained = subprocess.check_output([docker, 'image', 'inspect', '--format', '{{.Id}}', published], text=True).strip()
                self.assertEqual(retained, image)
            finally:
                for tag in tags:
                    subprocess.run([docker, 'image', 'rm', tag], capture_output=True)


if __name__ == '__main__':
    unittest.main()
