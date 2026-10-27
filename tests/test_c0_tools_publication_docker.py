# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Opt-in: accepted tools publish a real shared image without workspace state."""
import hashlib
import json
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
SOURCE = (ROOT / 'bin/c0').read_text()
IMAGE = os.environ.get('C0_DOCKER_SMOKE_IMAGE')


def function(name):
    return re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE, re.M | re.S).group()


@unittest.skipUnless(os.environ.get('C0_BUILD_DOCKER_TESTS') == '1' and IMAGE,
                     'opt-in: cached c0 runtime and real Docker required')
class ToolsPublicationDocker(unittest.TestCase):
    def test_accepted_runtime_is_real_published_content_and_retains_running_guest(self):
        docker = shutil.which('docker')
        self.assertTrue(docker)
        def call(*arguments, **kwargs):
            return subprocess.run([docker, *arguments], capture_output=True, text=True,
                                  timeout=180, **kwargs)
        original = call('image', 'inspect', IMAGE)
        if original.returncode:
            self.skipTest('runtime image is not cached; refusing to pull')
        source_id = json.loads(original.stdout)[0]['Id']
        token = uuid.uuid4().hex
        digest = lambda value: hashlib.sha256((token + value).encode()).hexdigest()
        parent, recipe, tools, accepted = map(digest, ('parent', 'recipe', 'tools', 'accepted'))
        build = hashlib.sha256(('c0-tools-accept-build-v1\n' + parent + '\n' + accepted + '\n').encode()).hexdigest()
        parent_runtime = 'c0dev-runtime-prod:' + parent
        base = 'c0dev-base-prod:' + parent
        new_runtime = 'c0dev-runtime-prod:' + build
        new_base = 'c0dev-base-prod:' + build
        published = 'c0dev-runtime-prod:recipe-' + recipe
        tags = [parent_runtime, base, new_runtime, new_base, published]
        for tag in tags:
            self.assertNotEqual(call('image', 'inspect', tag).returncode, 0,
                                'refusing to overwrite preexisting test namespace')
        cid = None
        with tempfile.TemporaryDirectory(prefix='c0-tools-publication-') as directory:
            context = Path(directory)
            try:
                self.assertEqual(call('image', 'tag', source_id, base).returncode, 0)
                (context / 'Dockerfile').write_text('FROM ' + IMAGE + '\n')
                built = call('build', '--pull=false', '--network', 'none',
                             '--label', 'c0dev.test_run=' + token,
                             '--label', 'c0dev.build=' + parent,
                             '--label', 'c0dev.recipe=' + recipe,
                             '--label', 'c0dev.mode=prod',
                             '--label', 'c0dev.tools_hash=' + tools,
                             '--label', 'c0dev.tools_volume=owned-tools-' + token,
                             '--label', 'c0dev.base_image=' + base,
                             '-t', parent_runtime, str(context))
                self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                self.assertEqual(call('image', 'tag', parent_runtime, published).returncode, 0)
                started = call('run', '-d', '--pull=never', '--network', 'none',
                               '--label', 'c0dev.test_run=' + token, '--user', '1000:1000',
                               '--entrypoint', '/bin/sleep', parent_runtime, '180')
                self.assertEqual(started.returncode, 0, started.stderr)
                cid = started.stdout.strip()
                marked = call('exec', cid, 'sh', '-ec', 'printf user-data >/home/dev/unmounted-note')
                self.assertEqual(marked.returncode, 0, marked.stderr)
                helpers = '\n'.join(function(name) for name in (
                    'c0_accept_runtime_metadata', 'c0_publish_accepted_runtime',
                    'c0_validate_runtime_image', 'c0_publish_runtime_image'))
                script = helpers + r'''
C0_MODE_KEY=prod
C0_RECIPE_ID="$TEST_RECIPE"
SHARED_TOOLS_VOLUME="owned-tools-$TEST_TOKEN"
TOOLS_ID="$TEST_TOOLS"
c0_runtime_recipe_ref() { printf 'c0dev-runtime-prod:recipe-%s\n' "$C0_RECIPE_ID"; }
c0_set_build_identity() {
    C0_BUILD_ID=$1
    C0_RUNTIME_IMAGE="c0dev-runtime-prod:$1"
    C0_BASE_IMAGE="c0dev-base-prod:$1"
}
metadata="$(c0_accept_runtime_metadata "$TEST_CID")" || exit
c0_publish_accepted_runtime "$metadata" "$TEST_ACCEPTED"
'''
                env = dict(os.environ, TEST_RECIPE=recipe, TEST_TOOLS=tools,
                           TEST_ACCEPTED=accepted, TEST_TOKEN=token, TEST_CID=cid,
                           TMPDIR=str(context) + '/')
                result = subprocess.run(['/bin/bash', '-c', script], env=env,
                                        capture_output=True, text=True, timeout=180)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                current = json.loads(call('image', 'inspect', published).stdout)[0]
                self.assertEqual(current['Config']['Labels']['c0dev.build'], build)
                self.assertEqual(current['Config']['Labels']['c0dev.tools_hash'], accepted)
                self.assertEqual(current['Config']['Labels']['c0dev.base_image'], new_base)
                self.assertEqual(json.loads(call('image', 'inspect', new_runtime).stdout)[0]['Id'], current['Id'])
                self.assertEqual(json.loads(call('image', 'inspect', new_base).stdout)[0]['Id'], source_id)
                self.assertEqual(call('exec', cid, 'cat', '/home/dev/unmounted-note').stdout, 'user-data')
                self.assertEqual(json.loads(call('inspect', cid).stdout)[0]['State']['Status'], 'running')
                self.assertEqual(sorted(path.name for path in context.iterdir()), ['Dockerfile'])
                wrapper = context / 'commands'
                wrapper.mkdir()
                (wrapper / 'docker').write_text('#!' + sys.executable + '\n' +
                    'import os,sys\nif sys.argv[1] == "build": sys.exit(29)\n' +
                    'os.execv(' + repr(docker) + ', [' + repr(docker) + '] + sys.argv[1:])\n')
                (wrapper / 'docker').chmod(0o755)
                failed = subprocess.run(['/bin/bash', '-c', script], env=dict(
                    env, TEST_ACCEPTED=digest('failed-acceptance'),
                    PATH=str(wrapper) + os.pathsep + os.environ['PATH']),
                    capture_output=True, text=True, timeout=180)
                self.assertNotEqual(failed.returncode, 0)
                self.assertEqual(json.loads(call('image', 'inspect', published).stdout)[0]['Id'], current['Id'])
                self.assertEqual(call('exec', cid, 'cat', '/home/dev/unmounted-note').stdout, 'user-data')
            finally:
                if cid:
                    inspected = call('inspect', cid)
                    if inspected.returncode == 0 and json.loads(inspected.stdout)[0]['Config']['Labels'].get('c0dev.test_run') == token:
                        call('rm', '-f', cid)
                # Exact unique tags are created only after absence was checked.
                # Base aliases may share source image content; remove aliases only.
                for tag in tags:
                    call('image', 'rm', tag)


if __name__ == '__main__':
    unittest.main()
