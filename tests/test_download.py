import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from us_names.download import download_sources, source_manifest
from us_names.build import build

class DownloadTests(unittest.TestCase):
    def test_download_cache_and_hash_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            original=root/'original.zip'
            with zipfile.ZipFile(original,'w') as z:z.writestr('sample.txt','data')
            sources={'test':original.as_uri()}
            dest=root/'raw'
            manifest=download_sources(dest,sources=sources)
            self.assertEqual(manifest['test']['sha256'],hashlib.sha256(original.read_bytes()).hexdigest())
            original.unlink()
            self.assertEqual(download_sources(dest,sources=sources),manifest)
            (dest/'original.zip').write_bytes(b'corrupt')
            with self.assertRaises(ValueError): source_manifest(dest,sources=sources)

    def test_failed_download_does_not_leave_final_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'raw'
            with self.assertRaises(OSError):
                download_sources(dest,sources={'test':(Path(tmp)/'missing.zip').as_uri()})
            self.assertFalse((dest/'missing.zip').exists())
            self.assertFalse(list(dest.glob('*.part')))

    def test_build_is_offline_and_missing_inputs_create_no_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
                with self.assertRaises(FileNotFoundError):build(root/'missing',root/'out.sqlite')
            self.assertFalse((root/'out.sqlite').exists())

if __name__=='__main__':unittest.main()
