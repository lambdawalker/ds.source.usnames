import tempfile
import unittest
from pathlib import Path
from us_names import Dataset, Generator, Query, NoCandidates

class GenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Dataset.create(Path(self.tmp.name)/'names.sqlite')
        for text,male,female in [('ERIKA',1,9999),('EDGAR',9999,1),('ALEX',5000,5000)]:
            self.db.add_name(text,'given',10000,{'hispanic':10000},'fixture')
            self.db.add_sex(text,'M',male,'fixture')
            self.db.add_sex(text,'F',female,'fixture')
        self.db.add_name('ESPARZA','surname',100,{'hispanic':100},'fixture')
        self.db.add_annual('ERIKA',2000,99,'F')
        self.db.add_annual('ERIKA',2000,1,'M')
        self.db.add_annual('EDGAR',2000,99,'M')
        self.db.add_annual('EDGAR',2000,1,'F')
        self.db.commit()
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def test_shared_gender_even_with_uniform_sampling(self):
        for weighted in (True,False):
            g=Generator(self.db,3)
            for _ in range(200):
                r=g.generate(Query(format='full',group='hispanic',use_frequency_weights=weighted))
                self.assertNotEqual(set(r['given_names']),{'ERIKA','EDGAR'})
                forbidden='EDGAR' if r['gender']=='female' else 'ERIKA'
                self.assertNotIn(forbidden,r['given_names'])
    def test_explicit_gender_and_cohort(self):
        g=Generator(self.db,3)
        for _ in range(20):
            r=g.generate(Query(format='full',gender='female',birth_year_range=(2000,2000)))
            self.assertEqual(r['given_names'],['ERIKA','ERIKA'])
    def test_unrestricted_can_mix(self):
        g=Generator(self.db,8)
        results=[g.generate(Query(format='full',gender='unrestricted')) for _ in range(100)]
        self.assertTrue(any(set(r['given_names'])=={'ERIKA','EDGAR'} for r in results))
    def test_surname_is_not_gender_filtered(self):
        self.assertEqual(Generator(self.db).generate(Query(format='surname',gender='female'))['text'],'ESPARZA')
    def test_normalized_tables(self):
        names={r[0] for r in self.db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'name_group_counts','name_sex_counts','name_year_sex_counts','sources'}.issubset(names))
        cols={r[1] for r in self.db.connection.execute('PRAGMA table_info(names)')}
        self.assertNotIn('groups_json',cols)
        self.assertEqual(self.db.connection.execute('PRAGMA foreign_key_check').fetchall(),[])
    def test_gender_filtered_in_sql(self):
        statements=[]
        self.db.connection.set_trace_callback(statements.append)
        Generator(self.db).generate(Query(format='given',gender='female'))
        self.assertTrue(any('name_sex_counts' in sql and 'SELECT' in sql for sql in statements))
    def test_invalid_gender(self):
        with self.assertRaises(ValueError):Generator(self.db).generate(Query(gender='invalid'))

    def test_two_generators_do_not_share_wrong_cohort(self):
        self.db.add_annual('EDGAR',1980,100,'F')
        self.db.commit()
        a,b=Generator(self.db,3),Generator(self.db,4)
        self.assertEqual(a.generate(Query(format='given',gender='female',birth_year_range=(2000,2000)))['text'],'ERIKA')
        self.assertEqual(b.generate(Query(format='given',gender='female',birth_year_range=(1980,1980)))['text'],'EDGAR')
        self.assertEqual(a.generate(Query(format='given',gender='female',birth_year_range=(2000,2000),component_lengths={'given':(5,5)}))['text'],'ERIKA')

    def test_explicit_compound_exception_is_order_sensitive(self):
        self.db.add_name('JOSE','given',100,{'hispanic':100},'fixture')
        self.db.add_sex('JOSE','M',100,'fixture')
        self.db.add_name('MARIA','given',100,{'hispanic':100},'fixture')
        self.db.add_sex('MARIA','F',100,'fixture')
        self.db.commit()
        g=Generator(self.db,3)
        a=g.generate(Query(format='full',given_pair=('JOSE','MARIA')))
        b=g.generate(Query(format='full',given_pair=('MARIA','JOSE')))
        self.assertEqual(a['gender'],'male')
        self.assertEqual(b['gender'],'female')
        self.assertEqual(a['given_names'],['JOSE','MARIA'])
        with self.assertRaises(NoCandidates):g.generate(Query(format='full',given_pair=('JOSE','MARIA'),gender='female'))
