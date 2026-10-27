# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Prove artifact sharing and workspace isolation without saved c0 selectors.

C0_SHARING_DOCKER=1 C0_SHARING_DOCKER_IMAGE=<cached-runtime-image> \
    python3 -m unittest discover -s tests \
    -p test_c0_sharing_matrix.py -v

Docker runs use unique recipe labels, owned disposable stores and temporary
workspaces. Production base/runtime build, publication and lifecycle helpers
execute with small Docker fixture recipes based on a cached complete runtime.
A fixed release manifest and small tools payload keep this identity test
independent of package installation and upstream release changes.
"""
import json
import os
from pathlib import Path
import pty
import re
import runpy
import select
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = runpy.run_path(str(ROOT / 'bin/c0-toolchain'))


def controlled_manifest():
    versions = dict(bun='1.4.4', uv='0.13.5', fnm='1.39.0', node='22.23.4',
                    python='3.15.2', pip='26.2.2', npm='12.2.1', pnpm='12.15.0',
                    semgrep='1.182.1')
    return RESOLVER['canonical_json'](dict(schema=1, versions=versions,
                                         sources=RESOLVER['source_urls'](
                                             versions, 'https://github.com/astral-sh/python-build-standalone/releases/download/'
                                             '20261026/cpython-3.15.2%2B20261026-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz'
                                             '#sha256=' + 'a' * 64)))


def checkout(parent, name, token):
    directory = parent / name
    (directory / 'bin').mkdir(parents=True)
    shutil.copytree(ROOT / 'docker', directory / 'docker',
                    ignore=shutil.ignore_patterns('.terminfo', '.Dockerfile*', '.compose.*'))
    for script in ('c0', 'docker-hash', 'dockerfile-concat', 'activate',
                   'list-listening-ports', 'c0-toolchain', 'c0-terminfo', 'c0-host-io', 'c0-credentials'):
        shutil.copy2(ROOT / 'bin' / script, directory / 'bin' / script)
    # Same content in both workspaces; also gives all derived test artifacts a
    # label that must match before cleanup is allowed.
    base = directory / 'docker/Dockerfile.base'
    base.write_text(base.read_text() + '\nLABEL c0dev.test_run=' + token + '\n')
    for relative in ('.claude', '.cache', '.codex', '.kimi-code', '.config',
                     '.local', 'rules', 'projects', 'auth/ssh'):
        (directory / relative).mkdir(parents=True, exist_ok=True)
    (directory / '.claude.json').write_text('{}')
    return directory


def probe(directory, mode='', build='a' * 64):
    script = r'''
source "$TEST_C0" help >/dev/null
c0_set_build_identity "$TEST_BUILD"
printf '%s\n' "recipe=$C0_RECIPE_ID" "tools_recipe=$TOOLS_RECIPE_ID" \
    "workspace=$C0_WORKSPACE_ID" "instance=$C0_INSTANCE_ID" \
    "runtime=$C0_RUNTIME_IMAGE" "base=$C0_BASE_IMAGE" "mode=$C0_MODE_KEY"
'''
    result = subprocess.run(['/bin/bash', '-c', script], capture_output=True, text=True,
                            env=dict(os.environ, TEST_C0=str(directory / 'bin/c0'),
                                     TEST_BUILD=build, C0_MODE=mode, C0_SSH_AGENT='0',
                                     C0_SECCOMP_NOTIFY='0'), timeout=30)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return dict(line.split('=', 1) for line in result.stdout.splitlines())


class SharingIdentity(unittest.TestCase):
    def test_folder_mode_and_build_keys_have_the_required_sharing_boundaries(self):
        with tempfile.TemporaryDirectory(prefix='c0-sharing-keys-') as temporary:
            parent = Path(temporary).resolve()
            token = uuid.uuid4().hex
            first = checkout(parent, 'one', token)
            second = checkout(parent, 'two', token)
            a, b = probe(first), probe(second)
            for key in ('recipe', 'tools_recipe', 'runtime', 'base', 'mode'):
                self.assertEqual(a[key], b[key], key)
            self.assertNotEqual(a['workspace'], b['workspace'])
            self.assertNotEqual(a['instance'], b['instance'])
            self.assertEqual(a, probe(first))
            changed_build = probe(first, build='b' * 64)
            self.assertEqual(a['workspace'], changed_build['workspace'])
            for key in ('runtime', 'base', 'instance'):
                self.assertNotEqual(a[key], changed_build[key], key)
            dev = probe(first, mode='dev')
            self.assertEqual(a['recipe'], dev['recipe'])
            for key in ('runtime', 'base', 'workspace', 'instance', 'mode'):
                self.assertNotEqual(a[key], dev[key], key)

    def test_recipe_hash_ignores_checkout_paths_and_comments_but_tracks_inputs(self):
        with tempfile.TemporaryDirectory(prefix='c0-sharing-recipes-') as temporary:
            parent = Path(temporary).resolve()
            token = uuid.uuid4().hex
            first = checkout(parent, 'one', token)
            second = checkout(parent, 'another-folder', token)
            a = probe(first)
            for dockerfile in ('Dockerfile.base', 'Dockerfile.tools', 'Dockerfile.runtime'):
                path = second / 'docker' / dockerfile
                path.write_text(path.read_text() + '\n# irrelevant comment\n')
            self.assertEqual(a['recipe'], probe(second)['recipe'])
            runtime = second / 'docker/Dockerfile.runtime'
            runtime.write_text(runtime.read_text() + '\nLABEL c0dev.matrix_revision=2\n')
            self.assertNotEqual(a['recipe'], probe(second)['recipe'])
            self.assertEqual(a['tools_recipe'], probe(second)['tools_recipe'])
            install = first / 'docker/install-orca.sh'
            install.write_text(install.read_text() + '\n# changed copied bytes\n')
            self.assertNotEqual(a['recipe'], probe(first)['recipe'])

    def test_security_helper_bytes_change_both_recipes_with_unchanged_dockerfiles(self):
        with tempfile.TemporaryDirectory(prefix='c0-sharing-security-input-') as temporary:
            directory = checkout(Path(temporary).resolve(), 'checkout', uuid.uuid4().hex)
            dockerfiles = {name: (directory / 'docker' / name).read_bytes()
                           for name in ('Dockerfile.base', 'Dockerfile.tools', 'Dockerfile.runtime')}
            before = probe(directory)
            helper = directory / 'docker/c0-security.py'
            original = helper.read_bytes()
            helper.write_bytes(original + b'\n# synthetic changed security helper bytes\n')
            after = probe(directory)
            for key in ('recipe', 'tools_recipe'):
                self.assertNotEqual(before[key], after[key], key)
            self.assertEqual(before['workspace'], after['workspace'])
            for name, content in dockerfiles.items():
                self.assertEqual((directory / 'docker' / name).read_bytes(), content)
            helper.write_bytes(original)
            restored = probe(directory)
            for key in ('recipe', 'tools_recipe'):
                self.assertEqual(before[key], restored[key], key)


@unittest.skipUnless(os.environ.get('C0_SHARING_DOCKER') == '1', 'opt-in owned Docker sharing matrix')
class SharingDocker(unittest.TestCase):
    def setUp(self):
        self.docker = shutil.which('docker')
        self.docker_config = os.environ.get('DOCKER_CONFIG', str(Path.home() / '.docker'))
        self.assertTrue(self.docker)
        self.fixture_image = os.environ.get('C0_SHARING_DOCKER_IMAGE')
        if not self.fixture_image:
            self.skipTest('set C0_SHARING_DOCKER_IMAGE to a cached complete runtime')
        self.check(subprocess.run([self.docker, 'version'], capture_output=True, text=True))
        if self.call('image', 'inspect', self.fixture_image).returncode:
            self.skipTest('the runtime fixture image is not cached; refusing to pull')
        if self.call('image', 'inspect', 'alpine:latest').returncode:
            self.skipTest('alpine:latest is not cached; refusing to pull')
        self.temp = tempfile.TemporaryDirectory(prefix='c0-sharing-docker-')
        self.parent = Path(self.temp.name).resolve()
        self.token = uuid.uuid4().hex
        self.prefix = 'c0-sharing-' + self.token[:12]
        self.wrapper = self.parent / 'real-docker-bin'
        self.wrapper.mkdir()
        # Local-only fixture FROM references cannot be pulled from a registry.
        # Keep every production build/validation/publication operation, changing
        # only network refresh of this explicitly cached test input.
        (self.wrapper / 'docker').write_text('#!/usr/bin/env python3\nimport os,sys\n'
            'args=sys.argv[1:]\n'
            'if args and (args[0]=="build" or (args[0]=="compose" and "build" in args)):\n'
            ' args=[arg for arg in args if arg!="--pull"]\n'
            'os.execv(' + repr(self.docker) + ',[' + repr(self.docker) + ']+args)\n')
        (self.wrapper / 'docker').chmod(0o755)
        self.home = self.parent / 'home'
        self.home.mkdir()
        (self.home / '.gitconfig').write_text('[user]\n name=SharingTest\n')
        self.folders = [checkout(self.parent, name, self.token) for name in ('one', 'two')]
        self.owned_volumes = set()
        self.label = 'label=c0dev.test_run=' + self.token
        self.addCleanup(self.cleanup)
        for directory in self.folders:
            self.configure(directory)
            self.keys(directory)
        for directory, mode in ((self.folders[0], ''), (self.folders[1], ''),
                                (self.folders[0], 'dev')):
            workspace = probe(directory, mode=mode)['workspace']
            volume = workspace + '-home-overlays'
            self.assertNotEqual(self.call('volume', 'inspect', volume).returncode, 0)
            self.check(self.call('volume', 'create', '--label', 'c0dev.test_run=' + self.token,
                                 '--label', 'c0dev.workspace=' + workspace,
                                 '--label', 'c0dev.mode=' + ('dev' if mode else 'prod'), volume))
            self.owned_volumes.add(volume)
        self.term = 'c0-sharing-' + self.token[:8]
        source = subprocess.check_output(['infocmp', '-x', 'xterm-256color'], text=True).splitlines()
        for index, line in enumerate(source):
            if line and not line.startswith('#'):
                source[index] = self.term + '|portable sharing matrix terminal,'
                break
        self.term_source = self.parent / 'terminal.src'
        self.term_source.write_text('\n'.join(source) + '\n')
        self.terminfo = self.parent / 'terminfo'
        self.check(subprocess.run(['tic', '-x', '-o', str(self.terminfo), str(self.term_source)],
                                  capture_output=True, text=True))

    def check(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def call(self, *args, **kwargs):
        return subprocess.run([self.docker, *args], capture_output=True, text=True,
                              timeout=120, **kwargs)

    def configure(self, directory):
        (directory / 'docker/Dockerfile.base').write_text(
            'ARG BUN_VERSION\nFROM ' + self.fixture_image + ' AS base\n'
            'USER dev\nLABEL c0dev.test_run=' + self.token + '\n')
        (directory / 'docker/Dockerfile.runtime').write_text('FROM base\nUSER dev\n')
        script = directory / 'bin/c0'
        source = script.read_text()
        self.assertEqual(source.count('SHARED_TOOLS_VOLUME="c0dev-tools-shared-dev"'), 1,
                         'refusing to run without isolating the development tools store')
        self.assertEqual(source.count('SHARED_TOOLS_VOLUME="c0dev-tools-shared"'), 1,
                         'refusing to run without isolating the production tools store')
        source = source.replace('SHARED_TOOLS_VOLUME="c0dev-tools-shared-dev"',
                                'SHARED_TOOLS_VOLUME="' + self.prefix + '-tools-dev"')
        source = source.replace('SHARED_TOOLS_VOLUME="c0dev-tools-shared"',
                                'SHARED_TOOLS_VOLUME="' + self.prefix + '-tools-prod"')
        # Keep the actual build identities, image creation, base/runtime recipes,
        # validation and publication. Only tools installation uses a small owned
        # payload, and release resolution uses fixed valid test metadata.
        body = r'''build_tools_volume() {
    docker volume create --label c0dev.test_run=@TOKEN@ "$SHARED_TOOLS_VOLUME" >/dev/null
    docker run --rm --pull=never --network none -i -v "$SHARED_TOOLS_VOLUME:/tools" alpine:latest sh -ec '
        p=/tools/opt/$1
        mkdir -p "$p/.local/bin"
        printf "#!/bin/sh\nexit 0\n" >"$p/.local/bin/fnm"
        chmod +x "$p/.local/bin/fnm"
        cat >"$p/.c0dev-toolchain.json"
        cp "$p/.c0dev-toolchain.json" "$p/.local/toolchain-fixture.json"
        touch "$p/.c0dev-complete"
        chown -R 1000:1000 "$p"
    ' sharing-tools "$TOOLS_ID" <"$C0_BUILD_CONTEXT/c0-toolchain.json"
}'''.replace('@TOKEN@', self.token)
        source, count = re.subn(r'^build_tools_volume\(\) \{\n.*?^\}', lambda match: body,
                                source, count=1, flags=re.M | re.S)
        self.assertEqual(count, 1)
        script.write_text(source)
        resolver = directory / 'bin/c0-toolchain'
        original = directory / 'bin/c0-toolchain-real'
        resolver.rename(original)
        payload = controlled_manifest()
        resolver.write_text('#!/usr/bin/env python3\nimport os,sys\nfrom pathlib import Path\n'
                            'if sys.argv[1]=="--output": Path(sys.argv[2]).write_text(' + repr(payload) + ')\n'
                            'else: os.execv(' + repr(str(original)) + ',[' + repr(str(original)) + ']+sys.argv[1:])\n')
        resolver.chmod(0o755)
        public = directory / 'docker/docker-compose.public.yaml'
        contents = public.read_text().replace('    labels:\n', '    labels:\n      c0dev.test_run: ' + self.token + '\n', 1)
        contents = contents.replace('"${C0DEV_WEB_PORT:-3000}:3000"', '"127.0.0.1:${C0DEV_WEB_PORT:-3000}:3000"')
        contents += '\nnetworks:\n  default:\n    labels:\n      c0dev.test_run: ' + self.token + '\n'
        public.write_text(contents)
        self.owned_volumes.update((self.prefix + '-tools-prod', self.prefix + '-tools-dev'))

    def keys(self, directory):
        ssh = directory / 'auth/ssh'
        ssh.chmod(0o700)
        for name in ('id_ed25519', 'ssh_host_ed25519_key'):
            self.check(subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '',
                                      '-C', 'disposable-sharing-test', '-f', str(ssh / name)],
                                     capture_output=True, text=True))
        (ssh / 'authorized_keys').write_bytes((ssh / 'id_ed25519.pub').read_bytes())
        (ssh / 'authorized_keys').chmod(0o600)

    def env(self, mode=''):
        return dict(os.environ, HOME=str(self.home), DOCKER_CONFIG=self.docker_config,
                    PATH=str(self.wrapper) + os.pathsep + os.environ['PATH'], C0_MODE=mode,
                    C0_SSH_AGENT='0', C0_SECCOMP_NOTIFY='0',
                    C0_SECURITY='guest-admin', TERM='xterm-256color')

    def cli(self, directory, *args, mode=''):
        return subprocess.run(['/bin/bash', str(directory / 'bin/c0'), *args],
                              cwd=directory, env=self.env(mode), capture_output=True,
                              text=True, timeout=900)

    def artifact(self, directory, mode=''):
        identity = probe(directory, mode=mode)
        alias = 'c0dev-runtime-' + ('dev' if mode else 'prod') + ':recipe-' + identity['recipe']
        image = json.loads(self.check(self.call('image', 'inspect', alias)))[0]
        labels = image['Config']['Labels']
        expected_mode = 'dev' if mode else 'prod'
        self.assertEqual(labels['c0dev.mode'], expected_mode)
        self.assertNotIn('c0dev.workspace', labels)
        self.assertNotIn('c0dev.instance', labels)
        if 'com.docker.compose.project' in labels:
            self.assertEqual(labels['com.docker.compose.project'],
                             'c0dev-build-' + expected_mode + '-' + labels['c0dev.build'])
        self.assertEqual(labels['c0dev.recipe'], identity['recipe'])
        self.assertRegex(labels['c0dev.build'], r'^[0-9a-f]{64}$')
        self.assertRegex(labels['c0dev.tools_hash'], r'^[0-9a-f]{64}$')
        self.assertEqual(labels['c0dev.base_image'],
                         'c0dev-base-' + expected_mode + ':' + labels['c0dev.build'])
        self.assertEqual(labels['c0dev.tools_volume'], self.prefix + '-tools-' + expected_mode)
        base = json.loads(self.check(self.call('image', 'inspect', labels['c0dev.base_image'])))[0]
        self.assertEqual(base['Config']['Labels']['c0dev.mode'], expected_mode)
        self.assertEqual(base['Config']['Labels']['c0dev.build'], labels['c0dev.build'])
        return dict(image=image['Id'], base=base['Id'], build=labels['c0dev.build'],
                    tools=labels['c0dev.tools_hash'], volume=labels['c0dev.tools_volume'],
                    alias=alias, recipe=identity['recipe'])

    def active(self, directory, mode=''):
        workspace = probe(directory, mode=mode)['workspace']
        ids = self.check(self.call('ps', '-q', '--no-trunc', '--filter', self.label,
                                  '--filter', 'label=c0dev.workspace=' + workspace)).split()
        self.assertEqual(len(ids), 1, ids)
        return json.loads(self.check(self.call('inspect', ids[0])))[0]

    def assert_storage(self, container, artifact):
        self.assertEqual(container['Image'], artifact['image'])
        mounted = next(m for m in container['HostConfig']['Mounts'] if m['Target'] == '/tools/current')
        self.assertEqual(mounted['Source'], artifact['volume'])
        self.assertEqual(mounted['VolumeOptions']['Subpath'], 'opt/' + artifact['tools'])
        home = next(m for m in container['Mounts'] if m['Destination'] == '/run/c0/overlay-state')
        self.owned_volumes.add(home['Name'])
        return home['Name']

    def seed(self, container):
        self.check(self.call('exec', '-u', '1000', container['Id'], 'sh', '-ec',
                            'printf project-data >$HOME/projects/sharing-note; '
                            'printf cache-data >$HOME/.cache/sharing-note; '
                            'printf stage-data >$HOME/.local/sharing-note; '
                            'printf launcher-data >$HOME/bin/sharing-note'))

    def preserved(self, container):
        self.assertEqual(self.check(self.call('exec', '-u', '1000', container['Id'], 'sh', '-ec',
                          'cat $HOME/projects/sharing-note $HOME/.cache/sharing-note '
                          '$HOME/.local/sharing-note $HOME/bin/sharing-note')),
                         'project-datacache-datastage-datalauncher-data')

    def interactive(self, directory, command):
        environment = dict(self.env(), TERM=self.term, TERMINFO=str(self.terminfo))
        master, slave = pty.openpty()
        process = subprocess.Popen(['/bin/bash', str(directory / 'bin/c0'), command], cwd=directory,
                                   env=environment, stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        output = b''
        marker = b'\r\n__SHARING_DONE__\r\n'
        try:
            instructions = ("printf 'UID=%s TERM=%s\\n' \"$(id -u)\" \"$TERM\"; "
                            'infocmp "$TERM" >/dev/null; '
                            'repo=$(mktemp -d /tmp/c0-sharing-pager.XXXXXX); '
                            'git init --template= -q "$repo"; '
                            'git -C "$repo" -c user.name=Sharing -c user.email=sharing@example.invalid '
                            '-c commit.gpgsign=false -c core.hooksPath=/dev/null '
                            'commit --allow-empty -qm sharing-pager; '
                            "GIT_PAGER='less -FX' git -C \"$repo\" --paginate log --oneline -1; "
                            "rm -rf \"$repo\"; printf '\\n__SHARING_DONE__\\n'\n")
            os.write(master, instructions.encode())
            deadline = time.monotonic() + 40
            while marker not in output and time.monotonic() < deadline:
                if select.select([master], [], [], .2)[0]:
                    output += os.read(master, 65536)
            self.assertIn(marker, output, output.decode(errors='replace'))
            self.assertIn(('UID=1000 TERM=' + self.term).encode(), output)
            self.assertNotIn(b'terminal is not fully functional', output)
            self.assertNotIn(b'unknown terminal', output)
            deadline = time.monotonic() + 3
            while b'$ ' not in output.split(marker, 1)[1] and time.monotonic() < deadline:
                if select.select([master], [], [], .2)[0]: output += os.read(master, 65536)
            os.write(master, b'exit\n')
            deadline = time.monotonic() + 15
            while process.poll() is None and time.monotonic() < deadline:
                if select.select([master], [], [], .2)[0]:
                    try:
                        output += os.read(master, 65536)
                    except OSError:
                        break
            self.assertIsNotNone(process.poll(), output.decode(errors='replace'))
            self.assertEqual(process.returncode, 0, output.decode(errors='replace'))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)

    def cleanup(self):
        if not hasattr(self, 'token'): return
        for cid in self.call('ps', '-aq', '--filter', self.label).stdout.split():
            item = self.call('inspect', cid)
            if item.returncode == 0 and json.loads(item.stdout)[0]['Config']['Labels'].get('c0dev.test_run') == self.token:
                self.call('rm', '-f', cid)
        for volume in self.owned_volumes:
            item = self.call('volume', 'inspect', volume)
            if item.returncode == 0:
                data = json.loads(item.stdout)[0]
                if (data.get('Labels') or {}).get('c0dev.test_run') == self.token:
                    self.call('volume', 'rm', volume)
                elif (data.get('Labels') or {}).get('c0dev.workspace', '') in {
                        probe(folder, mode=mode)['workspace'] for folder in self.folders for mode in ('', 'dev')}:
                    self.call('volume', 'rm', volume)
        for network in self.call('network', 'ls', '-q', '--filter', self.label).stdout.split():
            self.call('network', 'rm', network)
        references = self.call('image', 'ls', '--filter', self.label,
                               '--format', '{{.Repository}}:{{.Tag}}').stdout.split()
        for reference in references:
            if '<none>' not in reference:
                self.call('image', 'rm', reference)
        # Failed publication or retagging can leave a uniquely labeled dangling
        # image. Verify ownership again and remove it without forcing references.
        for identity in set(self.call('image', 'ls', '-q', '--filter', self.label).stdout.split()):
            inspection = self.call('image', 'inspect', identity)
            if inspection.returncode == 0 and json.loads(inspection.stdout)[0]['Config']['Labels'].get('c0dev.test_run') == self.token:
                self.call('image', 'rm', identity)
        self.temp.cleanup()

    def assert_no_control_files(self):
        for folder in self.folders:
            self.assertFalse((folder / '.local/c0').exists())
            self.assertFalse(list((folder / 'docker').glob('.compose.*')))
            self.assertFalse(list((folder / 'docker').glob('.Dockerfile*')))
        for volume in self.owned_volumes:
            if self.call('volume', 'inspect', volume).returncode == 0 and '-tools-' in volume:
                self.check(self.call('run', '--rm', '--pull=never', '--network', 'none',
                                    '-v', volume + ':/tools:ro', 'alpine:latest', 'sh', '-ec',
                                    'test ! -d /tools/pins && test ! -d /tools/state'))

    def test_cross_folder_mode_and_hash_sharing_and_rebuild_lifecycle(self):
        first, second = self.folders
        self.check(self.cli(first, 'build'))
        a = self.artifact(first)
        self.check(self.cli(second, 'build'))
        b = self.artifact(second)
        if a != b:
            details = dict(first=a, second=b)
            for key, artifact in (('first_image', a), ('second_image', b)):
                details[key] = json.loads(self.check(self.call('image', 'inspect', artifact['image'])))[0]
            self.fail(json.dumps(details, indent=2))
        self.check(self.cli(first, 'start'))
        one = self.active(first)
        self.check(self.cli(second, 'start'))
        two = self.active(second)
        self.assertNotEqual(one['Id'], two['Id'])
        one_volume = self.assert_storage(one, a)
        two_volume = self.assert_storage(two, b)
        self.assertNotEqual(one_volume, two_volume)
        for directory, current in ((first, one), (second, two)):
            self.check(self.cli(directory, 'start'))
            self.assertEqual(self.active(directory)['Id'], current['Id'])
        self.seed(one)
        self.interactive(first, 'sh')
        self.interactive(first, 'ssh')
        self.check(self.cli(first, 'build', mode='dev'))
        dev = self.artifact(first, mode='dev')
        self.assertNotEqual(a['alias'], dev['alias'])
        self.assertNotEqual(a['volume'], dev['volume'])
        self.assertNotEqual(a['image'], dev['image'])
        self.assertNotEqual(a['base'], dev['base'])
        self.check(self.cli(first, 'start', mode='dev'))
        developer = self.active(first, mode='dev')
        self.assertNotIn(developer['Id'], (one['Id'], two['Id']))
        self.assert_storage(developer, dev)
        self.check(self.cli(first, 'stop', mode='dev'))
        # A real recipe change alters build identity and tools identity. The old
        # workspace runtime can still be stopped through Docker-derived lookup.
        tools = first / 'docker/Dockerfile.tools'
        tools.write_text(tools.read_text() + '\nLABEL c0dev.matrix_revision=2\n')
        self.check(self.cli(first, 'build'))
        updated = self.artifact(first)
        self.assertNotEqual(updated['build'], a['build'])
        self.assertNotEqual(updated['tools'], a['tools'])
        self.assertEqual(self.active(second)['Image'], two['Image'])
        self.check(self.cli(first, 'stop'))
        self.assertNotEqual(self.call('inspect', one['Id']).returncode, 0)
        self.check(self.cli(first, 'start'))
        fresh = self.active(first)
        self.assertNotEqual(fresh['Id'], one['Id'])
        self.assertEqual(self.assert_storage(fresh, updated), one_volume)
        self.preserved(fresh)
        self.interactive(first, 'sh')
        self.interactive(first, 'ssh')
        self.check(self.cli(first, 'restart'))
        restarted = self.active(first)
        self.assertNotEqual(restarted['Id'], fresh['Id'])
        self.assertEqual(self.assert_storage(restarted, updated), one_volume)
        self.preserved(restarted)
        self.check(self.cli(second, 'start'))
        self.assertEqual(self.active(second)['Id'], two['Id'])
        self.assert_no_control_files()


if __name__ == '__main__':
    unittest.main()
