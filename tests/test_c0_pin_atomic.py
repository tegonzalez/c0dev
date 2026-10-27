# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Publish selection metadata atomically and treat checkout names as data."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'bin/c0').read_text()
FUNCTIONS = '\n'.join(re.search(r'^' + name + r'\(\) \{\n.*?^\}', SOURCE,
                                re.M | re.S).group()
                      for name in ('pin_path_for_folder_id', 'write_pin_for_folder_id'))


class PinAtomic(unittest.TestCase):
    def test_checkout_metacharacters_are_literal_and_rename_failure_keeps_old_pin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkout = root / 'project$(touch INJECTED)'
            checkout.mkdir()
            store = root / 'store'
            (store / 'pins').mkdir(parents=True)
            folder, old, new = 'a' * 64, 'b' * 64, 'c' * 64
            pin = store / 'pins' / (folder + '.pin')
            pin.write_text('tools_id=' + old + '\n')
            wrapper = root / 'commands'
            wrapper.mkdir()
            (wrapper / 'mv').write_text('#!/bin/sh\nexit 31\n')
            (wrapper / 'mv').chmod(0o755)
            script = FUNCTIONS + r'''
IN_CONTAINER=false
tools_volume_sh() {
    local script="$1"
    script=${script//\/tools\//"$TEST_STORE/"}
    /bin/sh -eu -c "$script"
}
write_pin_for_folder_id "$TEST_FOLDER" "$TEST_NEW" "$TEST_CHECKOUT" ''
'''
            env = dict(os.environ, TEST_STORE=str(store), TEST_FOLDER=folder,
                       TEST_NEW=new, TEST_CHECKOUT=str(checkout))
            failed = subprocess.run(['/bin/bash', '-c', script], env=dict(
                env, PATH=str(wrapper) + os.pathsep + os.environ['PATH']),
                text=True, capture_output=True, cwd=root, timeout=5)
            self.assertEqual(failed.returncode, 31, failed.stderr)
            self.assertEqual(pin.read_text(), 'tools_id=' + old + '\n')
            self.assertFalse((root / 'INJECTED').exists())
            self.assertEqual(list((store / 'pins').iterdir()), [pin])
            success = subprocess.run(['/bin/bash', '-c', script], env=env,
                                     text=True, capture_output=True, cwd=root, timeout=5)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertIn('tools_id=' + new, pin.read_text())
            self.assertIn('c0root=' + str(checkout.resolve()), pin.read_text())
            self.assertFalse((root / 'INJECTED').exists())
