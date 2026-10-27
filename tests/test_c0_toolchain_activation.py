# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Select built defaults despite persistent old home overrides, without installs."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class ToolchainActivation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='c0 toolchain activation ')
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.tools = self.root / 'tools'
        (self.home / 'bin').mkdir(parents=True)
        shutil.copy2(REPO / 'bin/activate', self.home / 'bin/activate')
        self.local = self.home / '.local'
        self.bin = self.local / 'bin'
        self.bin.mkdir(parents=True)
        for name in ('python', 'python3'):
            self.executable(self.bin / name, 'echo legacy-python\n')
        for name in ('pip', 'pip3'):
            self.executable(self.bin / name, 'echo legacy-pip\n')
        for name in ('uv', 'uvx', 'semgrep'):
            self.executable(self.bin / name, f'echo legacy-{name}\n')
        self.python = self.local / 'share/uv/python/cpython-3.15.2-linux-aarch64-gnu/bin/python3.15'
        self.executable(self.python, '''if [ "$1" = -m ] && [ "$2" = pip ]; then
    echo managed-pip:3.15.2
else
    echo managed-python:3.15.2
fi
''')
        (self.tools / '.local/bin').mkdir(parents=True)
        for name in ('python', 'python3'):
            (self.tools / '.local/bin' / name).symlink_to(self.python)
        self.immutable_python = self.tools / self.python.relative_to(self.home)
        self.executable(self.immutable_python, '''test "$1" != -I || shift
if [ "$1" = -m ] && [ "$2" = pip ]; then
    echo snapshot-pip:26.2.3
else
    echo snapshot-python:3.15.2
fi
''')
        for name in ('uv', 'uvx'):
            self.executable(self.tools / '.local/bin' / name, f'''if [ "$1" = tool ] && [ "$2" = run ]; then
    echo snapshot-uvx:0.13.6
else
    echo snapshot-{name}:0.13.6
fi
''')
        semgrep = self.tools / '.local/share/uv/tools/semgrep/bin'
        self.executable(semgrep / 'python', 'exec /bin/sh "$@"\n')
        self.executable(semgrep / 'semgrep', 'echo snapshot-semgrep:1.182.2\n')
        self.executable(self.local / 'share/uv/tools/semgrep/bin/semgrep', 'echo legacy-semgrep-package\n')
        self.manifest = self.tools / '.local/share/c0/toolchain.json'
        self.manifest.parent.mkdir(parents=True)
        self.write_manifest()
        fnm_root = self.local / 'share/fnm'
        old_node = fnm_root / 'node-versions/v22.23.4/installation/bin/node'
        new_node = fnm_root / 'node-versions/v22.23.5/installation/bin/node'
        for path, version in ((old_node, '22.23.4'), (new_node, '22.23.5')):
            self.executable(path, f'''if [ "$#" -gt 0 ]; then
    exec /bin/sh "$@"
fi
echo v{version}
''')
        immutable_installation = self.tools / '.local/share/fnm/node-versions/v22.23.5/installation'
        self.executable(immutable_installation / 'bin/node', 'echo snapshot-node\n')
        for name, relative, version in (
                ('npm', 'npm/bin/npm-cli.js', '12.2.2'),
                ('npx', 'npm/bin/npx-cli.js', '12.2.2'),
                ('pnpm', 'pnpm/bin/pnpm.cjs', '12.15.1'),
                ('pnpx', 'pnpm/bin/pnpx.cjs', '12.15.1')):
            self.executable(immutable_installation / 'lib/node_modules' / relative,
                            f'echo snapshot-{name}:{version}\n')
            self.executable(new_node.parent.parent / 'lib/node_modules' / relative,
                            f'echo legacy-{name}-same-node-patch\n')
            self.executable(new_node.parent / name, f'echo legacy-{name}-same-node-patch\n')
        for package, entries in (
                ('npm', dict(npm='bin/npm-cli.js', npx='bin/npx-cli.js')),
                ('pnpm', dict(pnpm='bin/pnpm.cjs', pnpx='bin/pnpx.cjs'))):
            (immutable_installation / 'lib/node_modules' / package / 'package.json').write_text(
                json.dumps({'bin': entries}))
        self.alias = fnm_root / 'aliases/default'
        self.alias.parent.mkdir()
        self.alias.symlink_to(old_node.parent.parent)
        (self.home / 'fnm-current').symlink_to(old_node.parent)
        self.executable(fnm_root / 'fnm', '''echo legacy-fnm >> "$HOME/fnm-calls"
test "$1" = env || exit 90
printf 'export PATH="%s/fnm-current:$PATH"\\n' "$HOME"
''')
        self.executable(self.tools / '.local/share/fnm/fnm', '''printf '%s\\n' "$*" >> "$HOME/fnm-calls"
case "$1" in
    env)
        printf 'export PATH="%s/fnm-current:$PATH"\\n' "$HOME"
        printf 'export FNM_DIR="%s/.local/share/fnm"\\n' "$HOME"
        ;;
    use)
        test -z "$FNM_INSTALL_IF_MISSING" || test "$FNM_INSTALL_IF_MISSING" = false || exit 13
        target="$FNM_DIR/node-versions/v$2/installation/bin"
        test -x "$target/node" || exit 14
        rm "$HOME/fnm-current"
        ln -s "$target" "$HOME/fnm-current"
        ;;
    --version) echo 'snapshot-fnm:1.39.1' ;;
    *) exit 15 ;;
esac
''')
        self.env = dict(os.environ, HOME=str(self.home), TOOLS_PREFIX=str(self.tools),
                        PATH='/usr/bin:/bin:/usr/sbin:/sbin')
        for name in ('FNM_DIR', 'PYTHONPATH', 'PYTHONHOME'):
            self.env.pop(name, None)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def executable(path, contents):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\n' + contents)
        path.chmod(0o755)

    def write_manifest(self, node='22.23.5', python='3.15.2'):
        self.manifest.write_text(json.dumps({'schema': 1, 'versions': {
            'node': node, 'python': python, 'uv': '0.13.6', 'fnm': '1.39.1',
            'npm': '12.2.2', 'pnpm': '12.15.1', 'pip': '26.2.3', 'semgrep': '1.182.2'}}))

    def source(self, shell, commands='python; python3; pip; pip3; node'):
        return subprocess.run([shell, '-c', '. "$HOME/bin/activate" || exit $?; ' + commands],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def test_snapshot_defaults_override_old_selectors_without_rewriting_them(self):
        for shell in ('/bin/sh', '/bin/bash'):
            with self.subTest(shell=shell):
                result = self.source(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), [
                    'managed-python:3.15.2', 'managed-python:3.15.2',
                    'snapshot-pip:26.2.3', 'snapshot-pip:26.2.3', 'v22.23.5'])
                self.assertIn('legacy-python', (self.bin / 'python').read_text())
                self.assertTrue(str(self.alias.readlink()).endswith('v22.23.4/installation'))
                self.assertIn('use 22.23.5', (self.home / 'fnm-calls').read_text())
                caches = list((self.home / '.cache/c0/toolchain-defaults').glob('*/bin'))
                self.assertEqual(len(caches), 1)
                self.assertEqual(stat.S_IMODE(caches[0].stat().st_mode), 0o700)

    def test_stable_pip_minor_and_post_releases_are_accepted(self):
        for release in ('26.3', '26.2.2.post1'):
            with self.subTest(release=release):
                document = json.loads(self.manifest.read_text())
                document['versions']['pip'] = release
                self.manifest.write_text(json.dumps(document))
                result = self.source('/bin/sh', 'true')
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_minor_python_alias_uses_snapshot_patch_despite_old_upper_alias(self):
        alias_name = 'cpython-3.15-linux-aarch64-gnu'
        old = self.local / 'share/uv/python/cpython-3.15.1-linux-aarch64-gnu/bin/python3.15'
        self.executable(old, 'echo legacy-minor-alias\n')
        (self.local / 'share/uv/python' / alias_name).symlink_to(old.parent.parent)
        snapshot_alias = self.tools / '.local/share/uv/python' / alias_name
        snapshot_alias.symlink_to(self.python.parent.parent)
        for name in ('python', 'python3'):
            launcher = self.tools / '.local/bin' / name
            launcher.unlink()
            launcher.symlink_to(self.local / 'share/uv/python' / alias_name / 'bin/python3.15')
        result = self.source('/bin/sh', 'python; python3')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['managed-python:3.15.2'] * 2)
        self.assertEqual((self.local / 'share/uv/python' / alias_name).readlink(), old.parent.parent)

    def test_manager_updates_bypass_same_node_upper_and_generic_overrides(self):
        for shell in ('/bin/sh', '/bin/bash'):
            with self.subTest(shell=shell):
                result = self.source(shell, 'uv; uvx; fnm --version; npm; npx; pnpm; pnpx; semgrep')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), [
                    'snapshot-uv:0.13.6', 'snapshot-uvx:0.13.6', 'snapshot-fnm:1.39.1',
                    'snapshot-npm:12.2.2', 'snapshot-npx:12.2.2', 'snapshot-pnpm:12.15.1',
                    'snapshot-pnpx:12.15.1', 'snapshot-semgrep:1.182.2'])
                self.assertNotIn('legacy-fnm', (self.home / 'fnm-calls').read_text())
                self.assertIn('legacy-uv', (self.bin / 'uv').read_text())

    def test_fnm_use_can_change_node_after_default_activation(self):
        result = self.source('/bin/sh', 'fnm use 22.23.4 >/dev/null; node; npm')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['v22.23.4', 'snapshot-npm:12.2.2'])

    def test_package_metadata_selects_mjs_and_native_entry_points(self):
        package = self.tools / '.local/share/fnm/node-versions/v22.23.5/installation/lib/node_modules/pnpm'
        self.executable(package / 'bin/pnpm.mjs', 'echo snapshot-pnpm-mjs\n')
        self.executable(package / 'native-pnpx', 'echo snapshot-pnpx-native\n')
        (package / 'package.json').write_text(json.dumps({'bin': {
            'pnpm': 'bin/pnpm.mjs', 'pnpx': 'native-pnpx'}}))
        result = self.source('/bin/sh', 'pnpm; pnpx')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['snapshot-pnpm-mjs', 'snapshot-pnpx-native'])

    def test_package_entry_point_cannot_escape_immutable_package(self):
        package = self.tools / '.local/share/fnm/node-versions/v22.23.5/installation/lib/node_modules/pnpm'
        (package / 'package.json').write_text(json.dumps({'bin': {'pnpm': '../../outside'}}))
        result = self.source('/bin/sh', 'echo should-not-run')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('entry point escapes its package', result.stderr)

    def test_missing_canonical_manager_fails_before_cache_or_fnm_changes(self):
        (self.tools / '.local/share/fnm/node-versions/v22.23.5/installation/lib/node_modules/npm/bin/npm-cli.js').unlink()
        result = self.source('/bin/bash', 'echo should-not-run')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('snapshot npm entry point is unavailable', result.stderr)
        self.assertFalse((self.home / '.cache/c0/toolchain-defaults').exists())
        self.assertFalse((self.home / 'fnm-calls').exists())

    def test_legacy_snapshot_without_manifest_retains_existing_behavior(self):
        self.manifest.unlink()
        result = self.source('/bin/bash')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('legacy-python', result.stdout)
        self.assertIn('v22.23.4', result.stdout)

    def test_invalid_branch_or_missing_target_fails_activation(self):
        for node, python in (('24.1.0', '3.15.2'), ('22.23.5', '3.16.0'),
                             ('22.23.5; touch unsafe', '3.15.2'), ('22.23.6', '3.15.2'),
                             ('22.23.5', '3.15.3')):
            with self.subTest(node=node, python=python):
                self.write_manifest(node, python)
                result = self.source('/bin/sh', 'echo should-not-run')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('error: c0 toolchain defaults:', result.stderr)
                self.assertNotIn('should-not-run', result.stdout)

    def test_generated_cache_rejects_symlink_directory(self):
        outside = self.root / 'outside'
        outside.mkdir()
        cache = self.home / '.cache/c0'
        cache.mkdir(parents=True)
        (cache / 'toolchain-defaults').symlink_to(outside)
        result = self.source('/bin/bash', 'echo should-not-run')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('toolchain cache must be a directory owned by the guest user', result.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_repeat_activation_reuses_cache_without_duplicate_path_entries(self):
        result = self.source('/bin/sh', '''. "$HOME/bin/activate" || exit $?
printf '%s\\n' "$PATH"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = result.stdout.strip().split(':')
        defaults = [entry for entry in entries if '/toolchain-defaults/' in entry]
        self.assertEqual(len(defaults), 1)


if __name__ == '__main__':
    unittest.main()
