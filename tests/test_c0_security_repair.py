# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Private system-Python repair refusal and existing-protection boundaries.

Controlled probes exercise repair decisions only; native CVE behavior is verified
separately by test_c0_cve_regressions.py inside isolated built guests.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


class SystemPythonRepairBoundary(unittest.TestCase):
    """Repair refusal/no-op control flow; native protection has its own guest suite."""
    def helper(self, protected):
        target = Path(__file__).resolve().parents[1] / 'docker/c0-security.py'
        spec = importlib.util.spec_from_file_location('c0_security_test', target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class ControlledOutsideDestinationError(Exception):
            pass

        def probe(member, destination):
            if protected:
                raise ControlledOutsideDestinationError(member, str(destination))
            return member

        module.tarfile = SimpleNamespace(
            TarInfo=tarfile.TarInfo, SYMTYPE=tarfile.SYMTYPE, LNKTYPE=tarfile.LNKTYPE,
            REGTYPE=tarfile.REGTYPE, os=os,
            OutsideDestinationError=ControlledOutsideDestinationError,
            tar_filter=mock.Mock(side_effect=probe))
        return module

    def test_unknown_unprotected_implementation_is_refused_without_changing_bytes(self):
        module = self.helper(protected=False)
        with tempfile.TemporaryDirectory(prefix='c0-repair-refusal-') as temporary:
            target = Path(temporary) / 'tarfile.py'
            source = b'def _get_filtered_attrs(member, destination):\n    return {}\n'
            target.write_bytes(source)
            with self.assertRaisesRegex(ValueError, 'unrecognized system tarfile implementation'):
                module.patch_python_tarfile(target)
            self.assertEqual(target.read_bytes(), source)
            self.assertGreater(module.tarfile.tar_filter.call_count, 0)

    def test_unsafe_sources_with_misplaced_or_bypassed_repair_sites_refuse_without_write(self):
        consumer = """def tar_filter(member, dest_path):
    new_attrs = _get_filtered_attrs(member, dest_path, False)
    if new_attrs:
        return member.replace(**new_attrs, deep=False)
    return member
"""
        fixtures = {
            'anchor-in-unrelated-function': """def _get_filtered_attrs(member, dest_path, for_data=True):
    return {}

def unrelated_function():
    # Limit permissions (no high bits, and go-w)
    return {}

""" + consumer,
            'target-returns-before-anchor': """def _get_filtered_attrs(member, dest_path, for_data=True):
    name = member.name
    target_path = dest_path
    return {}
    # Limit permissions (no high bits, and go-w)
    return {}

""" + consumer,
            'public-filter-bypasses-helper': """def _get_filtered_attrs(member, dest_path, for_data=True):
    name = member.name
    target_path = dest_path
    # Limit permissions (no high bits, and go-w)
    return {}

def tar_filter(member, dest_path):
    return member
""",
        }
        for condition, source in fixtures.items():
            with self.subTest(condition=condition):
                # Establish that this source's public consumer actually allows
                # the dangerous member; it is a wrong-result fixture, not merely
                # a different arrangement of the repair's text anchor.
                namespace = {}
                exec(compile(source, '<controlled-unprotected-tarfile>', 'exec'), namespace)
                member = tarfile.TarInfo('')
                member.type, member.linkname = tarfile.SYMTYPE, '.'
                self.assertIs(namespace['tar_filter'](member, '/tmp/controlled-extract'), member)
                module = self.helper(protected=False)
                with tempfile.TemporaryDirectory(prefix='c0-repair-unsafe-source-') as temporary:
                    target = Path(temporary) / 'tarfile.py'
                    original = source.encode()
                    target.write_bytes(original)
                    with self.assertRaises(ValueError):
                        module.patch_python_tarfile(target)
                    self.assertEqual(target.read_bytes(), original)

    def test_already_protected_implementation_is_byte_preserving_and_idempotent(self):
        module = self.helper(protected=True)
        with tempfile.TemporaryDirectory(prefix='c0-repair-noop-') as temporary:
            target = Path(temporary) / 'tarfile.py'
            # A distribution-protected implementation need not use our patch anchor.
            source = b'# controlled already-protected distribution implementation\n'
            target.write_bytes(source)
            digest = hashlib.sha256(source).hexdigest()
            for _ in range(2):
                result = module.patch_python_tarfile(target)
                self.assertTrue(result['already_fixed'])
                self.assertEqual(result['advisory'], 'CVE-2026-114583')
                self.assertEqual(result['before_sha256'], digest)
                self.assertEqual(result['after_sha256'], digest)
                self.assertEqual(target.read_bytes(), source)
            self.assertGreater(module.tarfile.tar_filter.call_count, 0)


if __name__ == '__main__':
    unittest.main()
