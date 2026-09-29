import tempfile
import unittest
import zipfile
from pathlib import Path
import openpyxl
from us_names import Dataset
from us_names.build import import_census, import_ssa, import_census_sex

class ImportTests(unittest.TestCase):
    def test_official_columns_preserved_and_ssa_sexes_retained(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            w=openpyxl.Workbook()
            w.active.append(['Title'])
            w.active.append([])
            w.active.append(['FIRST NAME','RANK','FREQUENCY (COUNT)','PROPORTION PER 100,000 POPULATION','CUMULATIVE PROPORTION','NON-HISPANIC OR LATINO WHITE ALONE','NON-HISPANIC OR LATINO BLACK OR AFRICAN AMERICAN ALONE','NON-HISPANIC OR LATINO AMERICAN INDIAN AND ALASKA NATIVE ALONE','NON-HISPANIC OR LATINO ASIAN AND NATIVE HAWAIIAN AND OTHER PACIFIC ISLANDER ALONE','NON-HISPANIC OR LATINO TWO OR MORE RACES','HISPANIC OR LATINO ORIGIN'])
            w.active.append(['JOSE',1,100,1,1,0,0,0,0,0,100])
            w.active.append(['ALL OTHER NAMES',None,500,1,1,500,0,0,0,0,0])
            w.save(p/'names.xlsx')
            with zipfile.ZipFile(p/'names.zip','w') as z:
                z.writestr('yob2000.txt','Jose,M,10\nJose,F,5\nRare,F,6\n')
                z.writestr('../ignore.txt','not data')
            with Dataset.create(p/'names.sqlite') as db:
                self.assertEqual(import_census(db,p/'names.xlsx','given'),1)
                summary=import_ssa(db,p/'names.zip')
                self.assertEqual(summary['year_range'],[2000,2000])
                row=db.connection.execute('SELECT SUM(a.count) FROM name_year_sex_counts a JOIN names n ON n.id=a.name_id WHERE n.name=?',('JOSE',)).fetchone()
                self.assertEqual(row[0],15)
                self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM name_year_sex_counts a JOIN names n ON n.id=a.name_id WHERE n.name='JOSE'").fetchone()[0],2)
                row=db.connection.execute('SELECT total,source_id FROM names WHERE name=?',('RARE',)).fetchone()
                self.assertIsNone(row[0])
                self.assertEqual(row[1],'ssa_national')

if __name__=='__main__':unittest.main()
