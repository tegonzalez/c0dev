# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Release identity, cached builds, and supervised cancellation stay consistent."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / 'bin/c0').read_text()


def function(name):
    return re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE, re.M | re.S).group()


RESOLVER = r'''
import json, os, sys
from pathlib import Path
versions = dict(bun='1.4.4', uv='0.13.5', fnm='1.39.0',
                node=os.environ['TEST_NODE'], python='3.15.1',
                npm='12.2.1', pnpm='12.15.0', semgrep='1.182.1',
                pip=os.environ['TEST_PIP'])
if sys.argv[1] == '--output':
    with open(os.environ['TEST_RESOLUTIONS'], 'a') as out: out.write('resolved\n')
    if os.environ.get('TEST_RESOLVE_FAIL'): sys.exit(28)
    Path(sys.argv[2]).write_text(json.dumps(dict(schema=1, versions=versions),
                                         sort_keys=True, separators=(',', ':'))+'\n')
elif sys.argv[1] == '--build-args':
    for key, value in json.loads(Path(sys.argv[2]).read_text())['versions'].items():
        print(key.upper()+'_VERSION='+value)
else: sys.exit(99)
'''


class ToolchainBuild(unittest.TestCase):
    def test_build_cache_requires_marker_and_exact_resolved_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = '{"schema":1,"versions":{"node":"22.23.4"}}\n'
            (root/'c0-toolchain.json').write_text(manifest)
            script = function('tools_volume_build_matches') + '''
C0_BUILD_CONTEXT="$TEST_ROOT"
SHARED_TOOLS_VOLUME=test-tools
c0_docker_run() {
    [[ "$1" == --user && "$2" == 1000:1000 ]] || return 2
    [[ "$TEST_MARKER" == yes ]] || return 1
    printf '%s' "$TEST_MANIFEST"
}
tools_volume_build_matches test-id
'''
            for marker, cached, expected in (
                    ('yes', manifest, 0), ('no', manifest, 1),
                    ('yes', '', 1), ('yes', manifest.replace('22.23.4', '22.23.3'), 1)):
                with self.subTest(marker=marker, cached=cached):
                    result = subprocess.run(['/bin/bash', '-c', script],
                                            env=dict(os.environ, TEST_ROOT=str(root),
                                                     TEST_MARKER=marker, TEST_MANIFEST=cached),
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, expected, result.stderr)

    def test_latest_release_and_recipe_determine_cache_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'bin').mkdir()
            resolver = root/'bin/c0-toolchain'
            resolver.write_text('#!'+sys.executable+'\n'+RESOLVER)
            resolver.chmod(0o755)
            script = '\n'.join(function(name) for name in (
                'short_hash', 'c0_instance_id_for', 'c0_set_build_identity',
                'set_tools_id', 'c0_resolve_toolchain', 'build_tools_volume')) + '''
set -e
C0ROOT="$TEST_ROOT"
C0_MODE=""
C0_MODE_KEY=prod
C0_RECIPE_ID="$TEST_RECIPE"
C0_BUILD_CONTEXT="$TEST_CONTEXT"
TOOLS_RECIPE_ID="$TEST_RECIPE"
TOOLS_BUILD_ID="$TEST_RECIPE"
SHARED_TOOLS_VOLUME=test-tools
verify_moby_seccomp_profile() { :; }
maybe_promote_staged_next() { :; }
tools_volume_build_matches() { echo "CACHE_LOOKUP=$1"; return 0; }
c0_resolve_toolchain
echo "BUILD_ID=$TOOLS_BUILD_ID"
echo "SELECTED_ID=$TOOLS_ID"
printf 'BUILD_ARG=%s\n' "${C0_TOOLCHAIN_BUILD_ARGS[@]}"
build_tools_volume false ''
'''
            records = []
            for number, (node, pip, recipe) in enumerate((
                    ('22.23.4', '26.2.2', 'a'*64), ('22.23.4', '26.2.2', 'a'*64),
                    ('22.23.5', '26.2.2', 'a'*64), ('22.23.4', '26.2.2', 'b'*64),
                    ('22.23.4', '26.2.3', 'a'*64))):
                context = root/str(number)
                context.mkdir()
                env = dict(os.environ, TEST_ROOT=str(root), TEST_CONTEXT=str(context),
                           TEST_NODE=node, TEST_PIP=pip, TEST_RECIPE=recipe,
                           TEST_RESOLUTIONS=str(root/'resolutions'))
                result = subprocess.run(['/bin/bash', '-c', script], env=env,
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                values = dict(line.split('=', 1) for line in result.stdout.splitlines()
                              if line.startswith(('BUILD_ID=', 'SELECTED_ID=', 'CACHE_LOOKUP=')))
                identity = values['BUILD_ID']
                self.assertRegex(identity, r'^[0-9a-f]{64}$')
                self.assertEqual(values['SELECTED_ID'], identity)
                self.assertEqual(values['CACHE_LOOKUP'], identity)
                self.assertEqual((context/'.c0-build-id').read_text().strip(), identity)
                self.assertIn('BUILD_ARG=NODE_VERSION='+node, result.stdout)
                self.assertIn('BUILD_ARG=PIP_VERSION='+pip, result.stdout)
                self.assertEqual(json.loads((context/'c0-toolchain.json').read_text())
                                 ['versions']['node'], node)
                records.append(identity)
            self.assertEqual(records[0], records[1])
            self.assertNotEqual(records[0], records[2])
            self.assertNotEqual(records[0], records[3])
            self.assertNotEqual(records[0], records[4])
            self.assertEqual((root/'resolutions').read_text(), 'resolved\n'*5)

    def test_supervisor_cleanup_uses_only_validated_worker_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            context = Path(temp)
            recipe, resolved = 'a'*64, 'b'*64
            script = function('c0_build_cleanup') + '''
C0_BUILD_CONTEXT="$TEST_CONTEXT"
TOOLS_BUILD_ID="$TEST_RECIPE"
C0_MODE_KEY=prod
SHARED_TOOLS_VOLUME=test-tools
tools_volume_exists() { return 0; }
docker() { printf 'DOCKER=%s\n' "$@" >>"$TEST_LOG"; }
c0_docker_run() { printf 'CLEANUP=%s\n' "$@" >>"$TEST_LOG"; }
c0_build_cleanup
'''
            for candidate, expected in ((resolved, resolved),
                                        ('$(touch should-not-execute)', recipe)):
                with self.subTest(candidate=candidate):
                    (context/'.c0-build-id').write_text(candidate+'\n')
                    log = context/'cleanup.log'
                    log.unlink(missing_ok=True)
                    env = dict(os.environ, TEST_CONTEXT=str(context), TEST_RECIPE=recipe,
                               TEST_LOG=str(log))
                    result = subprocess.run(['/bin/bash', '-c', script], env=env,
                                            text=True, capture_output=True, timeout=5, cwd=context)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('DOCKER=c0dev-tools-builder-prod:'+expected, log.read_text())
                    self.assertIn('CLEANUP=/tools/tmp/'+expected+'.partial', log.read_text())
                    self.assertFalse((context/'should-not-execute').exists())
                    self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
