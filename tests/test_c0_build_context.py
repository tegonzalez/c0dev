# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Generated build inputs are private to a build, never inherited from a fork."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT/'bin/c0').read_text()
FUNCTIONS = '\n'.join(re.search(r'^'+name+r'\(\) \{\n.*?^\}', SOURCE, re.M|re.S).group()
                      for name in ('cmd_build', 'c0_build_wait_group', 'c0_build_cancel_group',
                                   'c0_prepare_build_context', 'c0_prepare_tools_dockerfile',
                                   'c0_prepare_runtime_dockerfile'))


class BuildContext(unittest.TestCase):
    def test_fresh_inputs_concurrent_builds_and_cleanup_on_failure(self):
        with tempfile.TemporaryDirectory(prefix='c0-context-test-') as temp:
            root = Path(temp)
            (root/'bin').mkdir()
            (root/'docker').mkdir()
            shutil.copyfile(ROOT/'bin/dockerfile-concat', root/'bin/dockerfile-concat')
            (root/'bin/dockerfile-concat').chmod(0o755)
            inputs = ('1password.asc', 'cloud.google.gpg', 'install-orca.sh',
                      'docker-entrypoint.sh', 'home-overlays.conf', 'c0-overlay-check', 'c0-security.py')
            for name in inputs: (root/'docker'/name).write_text('canonical '+name+'\n')
            for name in ('base', 'tools', 'runtime'):
                (root/'docker'/('Dockerfile.'+name)).write_text('# canonical '+name+'\n')
            for name in ('.Dockerfile.build', '.Dockerfile.tools.build'):
                (root/'docker'/name).write_text('stale content from another fork\n')
            script = root/'build.sh'
            script.write_text('set -e\n'+FUNCTIONS+'''
C0ROOT="$TEST_ROOT"
DOCKERFILE_BASE="$C0ROOT/docker/Dockerfile.base"
DOCKERFILE_TOOLS="$C0ROOT/docker/Dockerfile.tools"
DOCKERFILE_RUNTIME="$C0ROOT/docker/Dockerfile.runtime"
require_host() { :; }
c0_build_steps() {
    c0_prepare_build_context
    c0_prepare_tools_dockerfile
    c0_prepare_runtime_dockerfile
    printf '%s' "$C0_BUILD_CONTEXT" > "$TEST_CAPTURE.path"
    cp -R "$C0_BUILD_CONTEXT" "$TEST_CAPTURE"
    sleep 0.3
    return "$TEST_STATUS"
}
cmd_build
''')
            procs = []
            for number, status in enumerate((0, 42)):
                capture = root/('capture-'+str(number))
                env = dict(os.environ, TEST_ROOT=str(root), TEST_CAPTURE=str(capture),
                           TEST_STATUS=str(status))
                procs.append(subprocess.Popen(['/bin/bash', str(script)], env=env,
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE))
            paths = []
            for number, proc in enumerate(procs):
                out, err = proc.communicate(timeout=5)
                self.assertEqual(proc.returncode, (0, 42)[number], (out, err))
                capture = root/('capture-'+str(number))
                path = Path(Path(str(capture)+'.path').read_text())
                paths.append(path)
                self.assertFalse(path.parent.exists())
                self.assertNotEqual(path.parent, root/'docker')
                self.assertEqual((capture/'Dockerfile.tools.build').read_text(),
                                 '# canonical base\n\n# canonical tools\n')
                self.assertEqual((capture/'Dockerfile.runtime.build').read_text(),
                                 '# canonical base\n\n# canonical runtime\n')
                for name in inputs:
                    self.assertEqual((capture/name).read_bytes(), (root/'docker'/name).read_bytes(), name)
                self.assertEqual(set(p.name for p in capture.iterdir()),
                                 set(inputs)|{'.terminfo', 'Dockerfile.tools.build', 'Dockerfile.runtime.build'})
            self.assertNotEqual(paths[0], paths[1])
            self.assertFalse((root/'docker/.terminfo').exists())
            self.assertEqual((root/'docker/.Dockerfile.build').read_text(),
                             'stale content from another fork\n')


if __name__ == '__main__':
    unittest.main()
