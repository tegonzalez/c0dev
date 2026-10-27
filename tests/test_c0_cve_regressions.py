# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Opt-in native CVE behavior checks, to run inside an isolated built guest.

Run C0_CVE_NATIVE=1 <interpreter> tests/test_c0_cve_regressions.py -v for
both the managed Python and /usr/bin/python3. Every archive and possible output
stays within a newly allocated TemporaryDirectory. No Docker, network, mounts,
user files, or credentials are accessed by this module.

CVE-2026-114583 oracle: CPython gh-160097 and its 3.15 fix c6ada40177436e4e:
https://github.com/python/cpython/issues/160097
https://github.com/python/cpython/commit/c6ada40177436e4e2533a7b252082b5f0c043477
The contract rejects destination-replacing links with OutsideDestinationError;
it still permits normal files and links within the extraction directory.
"""
import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('C0_CVE_NATIVE') == '1',
                     'opt-in: run C0_CVE_NATIVE=1 inside an isolated built guest')
class PythonTarFilterCVE2026114583(unittest.TestCase):
    def test_tar_filter_refuses_destination_replacing_links(self):
        with tempfile.TemporaryDirectory(prefix='c0-cve-tar-filter-') as temporary:
            destination = Path(temporary) / 'extract'
            for name in ('', '.', './', 'nested/..'):
                for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    with self.subTest(name=name, kind=kind):
                        member = tarfile.TarInfo(name)
                        member.type = kind
                        member.linkname = '.'
                        with self.assertRaises(tarfile.OutsideDestinationError):
                            tarfile.tar_filter(member, str(destination))

    def test_empty_name_symlink_archive_cannot_redirect_later_file(self):
        with tempfile.TemporaryDirectory(prefix='c0-cve-tar-archive-') as temporary:
            root = Path(temporary)
            destination = root / 'extract'  # Deliberately absent at extraction.
            outside = root / 'outside'
            outside.mkdir()
            sentinel = outside / 'sentinel'
            sentinel.write_bytes(b'keep existing data')
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode='w') as writer:
                redirect = tarfile.TarInfo('')
                redirect.type = tarfile.SYMTYPE
                redirect.linkname = str(outside)
                writer.addfile(redirect)
                payload = b'archive payload'
                member = tarfile.TarInfo('payload')
                member.size = len(payload)
                writer.addfile(member, io.BytesIO(payload))
            archive.seek(0)
            rejected = False
            with tarfile.open(fileobj=archive, mode='r:') as reader:
                try:
                    reader.extractall(destination, filter='tar')
                except tarfile.OutsideDestinationError:
                    rejected = True
            self.assertEqual(sentinel.read_bytes(), b'keep existing data')
            self.assertFalse((outside / 'payload').exists(),
                             'archive wrote outside its intended extraction directory')
            self.assertFalse(destination.is_symlink(),
                             'archive replaced the extraction destination with a link')
            self.assertTrue(rejected, 'tar filter did not reject the destination-replacing link')

    def test_tar_filter_still_extracts_normal_file_and_named_relative_symlink(self):
        with tempfile.TemporaryDirectory(prefix='c0-cve-tar-valid-') as temporary:
            destination = Path(temporary) / 'extract'
            payload = b'normal archive data'
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode='w') as writer:
                member = tarfile.TarInfo('payload')
                member.size = len(payload)
                writer.addfile(member, io.BytesIO(payload))
                alias = tarfile.TarInfo('alias')
                alias.type = tarfile.SYMTYPE
                alias.linkname = 'payload'
                writer.addfile(alias)
            archive.seek(0)
            with tarfile.open(fileobj=archive, mode='r:') as reader:
                reader.extractall(destination, filter='tar')
            self.assertEqual((destination / 'payload').read_bytes(), payload)
            self.assertTrue((destination / 'alias').is_symlink())
            self.assertEqual((destination / 'alias').read_bytes(), payload)


if __name__ == '__main__':
    unittest.main()
