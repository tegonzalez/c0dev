# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Real old-layout and fresh lifecycle checks, using only disposable resources.

C0_LIFECYCLE_SMOKE_IMAGE=<cached-runtime-image> python3 -m unittest discover \
    -s tests -p test_c0_lifecycle_compatibility_docker.py -v

The rebuild case runs the real runtime recipe with --pull and a disposable tools
fixture. No production credentials, public ports, or shared tools store mutations.
"""
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import socket
import subprocess
import sys
import time
import unittest
import uuid

from c0_fixture import Fixture, REPO

IMAGE = os.environ.get('C0_LIFECYCLE_SMOKE_IMAGE')


@unittest.skipUnless(IMAGE, 'opt-in: set C0_LIFECYCLE_SMOKE_IMAGE to a cached runtime image')
class LifecycleCompatibilityDocker(unittest.TestCase):
    def setUp(self):
        self.docker = shutil.which('docker')
        self.assertTrue(self.docker)
        for image in (IMAGE, 'alpine:latest'):
            if self.call('image', 'inspect', image).returncode:
                self.skipTest(image + ' is not cached; refusing to pull')
        self.f = Fixture()
        self.prefix = 'c0-lifecycle-smoke-' + uuid.uuid4().hex[:10]
        self.tools = self.prefix + '-tools'
        self.overlays = self.f.instance + '-home-overlays'
        self.network = self.prefix + '-network'
        self.owned_volumes = {self.tools, self.overlays}
        self.old = None
        self.runtime_image = self.f.instance + '-c0dev:latest'
        self.owned_images = set()
        self.removable = set()
        self.addCleanup(self.cleanup_resources)
        if (self.call('volume', 'inspect', self.overlays).returncode == 0
                or self.call('ps', '-aq', '--filter', 'label=c0dev.instance=' + self.f.instance).stdout.strip()):
            self.f.close()
            del self.f
            self.skipTest('disposable namespace already exists; refusing to touch it')
        self.assertNotEqual(self.call('image', 'inspect', self.runtime_image).returncode, 0)
        self.check(self.call('image', 'tag', IMAGE, self.runtime_image))
        self.owned_images.add(self.runtime_image)
        # Only the isolated checkout's resource namespaces and cached image change.
        c0 = self.f.checkout / 'bin/c0'
        source = c0.read_text()
        self.assertIn('SHARED_TOOLS_VOLUME="c0dev-tools-shared"', source)
        c0.write_text(source.replace('SHARED_TOOLS_VOLUME="c0dev-tools-shared"',
                                     'SHARED_TOOLS_VOLUME="' + self.tools + '"'))
        public = self.f.checkout / 'docker/docker-compose.public.yaml'
        public.write_text(public.read_text().replace('    labels:\n',
                          '    labels:\n      c0dev.test_run: ' + self.prefix + '\n', 1).replace('"${C0DEV_WEB_PORT:-3000}:3000"',
                          '"127.0.0.1:${C0DEV_WEB_PORT:-3000}:3000"').replace('  c0dev:\n',
                          '  c0dev:\n    image: ' + json.dumps(self.runtime_image) + '\n', 1)
                          + '\nnetworks:\n  default:\n    external: true\n    name: ' + self.network + '\n')
        self.call_log = self.f.root / 'cli-docker.jsonl'
        wrapper = self.f.root / 'real-docker-bin'
        wrapper.mkdir()
        (wrapper / 'docker').write_text('#!' + sys.executable + '\n'
            'import json, os, sys\n'
            'with open(' + repr(str(self.call_log)) + ', "a") as stream: stream.write(json.dumps(sys.argv[1:]) + "\\n")\n'
            'os.execv(' + repr(self.docker) + ', [' + repr(self.docker) + '] + sys.argv[1:])\n')
        (wrapper / 'docker').chmod(0o755)
        self.env = {key: value for key, value in self.f.env.items() if key in
                    ('HOME', 'TERM', 'LANG', 'LC_ALL', 'TMPDIR', 'C0_MODE', 'C0_SSH_AGENT', 'C0_SECCOMP_NOTIFY',
                     'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CERT_PATH', 'DOCKER_TLS_VERIFY')}
        self.env.update(PATH=str(wrapper) + os.pathsep + os.environ['PATH'], C0_SECURITY='permissive',
                        DOCKER_CONFIG=os.environ.get('DOCKER_CONFIG', str(Path.home() / '.docker')))
        self.env.pop('C0DEV_WEB_PORT', None)
        self.env.pop('C0DEV_SSH_PORT', None)
        self.check(self.call('network', 'create', '--label', 'c0dev.test_run=' + self.prefix, self.network))
        self.check(self.call('volume', 'create', '--label', 'c0dev.test_run=' + self.prefix, self.tools))
        self.check(self.call('volume', 'create', '--label', 'com.docker.compose.project=' + self.f.instance,
                            '--label', 'com.docker.compose.volume=home-overlays',
                            '--label', 'c0dev.test_run=' + self.prefix, self.overlays))
        self.check(self.call('run', '--rm', '--pull=never', '--network=none',
                            '-v', self.tools + ':/tools', 'alpine:latest', 'sh', '-ec',
                            'mkdir -p /tools/opt/' + self.f.tools + '/.local/bin; '
                            'printf "#!/bin/sh\\nexit 0\\n" >/tools/opt/' + self.f.tools + '/.local/bin/fnm; '
                            'chmod +x /tools/opt/' + self.f.tools + '/.local/bin/fnm; '
                            'touch /tools/opt/' + self.f.tools + '/.c0dev-complete; '
                            'chown -R 1000:1000 /tools/opt/' + self.f.tools))
        self.ssh_keys()
        self.term = 'c0-lifecycle-' + uuid.uuid4().hex[:8]
        lines = subprocess.check_output(['infocmp', '-x', 'xterm-256color'], text=True).splitlines()
        for index, line in enumerate(lines):
            if line and not line.startswith('#'):
                lines[index] = self.term + '|portable lifecycle terminal test,'
                break
        self.term_source = '\n'.join(lines) + '\n'
        host_source = self.f.root / 'terminal.src'
        host_source.write_text(self.term_source)
        self.host_terms = self.f.root / 'terminfo'
        subprocess.run(['tic', '-x', '-o', str(self.host_terms), str(host_source)], check=True, capture_output=True)

    def cleanup_resources(self):
        if not hasattr(self, 'f'):
            return
        # Each mutation is gated by the unique test label, never a c0 prefix.
        ids = self.call('ps', '-aq', '--filter', 'label=c0dev.test_run=' + self.prefix).stdout.split()
        for cid in ids:
            result = self.call('inspect', cid)
            if result.returncode == 0 and json.loads(result.stdout)[0]['Config']['Labels'].get('c0dev.test_run') == self.prefix:
                self.call('rm', '-f', cid)
        for volume in self.owned_volumes:
            result = self.call('volume', 'inspect', volume)
            if result.returncode == 0 and (json.loads(result.stdout)[0].get('Labels') or {}).get('c0dev.test_run') == self.prefix:
                self.call('volume', 'rm', volume)
        result = self.call('network', 'inspect', self.network)
        if result.returncode == 0 and (json.loads(result.stdout)[0].get('Labels') or {}).get('c0dev.test_run') == self.prefix:
            self.call('network', 'rm', self.network)
        for image in self.owned_images:
            self.call('image', 'rm', image)
        self.f.close()

    def assert_safe_lifecycle_calls(self):
        if not self.call_log.exists():
            return
        for line in self.call_log.read_text().splitlines():
            command = json.loads(line)
            self.assertNotIn(command[0], ('commit', 'export', 'load', 'import', 'rename', 'pause'))
            if command[0] == 'rm':
                self.assertFalse(set(command[1:]) - self.removable, command)
            self.assertNotIn('c0dev.image_lease', ' '.join(command))

    def call(self, *args, **kwargs):
        return subprocess.run([self.docker, *args], capture_output=True, text=True,
                              timeout=90, **kwargs)

    def check(self, result):
        diagnostics = result.stdout + result.stderr
        if result.returncode and hasattr(self, 'f'):
            ids = self.call('ps', '-aq', '--filter', 'label=c0dev.test_run=' + self.prefix).stdout.split()
            for cid in ids:
                inspection = self.call('inspect', cid)
                if inspection.returncode == 0:
                    value = json.loads(inspection.stdout)[0]
                    config = value['Config']
                    diagnostics += '\nCONTAINER ' + json.dumps(dict(
                        name=value['Name'], status=value['State']['Status'],
                        entrypoint=config.get('Entrypoint'), command=config.get('Cmd'),
                        user=config.get('User')))
                logs = self.call('logs', cid)
                diagnostics += '\nLOGS ' + cid + '\n' + (logs.stdout + logs.stderr)[-3000:]
        self.assertEqual(result.returncode, 0, diagnostics)
        return result.stdout.strip()

    def cli(self, *args, **kwargs):
        self.removable.update(self.call('ps', '-aq', '--no-trunc', '--filter',
                              'label=c0dev.test_run=' + self.prefix).stdout.split())
        result = subprocess.run(['/bin/bash', str(self.f.checkout / 'bin/c0'), *args],
                              env=self.env, cwd=self.f.checkout, capture_output=True,
                              text=True, timeout=600, **kwargs)
        self.assert_safe_lifecycle_calls()
        return result

    def ssh_keys(self):
        directory = self.f.checkout / 'auth/ssh'
        for name in ('id_ed25519', 'id_ed25519.pub', 'ssh_host_ed25519_key', 'authorized_keys'):
            (directory / name).unlink()
        directory.chmod(0o700)
        for key in ('id_ed25519', 'ssh_host_ed25519_key'):
            subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '',
                            '-C', 'disposable-c0-lifecycle-test', '-f', str(directory / key)],
                           check=True, capture_output=True)
        (directory / 'authorized_keys').write_bytes((directory / 'id_ed25519.pub').read_bytes())
        (directory / 'authorized_keys').chmod(0o600)
        (directory / 'sshd_config').write_text('''Port 2222
ListenAddress 0.0.0.0
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile /home/dev/.ssh/authorized_keys
HostKey /home/dev/.ssh/ssh_host_ed25519_key
PidFile /home/dev/.ssh/sshd.pid
UsePAM no
PermitTTY yes
''')

    def mount_local_overlay(self, cid):
        source = (REPO / 'bin/c0').read_text()
        names = ('c0_validate_overlay_row', 'c0_mount_home_overlay')
        functions = '\n'.join(re.search(r'^' + name + r'\(\) \{\n.*?^\}', source,
                                        re.M | re.S).group() for name in names)
        script = functions + '\nTOOLS_PREFIX=/tools/current\nTOOLS_ID="$1"\nc0_mount_home_overlay "$2" .local .local\n'
        result = subprocess.run(['/bin/bash', '-c', script, 'test-overlay', self.f.tools, cid],
                                capture_output=True, text=True, timeout=30)
        self.check(result)

    @staticmethod
    def free_host_ports():
        reserved = [socket.socket(), socket.socket()]
        try:
            for listener in reserved:
                listener.bind(('127.0.0.1', 0))
            return tuple(str(listener.getsockname()[1]) for listener in reserved)
        finally:
            for listener in reserved:
                listener.close()

    def old_guest(self, overlay=None):
        mounts = self.f.legacy_container()['mounts']
        overlay = overlay or self.overlays
        ssh_port, web_port = self.free_host_ports()
        args = ['run', '-d', '--pull=never', '--network', self.network,
                '--name', self.f.instance + '-c0dev-1', '--hostname', self.f.instance,
                '--user', '1000:1000', '--security-opt', 'no-new-privileges:true',
                '--cap-drop', 'ALL', '--cap-add', 'CHOWN', '--cap-add', 'DAC_OVERRIDE', '--cap-add', 'FOWNER',
                '--label', 'c0dev.instance=' + self.f.instance,
                '--label', 'c0dev.test_run=' + self.prefix,
                '--label', 'c0dev.tools_hash=' + self.f.tools,
                '--label', 'c0dev.tools_volume=' + self.tools,
                '--label', 'c0dev.security_mode=permissive',
                '--label', 'com.docker.compose.project=' + self.f.instance,
                '--label', 'com.docker.compose.service=c0dev',
                '--env', 'TOOLS_PREFIX=/tools/current',
                '-p', '127.0.0.1:' + ssh_port + ':2222',
                '-p', '127.0.0.1:' + web_port + ':3000']
        for mount in mounts:
            if mount['type'] == 'bind':
                value = 'type=bind,src=' + mount['source'] + ',dst=' + mount['target']
                if not mount['rw']:
                    value += ',readonly'
            elif mount['target'] == '/tools/current':
                value = ('type=volume,src=' + self.tools + ',dst=/tools/current,readonly,'
                         'volume-subpath=opt/' + self.f.tools)
            else:
                value = 'type=volume,src=' + overlay + ',dst=/run/c0/overlay-state'
            args += ['--mount', value]
        if overlay != self.overlays:
            args += ['--label', 'c0dev.home_overlays_volume=' + overlay]
        args += ['--entrypoint', '/bin/bash', IMAGE, '/usr/local/bin/docker-entrypoint.sh']
        self.old = self.check(self.call(*args))
        self.mount_local_overlay(self.old)
        self.seed_data(self.old)

    def seed_data(self, cid):
        self.old = cid
        self.check(self.call('exec', '-u', '1000', cid, 'sh', '-ec',
                            'printf overlay-data >/home/dev/.local/staged-note; '
                            'printf project-data >/home/dev/projects/lifecycle-note; '
                            'printf cache-data >/home/dev/.cache/lifecycle-note; '
                            'printf launcher-data >/home/dev/bin/lifecycle-note'))
        self.port = self.check(self.call('inspect', '--format',
                              '{{(index (index .NetworkSettings.Ports "2222/tcp") 0).HostPort}}', cid))
        self.wait_ssh()

    def wait_ssh(self):
        directory = self.f.checkout / 'auth/ssh'
        command = ['ssh', '-i', str(directory / 'id_ed25519'), '-p', self.port,
                   '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                   '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=1', 'dev@127.0.0.1', 'true']
        last = None
        for _ in range(30):
            last = subprocess.run(command, capture_output=True, text=True, timeout=3)
            if last.returncode == 0:
                return
            time.sleep(0.2)
        self.fail('SSH did not become ready: ' + last.stderr)

    def active(self):
        identities = self.check(self.call('ps', '-aq', '--no-trunc', '--filter',
                                         'label=c0dev.instance=' + self.f.instance)).split()
        self.assertTrue(identities, 'no retained or primary guest exists')
        values = json.loads(self.check(self.call('inspect', *identities)))
        primary = [value for value in values if value['Name'].lstrip('/') !=
                   'c0-recovery-' + self.f.instance + '-' + value['Id']]
        self.assertEqual(len(primary), 1, 'primary guest discovery is ambiguous')
        return primary[0]

    def preserved(self, cid):
        output = self.check(self.call('exec', '-u', '1000', cid, 'sh', '-ec',
                            'cat /home/dev/.local/staged-note /home/dev/projects/lifecycle-note '
                            '/home/dev/.cache/lifecycle-note /home/dev/bin/lifecycle-note'))
        self.assertEqual(output, 'overlay-dataproject-datacache-datalauncher-data')

    def interactive(self, command):
        env = dict(self.env, TERM=self.term, TERMINFO=str(self.host_terms))
        master, slave = pty.openpty()
        process = subprocess.Popen(['/bin/bash', str(self.f.checkout / 'bin/c0'), command],
                                   env=env, cwd=self.f.checkout, stdin=slave,
                                   stdout=slave, stderr=slave)
        os.close(slave)
        output = b''
        try:
            script = ('HISTFILE=/home/dev/.cache/lifecycle-bash-history; export HISTFILE; '
                      "printf 'UID=%s TERM=%s\\n' \"$(id -u)\" \"$TERM\"; "
                      'infocmp "$TERM" >/dev/null; '
                      'repo=$(mktemp -d /tmp/c0-pager.XXXXXX); '
                      'git init --template= -q "$repo"; '
                      'git -C "$repo" -c user.name=C0Test -c user.email=c0@example.invalid '
                      '-c commit.gpgsign=false -c core.hooksPath=/dev/null '
                      'commit --allow-empty -qm pager-test; '
                      "GIT_PAGER='less -FX' git -C \"$repo\" --paginate log --oneline -1; "
                      'rm -rf "$repo"; printf \'\\n__C0_PAGER_DONE__\\n\'\n')
            os.write(master, script.encode())
            deadline = time.monotonic() + 30
            marker = b'\r\n__C0_PAGER_DONE__\r\n'
            while time.monotonic() < deadline and marker not in output:
                if select.select([master], [], [], 0.2)[0]:
                    output += os.read(master, 65536)
            self.assertIn(marker, output, output.decode(errors='replace'))
            # Wait for readline after the pager; otherwise an early byte can be
            # consumed while less restores its terminal settings.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and b'$ ' not in output.split(marker, 1)[1]:
                if select.select([master], [], [], 0.2)[0]:
                    output += os.read(master, 65536)
            os.write(master, b'exit\n')
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and process.poll() is None:
                if select.select([master], [], [], 0.2)[0]:
                    try:
                        output += os.read(master, 65536)
                    except OSError:
                        break
            self.assertIsNotNone(process.poll(), output.decode(errors='replace'))
            self.assertEqual(process.returncode, 0, output.decode(errors='replace'))
            text = output.decode(errors='replace')
            self.assertIn('UID=1000 TERM=' + self.term, text)
            self.assertNotIn('terminal is not fully functional', text)
            self.assertNotIn('unknown terminal', text)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
        self.assert_safe_lifecycle_calls()

    def checkpoint(self, cid):
        value = json.loads(self.check(self.call('inspect', cid)))[0]
        return {key: value[key] for key in ('Id', 'Name', 'Image', 'Mounts', 'HostConfig')}

    def exercise_fresh_cycles(self, cid, expected_image=None, expected_overlay=None):
        # Starting an already-running instance is idempotent. A stop/start must
        # create a new container from the currently published image.
        self.check(self.cli('start'))
        self.assertEqual(self.active()['Id'], cid)
        self.preserved(cid)
        self.interactive('sh')
        self.interactive('ssh')
        previous = cid
        for iteration in range(3):
            if iteration == 0:
                self.check(self.cli('stop'))
                self.assertNotEqual(self.call('inspect', previous).returncode, 0)
                self.check(self.cli('start'))
            else:
                self.check(self.cli('restart'))
            current = self.active()
            self.assertNotEqual(current['Id'], previous)
            self.assertNotEqual(self.call('inspect', previous).returncode, 0)
            if expected_image:
                self.assertEqual(current['Image'], expected_image)
                self.assertEqual(current['Config']['Labels']['c0dev.tools_hash'], self.rebuilt_tools)
                tools_mount = next(mount for mount in current['HostConfig']['Mounts']
                                   if mount['Target'] == '/tools/current')
                self.assertEqual(tools_mount['VolumeOptions']['Subpath'], 'opt/' + self.rebuilt_tools)
            self.preserved(current['Id'])
            if expected_overlay:
                state_mount = next(mount for mount in current['Mounts']
                                   if mount['Destination'] == '/run/c0/overlay-state')
                self.assertEqual(state_mount['Name'], expected_overlay)
                self.assertEqual(self.check(self.call('exec', '-u', '1000', current['Id'],
                                 'cat', '/home/dev/bin/legacy-launcher-note')), 'volume-launcher-data')
            self.port = self.check(self.call('inspect', '--format',
                '{{(index (index .NetworkSettings.Ports "2222/tcp") 0).HostPort}}', current['Id']))
            self.wait_ssh()
            if iteration == 0:
                self.check(self.call('exec', current['Id'], 'sh', '-ec',
                                    'printf second-round >/home/dev/projects/later-note'))
            else:
                self.assertEqual(self.check(self.call('exec', current['Id'], 'cat',
                                                       '/home/dev/projects/later-note')), 'second-round')
            previous = current['Id']
        self.interactive('sh')
        self.interactive('ssh')
        return previous

    def rebuild_runtime(self, revision="rebuilt"):
        # Exercise real build/publication/pinning with an owned tools fixture;
        # release lookup and tool installation are covered by their own suites.
        self.rebuilt_tools = hashlib.sha256((self.f.tools + ':' + revision).encode()).hexdigest()
        self.check(self.call('run', '--rm', '--pull=never', '--network=none',
                            '-v', self.tools + ':/tools', 'alpine:latest', 'sh', '-ec',
                            'cp -a /tools/opt/' + self.f.tools + ' /tools/opt/' + self.rebuilt_tools))
        path = self.f.checkout / 'bin/c0'
        source = path.read_text()
        replacements = {
            'c0_resolve_toolchain': """c0_resolve_toolchain() {
    TOOLS_BUILD_ID="@TOOLS@"
    set_tools_id "$TOOLS_BUILD_ID"
    C0_TOOLCHAIN_BUILD_ARGS=(--build-arg BUN_VERSION=1.4.4)
    printf '{}\n' >"$C0_BUILD_CONTEXT/c0-toolchain.json"
}""".replace('@TOOLS@', self.rebuilt_tools),
            'build_tools_volume': 'build_tools_volume() {\n    return 0\n}',
        }
        for name, body in replacements.items():
            source, count = re.subn(r'^' + name + r'\(\) \{\n.*?^\}', lambda match: body,
                                    source, count=1, flags=re.M | re.S)
            self.assertEqual(count, 1)
        path.write_text(source)
        runtime = self.f.checkout / 'docker/Dockerfile.runtime'
        runtime.write_text(runtime.read_text() + '\nLABEL c0dev.test_run=' + self.prefix +
                           '\nLABEL c0dev.lifecycle_build=' + revision + '\n')
        previous = self.check(self.call('image', 'inspect', '--format', '{{.Id}}', self.runtime_image))
        self.check(self.cli('build'))
        current = self.check(self.call('image', 'inspect', '--format', '{{.Id}}', self.runtime_image))
        self.assertNotEqual(current, previous)
        self.assertEqual(self.check(self.call('image', 'inspect', '--format',
                          '{{index .Config.Labels "c0dev.lifecycle_build"}}', self.runtime_image)), revision)
        return current

    def recovery_artifact(self):
        # Existing historical containers remain data artifacts, never primaries.
        cid = self.check(self.call('create', '--pull=never', '--network=none',
                         '--label', 'c0dev.instance=' + self.f.instance,
                         '--label', 'c0dev.test_run=' + self.prefix,
                         '--label', 'com.docker.compose.project=' + self.f.instance,
                         '--label', 'com.docker.compose.service=c0dev',
                         IMAGE, 'true'))
        self.check(self.call('rename', cid, 'c0-recovery-' + self.f.instance + '-' + cid))
        return cid

    def test_old_layout_stop_start_creates_current_runtime_and_preserves_mounted_data(self):
        self.old_guest()
        self.exercise_fresh_cycles(self.old)

    def test_noncanonical_generation_rebuild_stop_start_preserves_same_volume_and_backup(self):
        generation = uuid.uuid4().hex
        volume = self.f.instance + '-home-overlays-' + generation
        self.check(self.call('volume', 'create', '--label', 'c0dev.instance=' + self.f.instance,
                            '--label', 'c0dev.overlay_generation=' + generation,
                            '--label', 'c0dev.overlay_source=' + self.overlays,
                            '--label', 'c0dev.test_run=' + self.prefix, volume))
        self.owned_volumes.add(volume)
        self.check(self.call('run', '--rm', '--pull=never', '--network=none',
                            '-v', volume + ':/state', 'alpine:latest', 'sh', '-ec',
                            'mkdir -p /state/launcher/upper; '
                            'printf volume-launcher-data >/state/launcher/upper/legacy-launcher-note; '
                            'chown -R 1000:1000 /state/launcher'))
        self.check(self.call('run', '--rm', '--pull=never', '--network=none',
                            '-v', self.overlays + ':/state', 'alpine:latest', 'sh', '-ec',
                            'printf canonical-untouched >/state/canonical-only'))
        backup = self.recovery_artifact()
        before = self.check(self.call('inspect', backup))
        self.old_guest(volume)
        rebuilt = self.rebuild_runtime()
        self.exercise_fresh_cycles(self.old, expected_image=rebuilt, expected_overlay=volume)
        # A later build must not reset storage selection once stop has saved it.
        selection = self.f.checkout / '.local/c0' / (self.f.instance + '.home-overlays-volume')
        selected = selection.read_bytes()
        rebuilt_again = self.rebuild_runtime('rebuilt-again')
        self.assertEqual(selection.read_bytes(), selected)
        previous = self.active()['Id']
        self.check(self.cli('stop'))
        self.assertNotEqual(self.call('inspect', previous).returncode, 0)
        self.check(self.cli('start'))
        current = self.active()
        self.assertNotEqual(current['Id'], previous)
        self.assertEqual(current['Image'], rebuilt_again)
        self.assertEqual(current['Config']['Labels']['c0dev.tools_hash'], self.rebuilt_tools)
        state_mount = next(mount for mount in current['Mounts']
                           if mount['Destination'] == '/run/c0/overlay-state')
        self.assertEqual(state_mount['Name'], volume)
        self.preserved(current['Id'])
        self.assertEqual(self.check(self.call('exec', '-u', '1000', current['Id'],
                         'cat', '/home/dev/bin/legacy-launcher-note')), 'volume-launcher-data')
        self.port = self.check(self.call('inspect', '--format',
            '{{(index (index .NetworkSettings.Ports "2222/tcp") 0).HostPort}}', current['Id']))
        self.wait_ssh()
        self.interactive('sh')
        self.interactive('ssh')
        self.assertEqual(self.check(self.call('inspect', backup)), before)
        self.assertEqual(self.check(self.call('run', '--rm', '--pull=never', '--network=none',
                         '-v', self.overlays + ':/state:ro', 'alpine:latest', 'cat',
                         '/state/canonical-only')), 'canonical-untouched')
        self.assertEqual(self.check(self.call('run', '--rm', '--pull=never', '--network=none',
                         '-v', self.overlays + ':/state:ro', 'alpine:latest', 'sh', '-ec',
                         'ls -A /state')), 'canonical-only')

    def test_rebuild_then_stop_start_uses_new_image_and_preserves_mounted_data(self):
        ssh_port, web_port = self.free_host_ports()
        self.env['C0DEV_WEB_PORT'] = web_port
        self.env['C0DEV_SSH_PORT'] = ssh_port
        self.check(self.cli('start'))
        candidate = self.active()
        expected_image = self.check(self.call('image', 'inspect', '--format', '{{.Id}}', IMAGE))
        self.assertEqual(candidate['Image'], expected_image)
        self.port = self.check(self.call('inspect', '--format',
            '{{(index (index .NetworkSettings.Ports "2222/tcp") 0).HostPort}}', candidate['Id']))
        self.wait_ssh()
        self.seed_data(candidate['Id'])
        mounts = {mount['Destination']: mount for mount in candidate['Mounts']}
        self.assertFalse(mounts['/run/c0/host-bin']['RW'])
        self.assertFalse(mounts['/home/dev/.gitconfig']['RW'])
        backup = self.recovery_artifact()
        backup_before = self.check(self.call('inspect', backup))
        rebuilt = self.rebuild_runtime()
        self.exercise_fresh_cycles(candidate['Id'], expected_image=rebuilt)
        self.assertEqual(self.check(self.call('inspect', backup)), backup_before)

    def test_backup_only_does_not_block_fresh_start_or_mutate_data(self):
        backup = self.recovery_artifact()
        before = self.check(self.call('inspect', backup))
        result = self.cli('start')
        self.check(result)
        self.assertEqual(self.check(self.call('inspect', backup)), before)
        self.assertNotEqual(self.active()['Id'], backup)
        self.assertIn(backup, self.call('ps', '-aq', '--no-trunc', '--filter',
                                      'label=c0dev.instance=' + self.f.instance).stdout.split())


if __name__ == '__main__':
    unittest.main()
