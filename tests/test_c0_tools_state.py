# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Tools operations preserve the running guest and unrelated persisted data."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SOURCE = (REPO / 'bin/c0').read_text()


def function(name):
    return re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE, re.M | re.S).group()


class ToolsState(unittest.TestCase):
    def exercise(self, operation, *, selected=None, shared=False, fail_clear=False,
                 publish_status=0, policy='.local|.local\n'):
        with tempfile.TemporaryDirectory(prefix='c0-tools-state-') as temp:
            root = Path(temp)
            trace = root / 'trace'
            trace.touch()
            policy_file = root / 'policy'
            policy_file.write_text(policy)
            env = dict(os.environ, TRACE=str(trace), C0ROOT=temp, C0_MODE='',
                       RUNNING='a' * 64, SELECTED=selected or 'a' * 64,
                       SHARED=str(int(shared)), FAIL_CLEAR=str(int(fail_clear)),
                       PUBLISH_STATUS=str(publish_status), TOOLS_ID='b' * 64,
                       HOME_OVERLAYS_FILE=str(policy_file), C0_RUNTIME_CID='container')
            script = 'set -e\n' + '\n'.join(function(name) for name in (
                'cmd_tools_accept', 'cmd_tools_restore',
                'c0_require_exclusive_overlay_volume')) + r'''
c0_require_container_running() { C0_RUNTIME_CID=container; }
get_c0_container_id() { echo container; }
c0_validate_container_mounts() { C0_CONTAINER_TOOLS_ID="$RUNNING"; }
set_tools_id() { TOOLS_ID=$1; }
c0_home_overlay_porcelain() { echo 'M .local/tool'; }
cmd_tools_stage_output() { :; }
c0_tools_helper_image() { echo sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc; }
c0_snapshot_home_overlays() { echo snapshot >"$2/stage.tar"; }
c0_publish_home_overlay_snapshot() {
    printf 'parent=%s\n' "$2" >>"$TRACE"
    return "$PUBLISH_STATUS"
}
c0_accept_runtime_metadata() { echo parent-image-metadata; }
c0_publish_accepted_runtime() { echo "artifact=$2" >>"$TRACE"; }
c0_runtime_recipe_ref() { echo shared-runtime; }
c0_resolve_shared_build() { TOOLS_BUILD_ID="$SELECTED"; }
c0_overlay_volume_for_container() { echo stage-volume; }
c0_clear_tools_stage() {
    printf 'clear=%s:%s\n' "$1" "$2" >>"$TRACE"
    [ "$FAIL_CLEAR" = 0 ]
}
c0_start_ready() { printf 'ready=%s:%s\n' "$1" "$2" >>"$TRACE"; }
docker() {
    case "$1" in
        ps) echo container; if [ "$SHARED" = 1 ]; then echo retained-backup; fi ;;
        stop|start) printf '%s=%s\n' "$1" "$2" >>"$TRACE" ;;
        image) [[ "$2" == inspect ]] ;;
        *) echo "unexpected Docker mutation: $*" >&2; return 99 ;;
    esac
}
'''
            result = subprocess.run(['/bin/bash', '-c', script + '\n' + operation],
                                    env=env, capture_output=True, text=True, timeout=10)
            return result, trace.read_text()

    def test_accept_publishes_from_actual_running_snapshot_without_replacing_guest(self):
        result, trace = self.exercise('cmd_tools_accept')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('parent=' + 'a' * 64, trace)
        self.assertRegex(trace, r'artifact=[a-f0-9]{64}')
        self.assertNotIn('stop=', trace)
        self.assertNotIn('clear=', trace)
        self.assertIn('fixed Docker mount cannot change in place', result.stderr)

    def test_failed_publish_keeps_selection_and_guest_untouched(self):
        result, trace = self.exercise('cmd_tools_accept', publish_status=23)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('artifact=', trace)
        self.assertNotIn('stop=', trace)

    def test_restore_stops_and_resumes_same_container(self):
        result, trace = self.exercise('cmd_tools_restore')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(trace.splitlines(), ['stop=container', 'clear=stage-volume:' + 'a' * 64,
                                              'start=container', 'ready=container:true'])

    def test_restore_refuses_different_selection_before_mutation(self):
        result, trace = self.exercise('cmd_tools_restore', selected='b' * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(trace, '')
        self.assertIn('guest data was not changed', result.stderr)

    def test_restore_refuses_stage_shared_with_retained_guest(self):
        result, trace = self.exercise('cmd_tools_restore', shared=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(trace, '')
        self.assertIn('retained-backup', result.stderr)

    def test_failed_restore_resumes_same_guest_and_reports_failure(self):
        result, trace = self.exercise('cmd_tools_restore', fail_clear=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('start=container\nready=container:true\n', trace)
        self.assertNotIn('artifact=', trace)

    def test_preexisting_generation_volume_requires_ownership_and_is_read_only_recognized(self):
        generation = 'c' * 32
        for owner, succeeds in (('checkout', True), ('other-checkout', False)):
            with self.subTest(owner=owner):
                script = function('c0_validate_overlay_volume') + '\n' + function('c0_overlay_volume_for_container') + r'''
docker() {
    case "$1:$2" in
        inspect:-f) echo "checkout-home-overlays-$GENERATION" ;;
        volume:inspect)
            case "$4" in
                *c0dev.instance*) echo "$OWNER" ;;
                *c0dev.overlay_generation*) echo "$GENERATION" ;;
                *) return 98 ;;
            esac ;;
        *) echo "unexpected mutation" >&2; return 99 ;;
    esac
}
c0_overlay_volume_for_container container
'''
                result = subprocess.run(['/bin/bash', '-c', script], capture_output=True, text=True,
                                        env=dict(os.environ, GENERATION=generation, OWNER=owner,
                                                 C0_INSTANCE_ID='checkout'), timeout=10)
                self.assertEqual(result.returncode == 0, succeeds, result.stderr)
                if succeeds:
                    self.assertEqual(result.stdout.strip(), 'checkout-home-overlays-' + generation)

    def test_clear_preserves_launcher_other_stages_and_unrelated_files(self):
        self.exercise_clear_stage(False)

    def test_clear_rejects_symlinked_stage_parent_before_deleting_data(self):
        self.exercise_clear_stage(True)

    def exercise_clear_stage(self, symlink_parent):
        with tempfile.TemporaryDirectory(prefix='c0-stage-command-') as temp:
            root = Path(temp)
            stage = root / 'stage'
            running, old = 'a' * 64, 'b' * 64
            files = ('upper/local/tool', 'upper/unrelated/data',
                     'work/' + running + '/local/work', 'work/' + old + '/local/work',
                     'launcher/upper/launcher', 'launcher/work/work', 'unrelated/data')
            for name in files:
                path = stage / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('preserved ' + name)
            if symlink_parent:
                (stage / 'upper').rename(stage / 'saved-upper')
                (stage / 'upper').symlink_to(stage / 'saved-upper', target_is_directory=True)
            policy = root / 'policy'
            policy.write_text('.local|.local\n')
            binary = root / 'docker'
            binary.write_text("#!/usr/bin/env python3\n" + r'''
import os, subprocess, sys
args = sys.argv[1:]
index = args.index('-c')
script = args[index+1].replace('/state', os.environ['STAGE'])
sys.exit(subprocess.run(['/bin/sh', '-eu', '-c', script, *args[index+2:]]).returncode)
''')
            binary.chmod(0o755)
            script = 'set -e\n' + '\n'.join(function(name) for name in (
                'c0_clear_tools_stage', 'c0_validate_overlay_row', 'c0_overlay_name')) + \
                '\nc0_clear_tools_stage stage-volume "$RUNNING" image\n'
            result = subprocess.run(['/bin/bash', '-c', script], capture_output=True, text=True,
                                    env=dict(os.environ, STAGE=str(stage), RUNNING=running,
                                             PATH=str(root) + os.pathsep + os.environ['PATH'],
                                             HOME_OVERLAYS_FILE=str(policy)), timeout=10)
            if symlink_parent:
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue((stage / 'upper/local/tool').exists())
                self.assertTrue((stage / ('work/' + running + '/local/work')).exists())
            else:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((stage / 'upper/local').exists())
                self.assertFalse((stage / ('work/' + running + '/local')).exists())
            for name in files[1:2] + files[3:]:
                self.assertEqual((stage / name).read_text(), 'preserved ' + name)


if __name__ == '__main__':
    unittest.main()
