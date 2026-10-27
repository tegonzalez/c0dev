# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Runtime removal retains the validated instance volume selection."""
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'bin/c0').read_text()
INSTANCE = 'c0dev-storage-test'
CANONICAL = INSTANCE + '-home-overlays'
GENERATION = CANONICAL + '-' + 'a' * 32


def function(name):
    return re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE, re.M | re.S).group()


HELPERS = '\n'.join(function(name) for name in (
    'c0_validate_overlay_volume', 'c0_overlay_volume_for_container',
    'c0_overlay_selection_path', 'c0_write_overlay_selection',
    'c0_read_overlay_selection', 'c0_stop_instance', 'c0_create_runtime'))
STUBS = r'''
C0ROOT="$TEST_ROOT"
C0_INSTANCE_ID="$TEST_INSTANCE"
MAIN_SERVICE=c0dev
c0_require_docker() { return 0; }
c0_validate_container_mounts() { return 0; }
get_c0_container_id_any() { [[ -f "$TEST_ROOT/removed" ]] || echo existing; return 0; }
docker() {
    case "$1:$2" in
        inspect:-f)
            # No stale container label may override the actual mounted volume.
            [[ "$3" != *Config.Labels* ]] || return 91
            printf '%s\n' "$TEST_ACTUAL"
            ;;
        volume:inspect)
            case "$*" in
                *c0dev.instance*) printf '%s\n' "$TEST_OWNER" ;;
                *c0dev.overlay_generation*) printf '%s\n' "${TEST_ACTUAL##*-}" ;;
                *) [[ "$TEST_MISSING" != yes ]] ;;
            esac
            ;;
        stop:*) printf 'stop:%s\n' "$2" >>"$TEST_ROOT/trace" ;;
        rm:*)
            printf 'rm:%s\n' "$2" >>"$TEST_ROOT/trace"
            touch "$TEST_ROOT/removed"
            ;;
        *) echo "unexpected Docker call: $*" >&2; return 92 ;;
    esac
}
dc() { printf '%s\t%s\n' "$C0_HOME_OVERLAYS_VOLUME" "$C0_HOME_OVERLAYS_EXTERNAL" >>"$TEST_ROOT/trace"; }
'''


class OverlayStorage(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='c0-storage-selection-')
        self.root = Path(self.directory.name)
        self.record = self.root / '.local/c0' / (INSTANCE + '.home-overlays-volume')

    def tearDown(self):
        self.directory.cleanup()

    def run_script(self, script, *, actual=GENERATION, owner=INSTANCE, missing=False):
        env = dict(os.environ, TEST_ROOT=str(self.root), TEST_INSTANCE=INSTANCE,
                   TEST_ACTUAL=actual, TEST_OWNER=owner,
                   TEST_MISSING='yes' if missing else 'no',
                   C0_HOME_OVERLAYS_VOLUME='caller-controlled-volume',
                   C0_HOME_OVERLAYS_EXTERNAL='caller-controlled-value')
        return subprocess.run(['/bin/bash', '-c', HELPERS + '\n' + STUBS + '\n' + script],
                              env=env, cwd=self.root, capture_output=True, text=True, timeout=5)

    def write_record(self, payload):
        self.record.parent.mkdir(parents=True, exist_ok=True)
        self.record.write_text(payload)

    def trace(self):
        path = self.root / 'trace'
        return path.read_text().splitlines() if path.exists() else []

    def test_first_creation_uses_canonical_defaults_and_ignores_caller_overrides(self):
        result = self.run_script('c0_create_runtime fresh-runtime')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.trace(), [CANONICAL + '\tfalse'])

    def test_stop_records_actual_volume_before_removal_then_fresh_creation_reuses_it(self):
        self.write_record(CANONICAL + '\n')
        result = self.run_script('c0_stop_instance && c0_create_runtime fresh-runtime')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.record.read_text(), GENERATION + '\n')
        self.assertEqual(stat.S_IMODE(self.record.stat().st_mode), 0o600)
        self.assertEqual(self.trace(), ['stop:existing', 'rm:existing', GENERATION + '\ttrue'])
        self.assertEqual(list(self.record.parent.glob('.home-overlays.*')), [])

    def test_canonical_record_is_external_after_stop_so_missing_data_is_not_recreated(self):
        result = self.run_script('c0_stop_instance && c0_create_runtime fresh-runtime', actual=CANONICAL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.trace(), ['stop:existing', 'rm:existing', CANONICAL + '\ttrue'])
        result = self.run_script('c0_create_runtime fresh-runtime', actual=CANONICAL, missing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('selected home-overlay volume is missing', result.stderr)
        self.assertEqual(len(self.trace()), 3)

    def test_selection_write_failure_does_not_stop_or_remove_the_container(self):
        result = self.run_script('c0_write_overlay_selection() { return 17; }; c0_stop_instance')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('container was left unchanged', result.stderr)
        self.assertEqual(self.trace(), [])
        self.assertFalse((self.root / 'removed').exists())

    def test_existing_container_corrects_a_malformed_record_from_its_actual_mount(self):
        self.write_record('obsolete-not-a-volume\n')
        result = self.run_script('c0_stop_instance')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.record.read_text(), GENERATION + '\n')

    def test_missing_foreign_or_malformed_record_cannot_create_an_empty_replacement(self):
        cases = ((GENERATION + '\n', INSTANCE, True),
                 (GENERATION + '\n', 'another-checkout', False),
                 (GENERATION + '\n' + CANONICAL + '\n', INSTANCE, False),
                 ('$(touch SHOULD_NOT_RUN)\n', INSTANCE, False))
        for payload, owner, missing in cases:
            with self.subTest(payload=payload, owner=owner, missing=missing):
                self.write_record(payload)
                result = self.run_script('c0_create_runtime fresh-runtime', owner=owner, missing=missing)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.trace(), [])
                self.assertEqual(self.record.read_text(), payload)
        self.assertFalse((self.root / 'SHOULD_NOT_RUN').exists())

    def test_symlink_selection_is_not_followed_or_overwritten(self):
        self.record.parent.mkdir(parents=True)
        target = self.root / 'unrelated-data'
        target.write_text('keep-me')
        self.record.symlink_to(target)
        for operation in ('c0_read_overlay_selection', 'c0_stop_instance'):
            with self.subTest(operation=operation):
                result = self.run_script(operation)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.trace(), [])
                self.assertEqual(target.read_text(), 'keep-me')
                self.assertTrue(self.record.is_symlink())


if __name__ == '__main__':
    unittest.main()
