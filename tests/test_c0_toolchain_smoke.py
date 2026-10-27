# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Opt-in fresh-overlay test of a real built runtime and tools snapshot.

Set C0_TOOLCHAIN_SMOKE_IMAGE, C0_TOOLCHAIN_SMOKE_VOLUME, and
C0_TOOLCHAIN_SMOKE_ID. No image pulls, network, credentials, or live overlays.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid

REPO = Path(__file__).resolve().parents[1]
SETTINGS = tuple(os.environ.get('C0_TOOLCHAIN_SMOKE_' + key)
                 for key in ('IMAGE', 'VOLUME', 'ID'))


@unittest.skipUnless(all(SETTINGS), 'opt-in: set C0_TOOLCHAIN_SMOKE_IMAGE/VOLUME/ID')
class ToolchainSmoke(unittest.TestCase):
    def test_fresh_overlay_login_versions_and_trust(self):
        image, tools_volume, tools_id = SETTINGS
        docker = shutil.which('docker')
        self.assertTrue(docker)

        def call(*args):
            return subprocess.run([docker, *args], capture_output=True, text=True, timeout=90)

        def check(result):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout.strip()

        check(call('image', 'inspect', image))
        check(call('image', 'inspect', 'alpine:latest'))
        check(call('volume', 'inspect', tools_volume))
        name = 'c0-toolchain-smoke-' + uuid.uuid4().hex[:12]
        overlays = name + '-overlays'
        cid = None
        try:
            check(call('volume', 'create', overlays))
            cid = check(call(
                'run', '-d', '--pull=never', '--network=none', '--name', name,
                '--security-opt', 'no-new-privileges:true', '--user', '1000:1000',
                '--env', 'TOOLS_PREFIX=/tools/current',
                '--env', 'SEMGREP_ENABLE_VERSION_CHECK=0',
                '--env', 'SEMGREP_SEND_METRICS=off',
                '--mount', f'type=volume,src={tools_volume},dst=/tools/current,readonly,volume-subpath=opt/{tools_id}',
                '--mount', f'type=volume,src={overlays},dst=/run/c0/overlay-state',
                '--mount', f'type=bind,src={REPO}/bin,dst=/run/c0/host-bin,readonly',
                '--mount', f'type=bind,src={REPO}/docker/home-overlays.conf,dst=/etc/c0dev/home-overlays.conf,readonly',
                '--entrypoint', '/bin/sleep', image, '600'))
            source = (REPO / 'bin/c0').read_text()
            names = ('c0_validate_overlay_row', 'c0_container_has_overlay_state_volume',
                     'c0_mount_home_overlay', 'c0_setup_home_overlays')
            functions = '\n'.join(re.search(r'^' + n + r'\(\) \{\n.*?^\}', source,
                                             re.M | re.S).group() for n in names)
            with tempfile.TemporaryDirectory(prefix='c0-toolchain-smoke-') as tmp:
                script = Path(tmp) / 'mount.sh'
                script.write_text('set -e\n' + functions + '\n'
                                  'TOOLS_PREFIX=/tools/current\n'
                                  'TOOLS_ID="$1"\n'
                                  'HOME_OVERLAYS_FILE="$2"\n'
                                  'c0_setup_home_overlays "$3"\n')
                result = subprocess.run(['/bin/bash', str(script), tools_id,
                                         str(REPO / 'docker/home-overlays.conf'), cid],
                                        capture_output=True, text=True, timeout=90)
                check(result)
            # Login must honor the immutable manifest despite old selectors.
            check(call('exec', '-u', '1000', cid, '/bin/sh', '-ec',
                       'ln -sfn /usr/bin/python3 /home/dev/.local/bin/python; '
                       'ln -sfn /usr/bin/python3 /home/dev/.local/bin/python3; '
                       'ln -sfn /missing-old-node /home/dev/.local/share/fnm/aliases/default; '
                       'for p in /home/dev/.local/bin/uv /home/dev/.local/bin/bun /home/dev/.local/share/fnm/fnm '
                       '/home/dev/.local/bin/semgrep /home/dev/.local/bin/pip; do '
                       'printf \'#!/bin/sh\\nexit 91\\n\' > "$p"; chmod +x "$p"; done'))
            check(call('exec', '-u', '1000', cid, '/usr/bin/python3', '-I', '-c', r'''
import json, os
from pathlib import Path
version = json.loads((Path(os.environ['TOOLS_PREFIX']) / '.local/share/c0/toolchain.json').read_text())['versions']['node']
root = Path.home() / f'.local/share/fnm/node-versions/v{version}/installation/lib/node_modules'
for package, command in (('npm', 'npm'), ('pnpm', 'pnpm')):
    entries = json.loads((root / package / 'package.json').read_text())['bin']
    entry = entries[command] if isinstance(entries, dict) else entries
    target = root / package / entry
    assert target.is_file(), target
    target.write_text('#!/bin/sh\nexit 92\n')
    target.chmod(0o755)
'''))
            output = check(call('exec', '-u', '1000', cid, '/bin/bash', '-lc', r'''
set -e
test "$(id -u)" = 1000
test -f "$TOOLS_PREFIX/.c0dev-complete"
python3 - <<'PY'
import importlib.metadata, json, os, platform, ssl, subprocess
from pathlib import Path
manifest = json.loads((Path(os.environ['TOOLS_PREFIX']) / '.local/share/c0/toolchain.json').read_text())
expected = manifest['versions']
def output(*args):
    return subprocess.check_output(args, text=True).strip()
assert expected['node'].startswith('22.')
assert expected['python'].startswith('3.15.')
assert platform.python_version() == expected['python']
assert output('python', '-c', 'import platform; print(platform.python_version())') == expected['python']
assert output('fnm', '--version') == 'fnm ' + expected['fnm']
assert output('semgrep', '--version').splitlines()[-1] == expected['semgrep']
assert output('node', '--version') == 'v' + expected['node']
assert output('npm', '--version') == expected['npm']
assert output('pnpm', '--version') == expected['pnpm']
assert output('uv', '--version').split()[1] == expected['uv']
assert output('bun', '--version') == expected['bun']
assert Path.home().joinpath('.local/share/fnm/aliases/default').readlink() == Path('/missing-old-node')
def release(value):
    return tuple(map(int, value.split('.')))
context = ssl.create_default_context()
names = {value for cert in context.get_ca_certs() for row in cert['subject']
         for key, value in row if key == 'commonName'}
assert 'emSign ECC Root CA - G3' not in names, names
assert 'AAA Certificate Services' not in names, names
import pip._vendor.certifi
assert importlib.metadata.version('pip') == expected['pip']
assert output('pip', '--version').split()[1] == expected['pip']
assert str(Path(os.environ['TOOLS_PREFIX'])) in output('pip', '--version')
bundles = [Path(pip._vendor.certifi.where()),
           Path.home() / '.local/share/uv/tools/semgrep/lib/python3.15/site-packages/certifi/cacert.pem']
for bundle in bundles:
    roots = ssl.create_default_context(cafile=str(bundle)).get_ca_certs()
    subjects = {value for cert in roots for row in cert['subject']
                for key, value in row if key == 'commonName'}
    assert 'emSign ECC Root CA - G3' not in subjects, bundle
import ensurepip, zipfile
assert release(ensurepip.version()) >= (26, 2, 2)
wheel = next((Path(ensurepip.__file__).parent / '_bundled').glob('pip-' + ensurepip.version() + '-*.whl'))
with zipfile.ZipFile(wheel) as archive:
    pem = archive.read('pip/_vendor/certifi/cacert.pem').decode()
roots = ssl.create_default_context(cadata=pem).get_ca_certs()
assert all(value != 'emSign ECC Root CA - G3' for cert in roots
           for row in cert['subject'] for key, value in row if key == 'commonName')
assert os.environ['SSL_CERT_FILE'] == '/etc/ssl/certs/ca-certificates.crt'
assert os.environ['REQUESTS_CA_BUNDLE'] == '/etc/ssl/certs/ca-certificates.crt'
assert os.environ['UV_SYSTEM_CERTS'] == 'true'
print(json.dumps({'uid': os.getuid(), 'trusted_roots': len(names), 'python': platform.python_version()}))
PY
'''))
            facts = json.loads(output.splitlines()[-1])
            self.assertEqual(facts['uid'], 1000)
            self.assertGreater(facts['trusted_roots'], 50)
        finally:
            call('rm', '-f', cid or name)
            call('volume', 'rm', overlays)


if __name__ == '__main__':
    unittest.main()
