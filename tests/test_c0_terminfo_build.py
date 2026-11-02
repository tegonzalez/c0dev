# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Build-path terminal capture and runtime-cache regression checks.

The oracle is docs/spec.md#build and #validation: caller terminal content is a
local runtime input, with unchanged tools identity. The actual CLI is sourced
and cmd_build executes, including preparation, identity, and runtime cache
functions. Only acquisition/build peers and the Docker transport are inert.
Host tic/infocmp compile and inspect the captured definitions; this is not a
Docker integration or package-installation test.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

DOCKER = r'''
import json, os, re, shutil, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(os.environ['TEST_ROOT'])
state_path = root/'docker-state.json'
state = json.loads(state_path.read_text())
state['calls'].append(args)
def finish(code=0, output=''):
    state_path.write_text(json.dumps(state))
    if output: print(output)
    sys.exit(code)
if args[:2] == ['image', 'inspect']:
    ref = args[-1]
    image = state['images'].get(ref)
    if not image:
        if ref.startswith('c0dev-base-'): finish(output='sha256:'+'a'*64)
        finish(1)
    fmt = args[args.index('--format')+1] if '--format' in args else ''
    if 'c0dev.mode' in fmt:
        finish(output='\t'.join(image['labels'][k] for k in
               ('mode','recipe','build','tools_hash','tools_volume','base_image')))
    finish(output=image['id'])
if args[:2] == ['image', 'tag']:
    image = state['images'][args[2]]
    state['images'][args[3]] = image
    state['publications'].append(args[3])
    finish()
if args[:2] == ['image', 'rm']: finish()
if args[0] == 'run':
    image = next((state['images'][a] for a in args if a in state['images']), None)
    if not image: finish(90, 'unknown validation image')
    # Validate only names requested by the real production validator.
    # A baseline-only validator must not acquire caller coverage from this double.
    if 'c0-runtime-check' in args:
        names = args[args.index('c0-runtime-check')+1:]
        if not names: finish(93, 'validator supplied no terminal definitions')
    else:
        names = ['xterm-256color']
    state.setdefault('validation_requests', []).append(names)
    for name in names:
        checked = subprocess.run([os.environ['REAL_INFOCMP'], '-A', image['database'], name],
                                 text=True, capture_output=True)
        if checked.returncode: finish(91, checked.stderr)
    finish()
if args[0] == 'compose' and 'build' in args:
    context = Path(os.environ['C0_BUILD_CONTEXT']).resolve()
    descriptors = [args[i+1] for i, arg in enumerate(args[:-1]) if arg in ('-f', '--file')]
    if [Path(path).resolve() for path in descriptors] != [context/'runtime-image.yaml']:
        finish(94, 'Compose build included runtime configuration: '+repr(descriptors))
    if any(arg.startswith(('-f=', '--file=')) for arg in args):
        finish(94, 'unexpected additional Compose descriptor')
    spec = Path(descriptors[0]).read_text()
    try:
        build_context = Path(json.loads(re.search(r'^\s*context: (.+)$', spec, re.M).group(1)).replace('$$','$')).resolve()
        dockerfile = Path(json.loads(re.search(r'^\s*dockerfile: (.+)$', spec, re.M).group(1)).replace('$$','$')).resolve()
    except (ValueError, AttributeError):
        finish(95, 'construction descriptor has no explicit quoted context/Dockerfile')
    if build_context != context or dockerfile != context/'Dockerfile.runtime.build' or not dockerfile.is_file():
        finish(95, 'construction descriptor escaped its owned context')
    tag = re.search(r'^\s*image: (.+)$', spec, re.M).group(1)
    labels = dict(re.findall(r'^\s*c0dev\.([^:]+): "(.*)"$', spec, re.M))
    number = len(state['builds'])+1
    saved = root/'images'/str(number)
    saved.mkdir(parents=True)
    source = saved/'source'
    shutil.copytree(context/'.terminfo', source)
    database = saved/'terminfo'
    names = sorted(p.name for p in source.iterdir())
    for name in names:
        compiled = subprocess.run([os.environ['REAL_TIC'], '-x', '-o', str(database), str(source/name)],
                                  text=True, capture_output=True)
        if compiled.returncode: finish(92, compiled.stderr)
    image = dict(id='sha256:'+format(number,'064x'), labels=labels,
                 terminals=names, database=str(database), source=str(source))
    state['images'][tag] = image
    state['images'][image['id']] = image
    state['builds'].append(image)
    finish()
finish(99, 'unsupported Docker operation '+repr(args))
'''

DRIVER = r'''
source "$TEST_ROOT/checkout/bin/c0" help >/dev/null
IN_CONTAINER=false
require_host() { :; }
verify_moby_seccomp_profile() { :; }
maybe_notify_seccomp_update_available() { :; }
c0_ssh_ensure_keys() { :; }
c0_build_base_image() { :; }
build_tools_volume() { :; }
gc_tools_hashes() { :; }
cmd_build "$@"
'''


class BuildFixture:
    def __init__(self, source=None):
        self.temporary = tempfile.TemporaryDirectory(prefix='c0-terminfo-build-')
        self.root = Path(self.temporary.name).resolve()
        self.checkout = self.root/'checkout'
        (self.checkout/'bin').mkdir(parents=True)
        (self.checkout/'docker/seccomp').mkdir(parents=True)
        for name in ('c0','c0-terminfo','c0-host-io','c0-credentials','docker-hash','dockerfile-concat'):
            shutil.copy2(ROOT/'bin'/name, self.checkout/'bin'/name)
        if source is not None:
            (self.checkout/'bin/c0').write_text(source)
        for name in ('Dockerfile.base','Dockerfile.tools','Dockerfile.runtime',
                     'install-orca.sh','home-overlays.conf','c0-overlay-check','c0-publish-tools',
                     'c0-security.py','1password.asc','cloud.google.gpg','docker-entrypoint.sh',
                     'docker-compose.public.yaml','docker-compose.security-guest-admin.yaml',
                     'docker-compose.security-least-privilege.yaml','volumes-folders.yaml','volumes-files.yaml',
                     'seccomp/moby-default-seccomp.json','seccomp/moby-default-seccomp.sha256',
                     'seccomp/moby-seccomp.tag'):
            shutil.copy2(ROOT/'docker'/name, self.checkout/'docker'/name)
        # These are runtime-creation inputs, unrelated to this image-build fixture.
        for name in ('volumes-folders.yaml', 'volumes-files.yaml'):
            (self.checkout/'docker'/name).write_text('services:\n  c0dev:\n    volumes: []\n')
        resolver = self.checkout/'bin/c0-toolchain'
        resolver.write_text('''#!/bin/sh
case "$1" in
 --output) cp "$TEST_ROOT/manifest.json" "$2" ;;
 --build-args) printf 'BUN_VERSION=1.4.4\\n' ;;
 *) exit 94 ;;
esac
''')
        resolver.chmod(0o755)
        (self.root/'manifest.json').write_text('{"test":"fixed construction selections"}\n')
        (self.root/'bin').mkdir()
        docker = self.root/'bin/docker'
        docker.write_text('#!'+sys.executable+'\n'+DOCKER)
        docker.chmod(0o755)
        (self.root/'docker-state.json').write_text(json.dumps(dict(images={}, builds=[], publications=[], calls=[])))
        (self.root/'driver.sh').write_text(DRIVER)
        self.infocmp = shutil.which('infocmp')
        self.tic = shutil.which('tic')
        self.database = self.root/'host-terminfo'
        self.name = 'c0-build-synthetic-terminal'
        self.definition(80)
        self.env = dict(os.environ, PATH=str(self.root/'bin')+os.pathsep+os.environ['PATH'],
                        TEST_ROOT=str(self.root), REAL_INFOCMP=self.infocmp, REAL_TIC=self.tic,
                        TERMINFO=str(self.database), C0_MODE='', C0_SECCOMP_NOTIFY='0', C0_SSH_AGENT='0')

    def close(self): self.temporary.cleanup()

    def definition(self, columns):
        source = subprocess.check_output([self.infocmp, '-x', 'xterm-256color'], text=True)
        lines = source.splitlines()
        for n, line in enumerate(lines):
            if line and not line.startswith('#'):
                lines[n] = self.name+'|caller build test terminal,'
                break
        source = re.sub(r'\bcols#\d+', 'cols#'+str(columns), '\n'.join(lines)+'\n')
        path = self.root/'host-source'
        path.write_text(source)
        subprocess.run([self.tic, '-x', '-o', str(self.database), str(path)],
                       check=True, text=True, capture_output=True)

    def build(self, terminal='caller', force=False):
        env = dict(self.env)
        if terminal is None: env.pop('TERM', None)
        else: env['TERM'] = self.name if terminal == 'caller' else terminal
        return subprocess.run(['/bin/bash', str(self.root/'driver.sh')]+(['-f'] if force else []),
                              env=env, cwd=self.checkout, stdin=subprocess.DEVNULL,
                              text=True, capture_output=True, timeout=20)

    def state(self): return json.loads((self.root/'docker-state.json').read_text())

    def last_image(self):
        state = self.state()
        tag = next(tag for tag in reversed(state['publications'])
                   if tag.startswith('c0dev-runtime-prod:') and ':recipe-' not in tag and ':latest' not in tag)
        return state['images'][tag]


@unittest.skipUnless(shutil.which('tic') and shutil.which('infocmp'), 'host ncurses tools required')
class BuildTerminfo(unittest.TestCase):
    def setUp(self):
        self.f = BuildFixture()
        self.addCleanup(self.f.close)

    def accepted(self, result):
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('Build complete', result.stdout)

    def assert_caller_image(self, columns=80):
        image = self.f.last_image()
        self.assertEqual(image['terminals'], [self.f.name, 'xterm-256color'])
        result = subprocess.run([self.f.infocmp, '-A', image['database'], self.f.name],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('cols#'+str(columns), result.stdout)
        return image

    def test_actual_build_captures_caller_and_reuses_only_matching_runtime(self):
        self.accepted(self.f.build())
        first = self.assert_caller_image()
        self.assertEqual(len(self.f.state()['builds']), 1)
        reused = self.f.build()
        self.accepted(reused)
        self.assertIn('Image: valid', reused.stdout)
        self.assertEqual(len(self.f.state()['builds']), 1)
        self.f.definition(99)
        self.accepted(self.f.build())
        changed = self.assert_caller_image(99)
        self.assertEqual(len(self.f.state()['builds']), 2)
        self.assertNotEqual(first['labels']['build'], changed['labels']['build'])
        self.assertEqual(first['labels']['tools_hash'], changed['labels']['tools_hash'])
        self.assertEqual(first['labels']['base_image'], changed['labels']['base_image'])
        # Rewriting identical input is a permitted variation, not a cache miss.
        self.f.definition(99)
        self.accepted(self.f.build())
        self.assertEqual(len(self.f.state()['builds']), 2)

    def test_cached_runtime_missing_caller_definition_is_rebuilt(self):
        self.accepted(self.f.build())
        before = self.assert_caller_image()
        files = list(Path(before['database']).rglob(self.f.name))
        self.assertTrue(files, 'fixture did not compile the caller definition')
        for path in files:
            path.unlink()
        state = self.f.state()
        state['validation_requests'] = []
        (self.f.root/'docker-state.json').write_text(json.dumps(state))
        repaired = self.f.build()
        self.accepted(repaired)
        self.assertNotIn('Image: valid', repaired.stdout)
        self.assertEqual(len(self.f.state()['builds']), 2)
        after = self.assert_caller_image()
        self.assertNotEqual(before['id'], after['id'])
        self.assertEqual(before['labels'], after['labels'])
        self.assertTrue(all(self.f.name in names for names in self.f.state()['validation_requests']))

    def test_equivalent_definitions_share_identity_across_host_database_paths(self):
        other = BuildFixture()
        self.addCleanup(other.close)
        self.assertNotEqual(self.f.database, other.database)
        self.accepted(self.f.build())
        self.accepted(other.build())
        first, second = self.f.last_image(), other.last_image()
        for key in ('recipe', 'build', 'tools_hash', 'base_image'):
            self.assertEqual(first['labels'][key], second['labels'][key], key)

    def test_runtime_only_copied_input_changes_runtime_but_not_base_or_tools(self):
        self.accepted(self.f.build())
        before = self.assert_caller_image()
        path = self.f.checkout/'docker/docker-entrypoint.sh'
        path.write_text(path.read_text()+'\n# changed consumed runtime entrypoint bytes\n')
        self.accepted(self.f.build())
        after = self.assert_caller_image()
        self.assertEqual(len(self.f.state()['builds']), 2)
        self.assertNotEqual(before['labels']['build'], after['labels']['build'])
        self.assertEqual(before['labels']['tools_hash'], after['labels']['tools_hash'])
        self.assertEqual(before['labels']['base_image'], after['labels']['base_image'])

    def test_force_build_keeps_caller_and_identity_but_bypasses_reuse(self):
        self.accepted(self.f.build())
        before = self.assert_caller_image()
        forced = self.f.build(force=True)
        self.accepted(forced)
        after = self.assert_caller_image()
        self.assertNotIn('Image: valid', forced.stdout)
        self.assertEqual(len(self.f.state()['builds']), 2)
        self.assertEqual(before['labels']['build'], after['labels']['build'])
        self.assertEqual(before['labels']['tools_hash'], after['labels']['tools_hash'])
        self.assertEqual(before['labels']['base_image'], after['labels']['base_image'])
        builds = [call for call in self.f.state()['calls'] if call[0] == 'compose']
        self.assertIn('--no-cache', builds[-1])

    def test_headless_and_unavailable_caller_have_only_baseline(self):
        self.accepted(self.f.build(terminal=None))
        self.assertEqual(self.f.last_image()['terminals'], ['xterm-256color'])
        unavailable = self.f.build(terminal='c0-unavailable-terminal-definition')
        self.accepted(unavailable)
        self.assertIn('unavailable-terminal-definition', unavailable.stderr)
        self.assertEqual(self.f.last_image()['terminals'], ['xterm-256color'])
        invalid = self.f.build(terminal='../../invalid-terminal')
        self.accepted(invalid)
        self.assertIn('invalid caller TERM', invalid.stderr)
        self.assertEqual(self.f.last_image()['terminals'], ['xterm-256color'])

    def test_missing_baseline_refuses_before_runtime_build_or_publication(self):
        fake = self.f.root/'bin/infocmp'
        fake.write_text('#!/bin/sh\nexit 1\n')
        fake.chmod(0o755)
        result = self.f.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('xterm-256color', result.stderr)
        self.assertEqual(self.f.state()['builds'], [])
        self.assertEqual(self.f.state()['publications'], [])

    def test_runtime_mount_configuration_is_not_a_build_prerequisite_or_input(self):
        self.accepted(self.f.build())
        before = self.assert_caller_image()
        changes = {
            'volumes-folders.yaml': 'services:\n  c0dev:\n    volumes:\n      - /c0-nonexistent-host-folder:/mnt/\n',
            'volumes-files.yaml': 'services:\n  c0dev:\n    volumes:\n      - /c0-nonexistent-host-file:/run/runtime-file:ro\n',
            'docker-compose.public.yaml': '\nx-c0-runtime-note: changed\n',
            'docker-compose.security-guest-admin.yaml': '\nx-c0-runtime-note: changed\n',
            'home-overlays.conf': '\n# changed runtime overlay policy\n',
            'c0-overlay-check': '\n# changed runtime-only checker\n',
            'unrelated-local-note': 'not an image-construction input\n',
        }
        for name, change in changes.items():
            with self.subTest(runtime_input=name):
                path = self.f.checkout/'docker'/name
                if name.startswith('volumes-') or not path.exists():
                    path.write_text(change)
                else:
                    path.write_text(path.read_text()+change)
                result = self.f.build()
                self.accepted(result)
                self.assertIn('Image: valid', result.stdout)
                self.assertEqual(len(self.f.state()['builds']), 1)
                self.assertEqual(before['labels'], self.f.last_image()['labels'])
        # Force the uncached construction transport while every runtime YAML is
        # syntactically invalid. A cache-only check cannot prove their exclusion.
        for name in ('volumes-folders.yaml', 'volumes-files.yaml',
                     'docker-compose.public.yaml', 'docker-compose.security-guest-admin.yaml',
                     'docker-compose.security-least-privilege.yaml'):
            (self.f.checkout/'docker'/name).write_text('not: [valid: YAML\n')
        forced = self.f.build(force=True)
        self.accepted(forced)
        self.assertNotIn('Image: valid', forced.stdout)
        self.assertEqual(len(self.f.state()['builds']), 2)
        self.assertEqual(before['labels'], self.f.last_image()['labels'])
        # The same malformed runtime files must also permit an ordinary build
        # when no completed image is available, not just force a cached one.
        state = self.f.state()
        state['images'] = {}
        (self.f.root/'docker-state.json').write_text(json.dumps(state))
        uncached = self.f.build()
        self.accepted(uncached)
        self.assertNotIn('Image: valid', uncached.stdout)
        self.assertEqual(len(self.f.state()['builds']), 3)
        self.assertEqual(before['labels'], self.f.last_image()['labels'])
        self.assertFalse(any(call[0] in ('exec','start','stop','rm','ps')
                             for call in self.f.state()['calls']))


if __name__ == '__main__': unittest.main()
