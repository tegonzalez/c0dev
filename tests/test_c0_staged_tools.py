# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Offline next-build promotion preserves referenced and rejected payloads."""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'bin/c0').read_text()
RESOLVER = runpy.run_path(str(ROOT / 'bin/c0-toolchain'))


def function(name):
    return re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE, re.M | re.S).group()


def manifest(node='22.23.4'):
    versions = dict(bun='1.4.4', uv='0.13.5', fnm='1.39.0', node=node,
                    python='3.15.2', pip='26.2.2', npm='12.2.1', pnpm='12.15.0',
                    semgrep='1.182.1')
    return RESOLVER['canonical_json'](dict(schema=1, versions=versions,
                                         sources=RESOLVER['source_urls'](
                                             versions, 'https://github.com/astral-sh/python-build-standalone/releases/download/'
                                             '20261026/cpython-3.15.2%2B20261026-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz'
                                             '#sha256=' + 'a' * 64)))


class StagedTools(unittest.TestCase):
    def promote(self, staged=None, *, marker=True, referenced=False, recipe=None,
                context=False, fail_admin=False):
        recipe = recipe or 'a' * 64
        payload = manifest()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        identity = hashlib.sha256(('c0-toolchain-build-v1\n' + 'a' * 64 + '\n'
                                   + digest + '\n').encode()).hexdigest()
        with tempfile.TemporaryDirectory(prefix='c0-staged-tools-') as temporary:
            root = Path(temporary)
            store = root / 'store'
            old = store / 'opt' / identity
            stage = store / 'tmp' / (identity + '.next')
            for path, content in ((old, 'old-tools'), (stage, 'rebuilt-tools')):
                path.mkdir(parents=True)
                (path / 'payload').write_text(content)
            (stage / '.c0dev-toolchain.json').write_text(payload if staged is None else staged)
            (stage / '.c0dev-toolchain.json').chmod(0o600)
            if marker:
                (stage / '.c0dev-complete').touch()
            context_path = root / 'context'
            context_path.mkdir()
            (context_path / 'c0-toolchain.json').write_text(payload)
            script = '\n'.join(function(name) for name in (
                'tools_volume_staged_matches', 'tools_volume_build_matches',
                'maybe_promote_staged_next')) + r'''
C0ROOT="$TEST_CHECKOUT"
SHARED_TOOLS_VOLUME=test-tools
TOOLS_RECIPE_ID="$TEST_RECIPE"
if [[ "$TEST_CONTEXT" == yes ]]; then C0_BUILD_CONTEXT="$TEST_ROOT/context"; else unset C0_BUILD_CONTEXT; fi
tools_volume_exists() { return 0; }
tools_volume_sh() { /bin/sh -c "${1//\/tools/$TEST_STORE}"; }
tools_volume_admin_sh() {
    [[ "$TEST_FAIL_ADMIN" != yes ]] || return 7
    /bin/sh -c "${1//\/tools/$TEST_STORE}"
}
c0_docker_run() {
    [[ "$1" == --user && "$2" == 1000:1000 ]] || return 9
    test -f "$TEST_STORE/tmp/$TEST_ID.next/.c0dev-complete" &&
        cat "$TEST_STORE/tmp/$TEST_ID.next/.c0dev-toolchain.json"
}
get_active_hashes() { [[ "$TEST_REFERENCED" != yes ]] || printf '%s\n' "$TEST_ID"; return 0; }
maybe_promote_staged_next "$TEST_ID"
'''
            env = dict(os.environ, TEST_CHECKOUT=str(ROOT), TEST_ROOT=str(root),
                       TEST_STORE=str(store), TEST_ID=identity, TEST_RECIPE=recipe,
                       TEST_CONTEXT='yes' if context else 'no',
                       TEST_REFERENCED='yes' if referenced else 'no',
                       TEST_FAIL_ADMIN='yes' if fail_admin else 'no')
            result = subprocess.run(['/bin/bash', '-c', script], env=env,
                                    capture_output=True, text=True, timeout=10)
            return result, (old / 'payload').read_text(), stage.exists()

    def test_offline_start_promotes_same_hash_rebuild_after_last_reference_is_removed(self):
        result, payload, stage_remains = self.promote()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload, 'rebuilt-tools')
        self.assertFalse(stage_remains)

    def test_referenced_staged_build_is_not_promoted(self):
        result, payload, stage_remains = self.promote(referenced=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload, 'old-tools')
        self.assertTrue(stage_remains)
        self.assertIn('retained containers still use this snapshot', result.stderr)

    def test_rejected_stage_never_replaces_existing_tools(self):
        for candidate in ({'staged': manifest('22.23.5')}, {'staged': '{malformed'},
                          {'marker': False}, {'recipe': 'b' * 64}):
            with self.subTest(candidate=candidate):
                result, payload, stage_remains = self.promote(**candidate)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('existing tools retained', result.stderr)
                self.assertEqual(payload, 'old-tools')
                self.assertTrue(stage_remains)

    def test_build_still_requires_the_exact_freshly_resolved_manifest(self):
        for staged, expected in ((None, 'rebuilt-tools'), (manifest('22.23.5'), 'old-tools')):
            with self.subTest(staged=staged):
                result, payload, _ = self.promote(staged=staged, context=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(payload, expected)

    def test_promotion_failure_is_reported_without_losing_old_tools(self):
        result, payload, stage_remains = self.promote(fail_admin=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payload, 'old-tools')
        self.assertTrue(stage_remains)


@unittest.skipUnless(os.environ.get('C0_BUILD_DOCKER_TESTS') == '1', 'opt-in real Docker tools promotion')
class StagedToolsDocker(unittest.TestCase):
    def test_private_staged_manifest_promotes_without_build_context_or_network(self):
        docker = shutil.which('docker')
        self.assertTrue(docker)
        if subprocess.run([docker, 'image', 'inspect', 'alpine:latest'],
                          capture_output=True).returncode:
            self.skipTest('alpine is not cached; refusing to pull')
        token = uuid.uuid4().hex
        volume = 'c0-staged-audit-' + token
        recipe = 'a' * 64
        payload = manifest()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        identity = hashlib.sha256(('c0-toolchain-build-v1\n' + recipe + '\n'
                                   + digest + '\n').encode()).hexdigest()

        def call(*args, **kwargs):
            return subprocess.run([docker, *args], capture_output=True, text=True,
                                  timeout=30, **kwargs)

        self.assertNotEqual(call('volume', 'inspect', volume).returncode, 0)
        result = call('volume', 'create', '--label', 'c0dev.staged_audit=' + token, volume)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            result = call('run', '--rm', '--pull=never', '--network', 'none', '-i',
                          '-v', volume + ':/tools', 'alpine:latest', 'sh', '-ec',
                          'old=/tools/opt/' + identity + '; next=/tools/tmp/' + identity + '.next; '
                          'mkdir -p "$old" "$next"; printf old >"$old/payload"; '
                          'printf rebuilt >"$next/payload"; '
                          'cat >"$next/.c0dev-toolchain.json"; '
                          'touch "$next/.c0dev-complete"; '
                          'chmod 600 "$next/.c0dev-toolchain.json"; chown -R 1000:1000 "$next"',
                          input=payload)
            self.assertEqual(result.returncode, 0, result.stderr)
            helpers = '\n'.join(function(name) for name in (
                'c0_docker_run', 'tools_volume_exists', 'tools_volume_sh',
                'tools_volume_admin_sh', 'tools_volume_staged_matches',
                'tools_volume_build_matches', 'maybe_promote_staged_next'))
            script = helpers + r'''
C0ROOT="$TEST_CHECKOUT"
SHARED_TOOLS_VOLUME="$TEST_VOLUME"
TOOLS_RECIPE_ID="$TEST_RECIPE"
unset C0_BUILD_CONTEXT
get_active_hashes() { return 0; }
maybe_promote_staged_next "$TEST_ID"
'''
            result = subprocess.run(['/bin/bash', '-c', script],
                                    env=dict(os.environ, TEST_CHECKOUT=str(ROOT),
                                             TEST_VOLUME=volume, TEST_RECIPE=recipe, TEST_ID=identity),
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Promoted:', result.stdout)
            result = call('run', '--rm', '--pull=never', '--network', 'none',
                          '--user', '1000:1000', '-v', volume + ':/tools:ro',
                          'alpine:latest', 'sh', '-ec',
                          'test ! -e /tools/tmp/' + identity + '.next; '
                          'test "$(cat /tools/opt/' + identity + '/payload)" = rebuilt; '
                          'test "$(stat -c %u:%g:%a /tools/opt/' + identity + '/.c0dev-toolchain.json)" = 1000:1000:600')
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            ownership = call('volume', 'inspect', '--format',
                             '{{index .Labels "c0dev.staged_audit"}}', volume)
            self.assertEqual(ownership.returncode, 0, ownership.stderr)
            self.assertEqual(ownership.stdout.strip(), token,
                             'refusing to remove volume without this test ownership label')
            result = call('volume', 'rm', volume)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
