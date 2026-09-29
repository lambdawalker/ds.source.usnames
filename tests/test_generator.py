import tempfile
import unittest
from pathlib import Path

from us_names import Dataset, Generator, Query, NoCandidates, SamplingExhausted
from us_names.core import char_length


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Dataset.create(Path(self.tmp.name) / 'test.sqlite')
        for name, role, count, groups in [
            ('JOSE', 'given', 900, {'hispanic': 900}),
            ('PEDRO', 'given', 100, {'hispanic': 100}),
            ('JOHN', 'given', 900, {'white': 900}),
            ('LEE', 'given', 100, {'white': 100}),
            ('GARZA', 'surname', 900, {'hispanic': 900}),
            ('RUIZ', 'surname', 100, {'hispanic': 100}),
            ('SMITH', 'surname', 1000, {'white': 1000}),
        ]:
            self.db.add_name(name, role, count, groups, 'fixture')
            if role == 'given': self.db.add_sex(name, 'M', count, 'fixture')
        self.db.add_annual('JOSE', 1980, 10)
        self.db.add_annual('PEDRO', 2000, 10)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_frequency_flag_changes_distribution(self):
        q = Query(format='given', group='hispanic')
        g = Generator(self.db, seed=4)
        weighted = sum(g.generate(q)['text'] == 'JOSE' for _ in range(2000))
        uniform = sum(g.generate(Query(format='given', group='hispanic', use_frequency_weights=False))['text'] == 'JOSE' for _ in range(2000))
        self.assertTrue(1730 < weighted < 1870)
        self.assertTrue(900 < uniform < 1100)

    def test_cultural_compatibility(self):
        g = Generator(self.db, seed=42)
        for _ in range(100):
            r = g.generate(Query())
            given, surname = r['text'].split()
            self.assertEqual(given in ('JOSE','PEDRO'), surname in ('GARZA','RUIZ'))

    def test_initials_custom_format_and_components(self):
        r = Generator(self.db, 2).generate(Query(format='{surname}, {given_initial} {middle_initial}', group='hispanic'))
        self.assertRegex(r['text'], r'^(GARZA|RUIZ), [JP]\. [JP]\.$')
        self.assertEqual(len(r['given_names']), 2)

    def test_two_given_names_and_two_surnames(self):
        r = Generator(self.db, 3).generate(Query(format='double_surname', group='hispanic'))
        self.assertEqual(len(r['given_names']), 2)
        self.assertEqual(len(r['surnames']), 2)

    def test_exact_length_after_formatting(self):
        g = Generator(self.db, 42)
        for _ in range(30):
            r = g.generate(Query(group='hispanic', min_length=10, max_length=10))
            self.assertEqual(char_length(r['text']), 10)

    def test_component_limits(self):
        r = Generator(self.db, 3).generate(Query(group='hispanic', component_lengths={'given': (5,5), 'surname': (4,4)}))
        self.assertEqual(r['text'], 'PEDRO RUIZ')

    def test_year_filter(self):
        r = Generator(self.db, 3).generate(Query(format='given', group='hispanic', birth_year_range=(2000,2000)))
        self.assertEqual(r['text'],'PEDRO')
        self.assertEqual(r['birth_year_range'], [2000,2000])

    def test_seed_reproduces_batch(self):
        a, b = Generator(self.db, 99), Generator(self.db, 99)
        self.assertEqual([a.generate() for _ in range(5)], [b.generate() for _ in range(5)])

    def test_impossible_length_is_bounded(self):
        with self.assertRaises((NoCandidates, SamplingExhausted)):
            Generator(self.db).generate(Query(min_length=100, max_length=101, max_attempts=10))

    def test_unicode_graphemes_and_output_conversion(self):
        self.assertEqual(char_length('Jose\u0301'), 4)
        self.db.add_name('JOSÉ', 'given', 1, {}, 'fixture')
        self.db.commit()
        r = Generator(self.db, 1).generate(Query(format='given', group=None, component_lengths={'given': (4,4)}, ascii_only=True, casing='lower'))
        self.assertNotIn('é', r['text'])

    def test_unknown_format_is_rejected(self):
        with self.assertRaises(ValueError):
            Generator(self.db).generate(Query(format='{nonsense}'))

    def test_invalid_range_is_rejected(self):
        with self.assertRaises(ValueError):
            Generator(self.db).generate(Query(min_length=20, max_length=10))

if __name__ == '__main__':
    unittest.main()
