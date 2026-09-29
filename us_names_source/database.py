"""Normalized version-2 SQLite storage."""
import json
import sqlite3
import unicodedata
from pathlib import Path
import regex

SCHEMA_VERSION = 2

class Dataset:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f'{path}: build the dataset first')
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys=ON')
        if self.connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
            self.close()
            raise ValueError('Dataset schema is incompatible; rebuild with us_names_source.build (schema 2)')

    @classmethod
    def create(cls, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb'):
            pass
        c = sqlite3.connect(path)
        c.executescript('''
        PRAGMA foreign_keys=ON;
        PRAGMA user_version=2;
        CREATE TABLE sources(id TEXT PRIMARY KEY, url TEXT, filename TEXT, sha256 TEXT, bytes INTEGER);
        CREATE TABLE names(
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('given','surname')),
          total REAL CHECK(total>=0), char_length INTEGER NOT NULL CHECK(char_length>0),
          source_id TEXT NOT NULL REFERENCES sources(id), UNIQUE(name,role));
        CREATE INDEX names_role_length ON names(role,char_length,id);
        CREATE TABLE name_group_counts(
          name_id INTEGER NOT NULL REFERENCES names(id), group_id TEXT NOT NULL,
          count REAL NOT NULL CHECK(count>=0), source_id TEXT NOT NULL REFERENCES sources(id),
          PRIMARY KEY(name_id,group_id)) WITHOUT ROWID;
        CREATE INDEX group_candidates ON name_group_counts(group_id,count,name_id);
        CREATE TABLE name_sex_counts(
          name_id INTEGER NOT NULL REFERENCES names(id), sex TEXT NOT NULL CHECK(sex IN ('M','F')),
          count REAL NOT NULL CHECK(count>=0), share REAL NOT NULL DEFAULT 0 CHECK(share BETWEEN 0 AND 1),
          source_id TEXT NOT NULL REFERENCES sources(id), PRIMARY KEY(name_id,sex)) WITHOUT ROWID;
        CREATE INDEX sex_candidates ON name_sex_counts(sex,share,name_id);
        CREATE TABLE name_year_sex_counts(
          name_id INTEGER NOT NULL REFERENCES names(id), year INTEGER NOT NULL,
          sex TEXT NOT NULL CHECK(sex IN ('M','F')), count INTEGER NOT NULL CHECK(count>=0),
          source_id TEXT NOT NULL REFERENCES sources(id), PRIMARY KEY(name_id,year,sex)) WITHOUT ROWID;
        CREATE INDEX year_sex_candidates ON name_year_sex_counts(year,sex,name_id,count);
        CREATE TABLE name_origin_associations(
          name_id INTEGER NOT NULL REFERENCES names(id), label TEXT NOT NULL,
          evidence TEXT NOT NULL, source_id TEXT NOT NULL REFERENCES sources(id),
          PRIMARY KEY(name_id,label,source_id)) WITHOUT ROWID;
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        c.close()
        return cls(path)

    def add_source(self, source, metadata=None):
        m = metadata or {}
        self.connection.execute('INSERT OR IGNORE INTO sources VALUES (?,?,?,?,?)',
            (source,m.get('url'),m.get('file'),m.get('sha256'),m.get('bytes')))

    def add_name(self, name, role, total, groups, source, origins=None):
        name = unicodedata.normalize('NFC',name)
        if not name or role not in ('given','surname') or (total is not None and total<0) or any(v<0 for v in groups.values()):
            raise ValueError('Invalid name or counts')
        self.add_source(source)
        cursor=self.connection.execute('INSERT INTO names(name,role,total,char_length,source_id) VALUES (?,?,?,?,?)',
            (name,role,total or None,len(regex.findall(r'\X',name)),source))
        ident=cursor.lastrowid
        self.connection.executemany('INSERT INTO name_group_counts VALUES (?,?,?,?)',[(ident,g,n,source) for g,n in groups.items()])
        for origin in origins or []:
            self.connection.execute('INSERT INTO name_origin_associations VALUES (?,?,?,?)',
                (ident,origin['label'],origin.get('evidence','unknown'),source))
        return ident

    def name_id(self, name, role='given'):
        row=self.connection.execute('SELECT id FROM names WHERE name=? AND role=?',(name,role)).fetchone()
        if row is None:raise ValueError(f'Unknown {role}: {name}')
        return row[0]

    def add_sex(self, name, sex, count, source):
        self.add_source(source)
        ident=self.name_id(name)
        self.connection.execute('INSERT OR REPLACE INTO name_sex_counts VALUES (?,?,?,0,?)',(ident,sex,count,source))
        self.connection.execute('UPDATE name_sex_counts SET share=COALESCE(count/NULLIF((SELECT SUM(count) FROM name_sex_counts WHERE name_id=?),0),0) WHERE name_id=?',(ident,ident))

    def add_annual(self, name, year, count, sex='M', source='ssa_national'):
        self.add_source(source)
        self.connection.execute('INSERT INTO name_year_sex_counts VALUES (?,?,?,?,?) ON CONFLICT(name_id,year,sex) DO UPDATE SET count=count+excluded.count',
            (self.name_id(name),year,sex,count,source))

    def record(self, ident):
        r=dict(self.connection.execute('SELECT * FROM names WHERE id=?',(ident,)).fetchone())
        return {'id':r['id'],'source_text':r['name'],'role':r['role'],'national_count':r['total'],
            'source':r['source_id'],
            'group_counts':dict(self.connection.execute('SELECT group_id,count FROM name_group_counts WHERE name_id=?',(ident,))),
            'sex_counts':{x['sex']:{'count':x['count'],'share':x['share'],'source':x['source_id']} for x in self.connection.execute('SELECT * FROM name_sex_counts WHERE name_id=?',(ident,))},
            'origins':[dict(x) for x in self.connection.execute('SELECT label,evidence,source_id FROM name_origin_associations WHERE name_id=?',(ident,))]}

    def set_metadata(self,key,value):
        self.connection.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(key,json.dumps(value)))
    def metadata(self):
        return {r[0]:json.loads(r[1]) for r in self.connection.execute('SELECT * FROM metadata')}
    def commit(self):self.connection.commit()
    def close(self):self.connection.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
