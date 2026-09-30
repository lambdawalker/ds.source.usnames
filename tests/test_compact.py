import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from us_names_source.database import Dataset
from us_names_source import compact

class CompactTests(unittest.TestCase):
    def test_interpolation_and_constant_extrapolation(self):
        values, flags = compact.fill_series([None, .2, None, .6, None], .1)
        self.assertEqual(flags, [2,0,1,0,2])
        for actual, expected in zip(values,[.2,.2,.4,.6,.6]):
            self.assertAlmostEqual(actual,expected)
        self.assertEqual(compact.fill_series([None,None],.3),([.3,.3],[3,3]))

    def test_quantization_retains_small_positive_weights(self):
        values=compact.quantize_weights([1e-15,.2,.8],1000)
        self.assertEqual(sum(values),1000)
        self.assertGreater(values[0],0)

    def test_build_retains_names_and_marks_estimates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with Dataset.create(root/'stage.sqlite') as db:
                for name,total in [('ERICA',100),('ALEX',100),('NO_ANNUAL',10)]:
                    db.add_name(name,'given',total,{'white':total},'fixture')
                    db.add_sex(name,'F',70,'fixture')
                    db.add_sex(name,'M',30,'fixture')
                db.add_name('SMITH','surname',10,{'white':10},'fixture')
                for year, female in [(1991,7),(1997,3)]:
                    db.add_annual('ERICA',year,female,'F')
                    db.add_annual('ERICA',year,10-female,'M')
                for year in (1991,1994,1999):
                    db.add_annual('ALEX',year,10,'M')
                db.set_metadata('sources',{})
                db.set_metadata('dataset_version','fixture')
                db.commit()
            meta=compact.build_compact(root/'stage.sqlite',root/'out.sqlite',bucket_anchor=1991)
            with sqlite3.connect(root/'out.sqlite') as c:
                c.row_factory=sqlite3.Row
                self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],3)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM names').fetchone()[0],4)
                row=c.execute("SELECT * FROM names WHERE name='ERICA'").fetchone()
                self.assertEqual(row['female_1991_1993'],7000)
                self.assertAlmostEqual(c.execute("SELECT female_1991_1993 FROM names_normalized WHERE name='ERICA'").fetchone()[0],.7)
                self.assertEqual(row['female_1994_1996'],5000)
                self.assertEqual(row['female_1997_1999'],3000)
                self.assertEqual(compact.decode_flags(row['period_evidence'],3),[0,1,0])
                for period in c.execute('SELECT * FROM periods').fetchall():
                    suffix=f"{period['start_year']}_{period['end_year']}"
                    self.assertEqual(c.execute(f'SELECT SUM(frequency_{suffix}) FROM names').fetchone()[0],compact.FREQUENCY_SCALE)
                    self.assertGreater(c.execute(f"SELECT frequency_{suffix} FROM names WHERE name='NO_ANNUAL'").fetchone()[0],0)
                    self.assertIsNone(c.execute(f"SELECT female_{suffix} FROM names WHERE name='SMITH'").fetchone()[0])
                self.assertEqual(c.execute('SELECT observed_total FROM periods ORDER BY start_year').fetchall()[1][0],10)
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
            from us_names_source.export import iter_records
            with sqlite3.connect(root/'out.sqlite') as c:
                exported=list(iter_records(c))
                erica=next(r for r in exported if r['name']=='ERICA')
                self.assertEqual(erica['periods']['1994_1996']['evidence'],'interpolated')
                self.assertEqual(erica['periods']['1991_1993']['female_share'],.7)
            self.assertEqual(meta['statistics']['retained_names'],4)
            with self.assertRaises(FileExistsError):
                compact.build_compact(root/'stage.sqlite',root/'out.sqlite',bucket_anchor=1991)
