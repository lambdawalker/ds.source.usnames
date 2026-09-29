import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from us_names import Dataset
from us_names.cli import main

class CLITests(unittest.TestCase):
    def test_batch_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'names.sqlite'
            with Dataset.create(db) as store:
                store.add_name('JOSE','given',10,{'hispanic':10},'fixture')
                store.add_sex('JOSE','M',10,'fixture')
                store.add_name('RUIZ','surname',10,{'hispanic':10},'fixture')
                store.commit()
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                main(['generate','--db',str(db),'--count','3','--seed','1','--jsonl'])
            results=[json.loads(line) for line in out.getvalue().splitlines()]
            self.assertEqual(len(results),3)
            self.assertTrue(all(r['text']=='JOSE RUIZ' for r in results))

if __name__=='__main__': unittest.main()
