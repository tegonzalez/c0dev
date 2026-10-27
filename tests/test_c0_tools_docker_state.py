# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Tools selection and cleanup use published Docker artifacts, not registries."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'bin/c0').read_text()


def function(name):
    return re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE, re.M | re.S).group()


class ToolsDockerState(unittest.TestCase):
    def exercise(self, operation, *, published='a' * 64, active='b' * 64,
                 known=('c' * 64,), snapshots=('a' * 64, 'b' * 64, 'c' * 64, 'd' * 64), legacy=True):
        with tempfile.TemporaryDirectory(prefix='c0-tools-docker-state-') as temporary:
            root = Path(temporary)
            store = root / 'store'
            for identity in snapshots:
                path = store / 'opt' / identity
                path.mkdir(parents=True)
                (path / 'payload').write_text(identity)
            (store / 'tmp').mkdir(parents=True)
            old = store / 'pins/old.pin'
            if legacy:
                old.parent.mkdir()
                old.write_text('obsolete selection must not be read or rewritten')
            helpers = '\n'.join(function(name) for name in ('gc_tools_hashes', 'cmd_clean'))
            script = helpers + r'''
IN_CONTAINER=false
SHARED_TOOLS_VOLUME=owned-test-store
require_host() { :; }
c0_require_docker() { :; }
tools_volume_exists() { return 0; }
get_active_hashes() { printf '%s\n' "$TEST_ACTIVE"; }
get_published_tools_hashes() { printf '%s\n' "$TEST_PUBLISHED"; }
list_container_ids_using_tools_volume() { [[ -z "$TEST_ACTIVE" ]] || echo container; return 0; }
tools_volume_cache_matches() { printf '%s\n' "$TEST_KNOWN" | grep -qx "$1"; }
tools_volume_sh() { /bin/sh -c "${1//\/tools/$TEST_STORE}"; }
tools_volume_admin_sh() { /bin/sh -c "${1//\/tools/$TEST_STORE}"; }
docker() {
    [[ "$1:$2" == volume:rm ]] || return 91
    touch "$TEST_ROOT/volume-removed"
}
''' + operation
            env = dict(os.environ, TEST_ROOT=str(root), TEST_STORE=str(store),
                       TEST_ACTIVE=active, TEST_PUBLISHED=published,
                       TEST_KNOWN='\n'.join(known))
            result = subprocess.run(['/bin/bash', '-c', script], env=env,
                                    capture_output=True, text=True, timeout=5)
            retained = sorted(path.name for path in (store / 'opt').iterdir())
            if legacy:
                self.assertEqual(old.read_text(), 'obsolete selection must not be read or rewritten')
            else:
                self.assertFalse(old.parent.exists())
            self.assertFalse((root / '.local').exists())
            return result, retained, (root / 'volume-removed').exists()

    def test_normal_clean_collects_only_unreferenced_rebuildable_cache(self):
        result, retained, removed_volume = self.exercise('cmd_clean', active='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(retained, ['a' * 64, 'b' * 64, 'd' * 64])
        self.assertFalse(removed_volume)

    def test_normal_clean_retains_container_referenced_store(self):
        result, retained, removed_volume = self.exercise('cmd_clean')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('nothing was removed', result.stderr)
        self.assertEqual(len(retained), 4)
        self.assertFalse(removed_volume)

    def test_clean_all_retains_published_or_container_referenced_store(self):
        for published, active in (('a' * 64, ''), ('', 'b' * 64)):
            with self.subTest(published=published, active=active):
                result, retained, removed_volume = self.exercise(
                    'cmd_clean --all', published=published, active=active)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('nothing was removed', result.stderr)
                self.assertEqual(len(retained), 4)
                self.assertFalse(removed_volume)

    def test_clean_all_retains_unknown_legacy_data(self):
        result, retained, removed_volume = self.exercise('cmd_clean --all', published='', active='')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('legacy data remains', result.stderr)
        self.assertEqual(retained, ['a' * 64, 'b' * 64, 'd' * 64])
        self.assertFalse(removed_volume)

    def test_clean_all_can_remove_a_wholly_unused_rebuildable_cache(self):
        result, retained, removed_volume = self.exercise(
            'cmd_clean --all', published='', active='', snapshots=('c' * 64,), legacy=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(retained, [])
        self.assertTrue(removed_volume)

    def test_published_references_are_validated_and_inspection_errors_propagate(self):
        script = function('get_published_tools_hashes') + r'''
SHARED_TOOLS_VOLUME=owned-test-store
docker() {
    case "$1:$2" in
        image:ls) printf 'image-a\nimage-b\n' ;;
        image:inspect)
            if [[ "${@: -1}" == image-b ]]; then return 29; fi
            printf '%064d\n' 1 ;;
        *) return 92 ;;
    esac
}
get_published_tools_hashes
'''
        result = subprocess.run(['/bin/bash', '-c', script], capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

    def test_selection_reads_shared_docker_metadata_only(self):
        script = '\n'.join(function(name) for name in ('set_tools_id', 'resolve_tools_selection')) + r'''
c0_resolve_shared_build() { TOOLS_BUILD_ID=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }
resolve_tools_selection
printf '%s\n' "$TOOLS_ID"
'''
        with tempfile.TemporaryDirectory(prefix='c0-no-tools-selector-') as root:
            result = subprocess.run(['/bin/bash', '-c', script], cwd=root,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'a' * 64)
            self.assertEqual(list(Path(root).iterdir()), [])




class CacheIdentity(unittest.TestCase):
    def test_only_current_recipe_rebuildable_cache_is_collectible(self):
        import hashlib
        import runpy
        resolver = runpy.run_path(str(ROOT / 'bin/c0-toolchain'))
        versions = dict(bun='1.4.4', uv='0.13.5', fnm='1.39.0', node='22.23.4',
                        python='3.15.1', pip='26.2.2', npm='12.2.1', pnpm='12.15.0', semgrep='1.182.1')
        payload = resolver['canonical_json'](dict(schema=1, versions=versions,
                                                  sources=resolver['source_urls'](versions)))
        recipe = 'a' * 64
        identity = hashlib.sha256(('c0-toolchain-build-v1\n' + recipe + '\n' +
                                   hashlib.sha256(payload.encode()).hexdigest() + '\n').encode()).hexdigest()
        with tempfile.TemporaryDirectory(prefix='c0-cache-identity-') as directory:
            root = Path(directory)
            snapshot = root / 'opt' / identity
            snapshot.mkdir(parents=True)
            (snapshot / '.c0dev-complete').touch()
            (snapshot / '.c0dev-toolchain.json').write_text(payload)
            (snapshot / '.c0dev-toolchain.json').chmod(0o600)
            helpers = function('tools_volume_cache_matches') + r'''
c0_docker_run() {
    [[ "$1:$2" == --user:1000:1000 ]] || return 9
    while [[ "$1" != sh ]]; do shift; done
    local -a command=()
    local argument
    for argument; do command+=("${argument//\/tools/$TEST_STORE}"); done
    "${command[@]}"
}
tools_volume_cache_matches "$TEST_ID"
'''
            env = dict(os.environ, C0ROOT=str(ROOT), TOOLS_RECIPE_ID=recipe,
                       SHARED_TOOLS_VOLUME='owned-cache', TEST_STORE=str(root), TEST_ID=identity)
            def probe():
                return subprocess.run(['/bin/bash', '-c', helpers], env=env,
                                      capture_output=True, text=True, timeout=5)
            self.assertEqual(probe().returncode, 0)
            (snapshot / '.c0dev-parent').write_text('accepted-native-data')
            self.assertNotEqual(probe().returncode, 0)
            (snapshot / '.c0dev-parent').unlink()
            env['TOOLS_RECIPE_ID'] = 'b' * 64
            self.assertNotEqual(probe().returncode, 0)


if __name__ == '__main__':
    unittest.main()
