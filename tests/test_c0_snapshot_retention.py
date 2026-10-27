# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Garbage collection must not break resuming a stopped runtime."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

SOURCE = (Path(__file__).resolve().parents[1]/'bin/c0').read_text()
FUNCTIONS = '\n'.join(re.search(r'^'+name+r'\(\) \{\n.*?^\}', SOURCE, re.M|re.S).group()
                      for name in ('list_container_ids_using_tools_volume', 'get_tools_hash_label',
                                   'get_active_hashes', 'gc_tools_hashes'))
MOCK = '''
import os, sys
args = sys.argv[1:]
if args[0] == os.environ['TEST_FAIL']: sys.exit(27)
if args[0] == 'ps':
    if '-aq' in args: print('stopped-runtime')
    print('running-runtime')
elif args[0] == 'inspect':
    print(('a' if args[1] == 'stopped-runtime' else 'b')*64)
else: sys.exit(99)
'''


class SnapshotRetention(unittest.TestCase):
    def run_gc(self, fail=''):
        with tempfile.TemporaryDirectory(prefix='c0-gc-') as temp:
            root = Path(temp)
            docker = root/'docker'; docker.write_text('#!'+sys.executable+'\n'+MOCK); docker.chmod(0o755)
            script = root/'gc.sh'
            script.write_text('set -e\n'+FUNCTIONS+'''
SHARED_TOOLS_VOLUME=test-shared
IN_CONTAINER=false
tools_volume_exists() { return 0; }
cleanup_orphan_pins() { :; }
get_pinned_hashes() { :; }
tools_volume_sh() {
    case "$*" in
        'ls -1 /tools/opt'*) printf '%s\\n' "$TEST_STOPPED" "$TEST_RUNNING" "$TEST_UNUSED" ;;
        'test -f '*) return 0 ;;
        *) return 99 ;;
    esac
}
tools_volume_admin_sh() { printf '%s\\n' "$*" >> "$TEST_REMOVALS"; }
gc_tools_hashes
''')
            removals = root/'removals'
            env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ['PATH'], TEST_FAIL=fail,
                       TEST_REMOVALS=str(removals), TEST_STOPPED='a'*64, TEST_RUNNING='b'*64, TEST_UNUSED='c'*64)
            result = subprocess.run(['/bin/bash', str(script)], env=env, capture_output=True, text=True, timeout=5)
            return result, removals.read_text() if removals.exists() else ''

    def test_running_and_stopped_snapshots_are_preserved(self):
        result, removed = self.run_gc()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('a'*64, removed)
        self.assertNotIn('b'*64, removed)
        self.assertIn('c'*64, removed)

    def test_failed_container_listing_prevents_deletion(self):
        result, removed = self.run_gc(fail='ps')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(removed, '')

    def test_failed_label_inspection_prevents_deletion(self):
        result, removed = self.run_gc(fail='inspect')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(removed, '')


if __name__ == '__main__': unittest.main()
