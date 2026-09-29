"""Seeded name generation from source-labelled aggregate data."""
from __future__ import annotations
import bisect
import json
import random
import sqlite3
import string
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import regex

VERSION = '0.1.0'
GROUPS = ('white', 'black', 'aian', 'asian_nhpi', 'multiracial', 'hispanic')
FORMATS = {
    'given': '{given}', 'surname': '{surname}', 'name': '{given} {surname}',
    'full': '{given} {middle} {surname}',
    'double_surname': '{given} {middle} {surname} {surname2}',
    'middle_initial': '{given} {middle_initial} {surname}',
    'given_initials': '{given_initial} {middle_initial} {surname}',
    'initials': '{given_initial} {middle_initial} {surname_initial}',
    'surname_first': '{surname}, {given} {middle_initial}',
}
COMPONENTS = ('given', 'middle', 'surname', 'surname2')


def char_length(text):
    return len(regex.findall(r'\X', text))


def transform(text, query):
    text = unicodedata.normalize('NFC', text)
    if query.ascii_only:
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    return {'upper': str.upper, 'lower': str.lower, 'title': str.title}.get(query.casing, lambda x:x)(text)


class NoCandidates(ValueError):
    """No eligible tokens."""


class SamplingExhausted(RuntimeError):
    """Attempt limit reached; this does NOT prove the query impossible."""


@dataclass(frozen=True)
class Query:
    format: str = 'name'
    min_length: int = 1
    max_length: int | None = None
    component_lengths: dict[str, tuple[int, int | None]] = field(default_factory=dict)
    use_frequency_weights: bool = True
    group: str | None = 'auto'
    min_group_share: float = 0.05
    birth_year_range: tuple[int, int] | None = None
    casing: str = 'source'
    ascii_only: bool = False
    initial_period: bool = True
    max_attempts: int = 10000


class Dataset:
    """SQLite dataset; use as a context manager to close it."""
    def __init__(self, path):
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f'{path}: build the dataset first')
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row

    @classmethod
    def create(cls, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(path)
        c = sqlite3.connect(path)
        c.executescript('''
            CREATE TABLE names (name TEXT NOT NULL, role TEXT NOT NULL, total REAL NOT NULL,
              groups_json TEXT NOT NULL, source TEXT NOT NULL,
              origins_json TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(name, role));
            CREATE TABLE annual (name TEXT NOT NULL, year INTEGER NOT NULL, count INTEGER NOT NULL,
              PRIMARY KEY(name, year)) WITHOUT ROWID;
            CREATE INDEX annual_year ON annual(year);
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        c.close()
        return cls(path)

    def add_name(self, name, role, total, groups, source, origins=None):
        if role not in ('given','surname') or not name or total < 0 or any(v < 0 for v in groups.values()):
            raise ValueError('Invalid name record or negative counts')
        self.connection.execute('INSERT INTO names VALUES (?,?,?,?,?,?)',
            (unicodedata.normalize('NFC', name), role, total, json.dumps(groups), source, json.dumps(origins or [])))

    def add_annual(self, name, year, count):
        if count < 0:
            raise ValueError('Negative annual count')
        self.connection.execute('INSERT INTO annual VALUES (?,?,?) ON CONFLICT(name,year) DO UPDATE SET count=count+excluded.count', (name, year, count))

    def set_metadata(self, key, value):
        self.connection.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(key,json.dumps(value)))

    def metadata(self):
        return {r['key']: json.loads(r['value']) for r in self.connection.execute('SELECT * FROM metadata')}

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Generator:
    """Single-threaded, seeded generator; instantiate after dataset edits.

    Create one instance per worker. Sampling pools are cached for batches.
    """
    def __init__(self, dataset, seed=None):
        self.dataset, self.seed = dataset, seed
        self.random = random.Random(seed)
        self.rows = {'given': [], 'surname': []}
        for r in dataset.connection.execute('SELECT * FROM names ORDER BY role,name'):
            record = dict(r)
            record['groups'] = json.loads(record.pop('groups_json'))
            record['origins'] = json.loads(record.pop('origins_json'))
            self.rows[record['role']].append(record)
        self.dataset_version = dataset.metadata().get('dataset_version', 'unversioned')

    @lru_cache(maxsize=16)
    def _annual(self, years):
        return dict(self.dataset.connection.execute('SELECT name,SUM(count) FROM annual WHERE year BETWEEN ? AND ? GROUP BY name', years))

    @lru_cache(maxsize=128)
    def _pool(self, role, group, share, years, weighted, lower, upper, casing, ascii_only):
        annual = self._annual(years) if years and role == 'given' else None
        q = Query(casing=casing, ascii_only=ascii_only)
        entries, cumulative, mass = [], [], 0.0
        for row in self.rows[role]:
            total = row['total']
            gc = row['groups'].get(group, 0) if group else total
            if group and (not total or gc <= 0 or gc / total < share):
                continue
            if annual is not None and row['name'] not in annual:
                continue
            rendered = transform(row['name'], q)
            size = char_length(rendered)
            if not rendered or size < lower or (upper is not None and size > upper):
                continue
            # Product approximation: cohort frequency × Census group share.
            w = annual[row['name']] * (gc / total if group else 1) if annual is not None else gc
            if weighted and w <= 0:
                continue
            mass += w if weighted else 1
            entries.append((row, rendered))
            cumulative.append(mass)
        return entries, cumulative

    def _prepare(self, q):
        if q.min_length < 0 or (q.max_length is not None and q.max_length < q.min_length):
            raise ValueError('Invalid inclusive length range')
        if q.max_attempts < 1 or not 0 <= q.min_group_share <= 1:
            raise ValueError('Invalid attempt limit or group share')
        if q.casing not in ('source','upper','lower','title'):
            raise ValueError('Unknown casing')
        if q.group not in (None,'auto',*GROUPS):
            raise ValueError(f'Unknown group: {q.group}')
        if q.birth_year_range and (len(q.birth_year_range) != 2 or q.birth_year_range[0] > q.birth_year_range[1]):
            raise ValueError('Invalid birth year range')
        template = FORMATS.get(q.format, q.format)
        fields = []
        for literal, name, spec, conversion in string.Formatter().parse(template):
            if name is None:
                continue
            if name.removesuffix('_initial') not in COMPONENTS or spec or conversion:
                raise ValueError(f'Unsupported template field: {name}')
            fields.append(name)
        if not fields:
            raise ValueError('Format must contain a name placeholder or be a preset')
        components = tuple(c for c in COMPONENTS if c in fields or c+'_initial' in fields)
        for key, bounds in q.component_lengths.items():
            if key not in components or len(bounds) != 2 or bounds[0] < 0 or (bounds[1] is not None and bounds[1] < bounds[0]):
                raise ValueError(f'Invalid component length: {key}')
        years = tuple(q.birth_year_range) if q.birth_year_range else None
        options = []
        for group in (GROUPS if q.group == 'auto' else [q.group]):
            pools = {}
            for c in components:
                low, high = q.component_lengths.get(c, (1,None))
                pool = self._pool('given' if c in ('given','middle') else 'surname',group,q.min_group_share,years,q.use_frequency_weights,low,high,q.casing,q.ascii_only)
                if not pool[0]:
                    break
                pools[c] = pool
            else:
                options.append((group, pools, pools[components[0]][1][-1]))
        if not options:
            raise NoCandidates('No eligible tokens for all components; relax group, cohort or component limits')
        return template, components, options

    def generate(self, query=None):
        q = query or Query()
        key = json.dumps(q.__dict__,sort_keys=True)
        if not hasattr(self,'_prepared') or self._prepared[0] != key:
            self._prepared = key, self._prepare(q)
        template, components, options = self._prepared[1]
        for _ in range(q.max_attempts):
            group, pools, _ = self.random.choices(options, weights=[x[2] for x in options], k=1)[0]
            values, selected = {}, {}
            for c in components:
                rows, cumulative = pools[c]
                index = bisect.bisect_right(cumulative, self.random.random()*cumulative[-1])
                record, rendered = rows[index]
                selected[c] = record, rendered
                values[c] = rendered
                values[c+'_initial'] = regex.findall(r'\X',rendered)[0] + ('.' if q.initial_period else '')
            text = template.format_map(values)
            size = char_length(text)
            if size < q.min_length or (q.max_length is not None and size > q.max_length):
                continue
            details = {}
            for c,(record,rendered) in selected.items():
                details[c] = {
                    'text': rendered, 'source_text': record['name'], 'role': record['role'],
                    'source': record['source'], 'national_count': record['total'] or None,
                    'group_counts': record['groups'], 'origins': record['origins'],
                }
                if q.birth_year_range and record['role'] == 'given':
                    details[c]['cohort_birth_count'] = self._annual(tuple(q.birth_year_range))[record['name']]
            return {
                'text': text, 'length': size,
                'given_names': [selected[c][1] for c in ('given','middle') if c in selected],
                'surnames': [selected[c][1] for c in ('surname','surname2') if c in selected],
                'components': details, 'group': group,
                'birth_year_range': list(q.birth_year_range) if q.birth_year_range else None,
                'use_frequency_weights': q.use_frequency_weights,
                'generator_version': VERSION, 'dataset_version': self.dataset_version,
            }
        raise SamplingExhausted(f'No result after {q.max_attempts} attempts; widen length bounds or raise max_attempts. This does not prove no match exists.')
