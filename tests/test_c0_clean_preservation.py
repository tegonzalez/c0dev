# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Tools cleanup must not remove guests or invalidate retained recovery data."""
import unittest
from c0_fixture import Fixture


class CleanPreservation(unittest.TestCase):
    def test_clean_refuses_storage_referenced_by_any_guest(self):
        for status in ('running', 'exited'):
            for recovery in (False, True):
                for args in (('clean',), ('clean', '--all')):
                    with self.subTest(status=status, recovery=recovery, args=args):
                        fixture = Fixture()
                        try:
                            state = fixture.read()
                            guest = state['containers'][0]
                            guest['state'] = status
                            guest['rootfs'] = {'/home/dev/only-copy': 'keep'}
                            if recovery:
                                guest['name'] = f'c0-recovery-{fixture.instance}-{guest["id"]}'
                            fixture.write(state)
                            result = fixture.run(*args)
                            self.assertNotEqual(result.returncode, 0)
                            self.assertIn('nothing was removed', result.stderr)
                            after = fixture.read()
                            self.assertEqual(after['containers'][0]['rootfs'], guest['rootfs'])
                            self.assertFalse(any(call[0] in ('rm', 'run', 'stop', 'rename')
                                                 for call in after['calls']))
                            self.assertFalse(any(call[:2] == ['volume', 'rm']
                                                 for call in after['calls']))
                        finally:
                            fixture.close()
