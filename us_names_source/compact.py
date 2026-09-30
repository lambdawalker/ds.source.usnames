"""Schema-3 fictional-name model: wide rows, three-year periods, scaled shares."""
from __future__ import annotations
from array import array
from contextlib import closing
from datetime import datetime, timezone
from itertools import groupby
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
from . import VERSION

FREQUENCY_SCALE = 1_000_000_000
SHARE_SCALE = 10_000
GROUPS = ('white','black','aian','asian_nhpi','multiracial','hispanic')
EVIDENCE = ('observed','interpolated','extrapolated','fallback')


def fill_series(values, fallback, positions=None):
    """Linear interior interpolation; constant endpoint extrapolation; all-null fallback."""
    positions = list(range(len(values))) if positions is None else positions
    known = [i for i,v in enumerate(values) if v is not None]
    if not known:
        return [fallback]*len(values), [3]*len(values)
    result = list(values)
    flags = [0]*len(values)
    first,last = known[0],known[-1]
    for i in range(first): result[i],flags[i] = values[first],2
    for i in range(last+1,len(values)): result[i],flags[i] = values[last],2
    for a,b in zip(known,known[1:]):
        for i in range(a+1,b):
            fraction = (positions[i]-positions[a])/(positions[b]-positions[a])
            result[i] = values[a]+fraction*(values[b]-values[a])
            flags[i] = 1
    return result,flags


def quantize_weights(values, scale=FREQUENCY_SCALE):
    """Exact integer sum with one unit reserved per positive name to prevent erasure."""
    positive = [i for i,v in enumerate(values) if v>0]
    if not positive or len(positive)>scale:
        raise ValueError('Cannot quantize empty distribution or too many names')
    total = math.fsum(values)
    budget = scale-len(positive)
    result = [0]*len(values)
    fractions = []
    for i in positive:
        target = values[i]/total*budget
        floor = math.floor(target)
        result[i] = floor+1
        fractions.append((target-floor,i))
    remaining = scale-sum(result)
    for _,i in sorted(fractions,key=lambda x:(-x[0],x[1]))[:remaining]:
        result[i] += 1
    if sum(result)!=scale: raise ValueError('Quantization failed')
    return result


def encode_flags(flags):
    result = bytearray((len(flags)+3)//4)
    for i,flag in enumerate(flags): result[i//4] |= flag << (2*(i%4))
    return bytes(result)


def decode_flags(data, length):
    return [(data[i//4] >> (2*(i%4))) & 3 for i in range(length)]


def build_compact(staging, output, *, bucket_anchor=1880):
    """Convert a validated schema-2 staging DB, keeping every name/role record."""
    output = Path(output)
    manifest_path = output.with_suffix('.manifest.json')
    if output.exists() or manifest_path.exists():
        raise FileExistsError(f'{output} or its manifest already exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(Path(staging).resolve().as_uri()+'?mode=ro',uri=True)) as src:
        if src.execute('PRAGMA user_version').fetchone()[0]!=2:
            raise ValueError('Expected schema-2 staging database')
        metadata = {k:json.loads(v) for k,v in src.execute('SELECT * FROM metadata')}
        lo,hi = src.execute('SELECT MIN(year),MAX(year) FROM name_year_sex_counts').fetchone()
        if lo is None or bucket_anchor>lo: raise ValueError('Missing SSA years or anchor after first year')
        first = bucket_anchor+((lo-bucket_anchor)//3)*3
        periods = [(y,min(y+2,hi)) for y in range(first,hi+1,3)]
        positions = [(a+b)/2 for a,b in periods]
        totals = [0]*len(periods)
        for year,count in src.execute('SELECT year,SUM(count) FROM name_year_sex_counts GROUP BY year'):
            totals[(year-first)//3] += count
        rows = src.execute('SELECT id,name,role,total,char_length,source_id FROM names ORDER BY id').fetchall()
        given = [r for r in rows if r[2]=='given']
        overall = {i:(f,t) for i,f,t in src.execute("SELECT name_id,SUM(CASE WHEN sex='F' THEN count ELSE 0 END),SUM(count) FROM name_sex_counts GROUP BY name_id")}
        groups = {}
        for ident,group,count in src.execute('SELECT name_id,group_id,count FROM name_group_counts'):
            groups.setdefault(ident,{})[group] = count
        # A name with no SSA evidence gets a constant Census-based frequency prior.
        fallback_counts = [r[3] or overall.get(r[0],(0,0))[1] or 1 for r in given]
        fallback_total = math.fsum(fallback_counts)
        observations = src.execute("""SELECT name_id,(year-?)/3,SUM(count),
            SUM(CASE WHEN sex='F' THEN count ELSE 0 END)
            FROM name_year_sex_counts GROUP BY name_id,(year-?)/3 ORDER BY name_id,(year-?)/3""",(first,first,first))
        grouped = iter(groupby(observations,key=lambda r:r[0]))
        current = next(grouped,None)
        frequencies = [array('d') for _ in periods]
        female_rows = []
        evidence_rows = []
        evidence_counts = [0]*4
        for index,row in enumerate(given):
            ident = row[0]
            observations_for_name = {}
            if current is not None and current[0]==ident:
                observations_for_name = {r[1]:(r[2],r[3]) for r in current[1]}
                current = next(grouped,None)
            freq = [None]*len(periods)
            female = [None]*len(periods)
            for bucket,(total,f) in observations_for_name.items():
                if total>0 and totals[bucket]>0:
                    freq[bucket] = total/totals[bucket]
                    female[bucket] = f/total
            f,t = overall.get(ident,(0,0))
            freq,flags = fill_series(freq,fallback_counts[index]/fallback_total,positions)
            female,_ = fill_series(female,f/t if t else .5,positions)
            for bucket,value in enumerate(freq): frequencies[bucket].append(value)
            female_rows.append(array('H',(round(min(1,max(0,x))*SHARE_SCALE) for x in female)))
            evidence_rows.append(encode_flags(flags))
            for flag in flags: evidence_counts[flag]+=1
        # Added model mass is normalized away, including for observed cells.
        model_mass = [math.fsum(values) for values in frequencies]
        max_error = []
        for i,values in enumerate(frequencies):
            quantized = quantize_weights(values)
            max_error.append(max(abs(q/FREQUENCY_SCALE-v/model_mass[i]) for q,v in zip(quantized,values)))
            frequencies[i] = array('I',quantized)
        with tempfile.TemporaryDirectory(prefix='.compact-',dir=output.parent) as tmp:
            staged = Path(tmp)/'names.sqlite'
            with closing(sqlite3.connect(staged)) as dst:
                dst.execute('PRAGMA foreign_keys=ON')
                dst.execute('PRAGMA user_version=3')
                dst.execute('CREATE TABLE sources(id INTEGER PRIMARY KEY,label TEXT UNIQUE,url TEXT,filename TEXT,sha256 TEXT,bytes INTEGER)')
                source_ids = {}
                for i,record in enumerate(src.execute('SELECT * FROM sources ORDER BY id'),1):
                    source_ids[record[0]]=i
                    dst.execute('INSERT INTO sources VALUES (?,?,?,?,?,?)',(i,*record))
                dst.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                dst.execute('''CREATE TABLE periods(id INTEGER PRIMARY KEY,start_year INTEGER,end_year INTEGER,
                    observed_total INTEGER NOT NULL,model_mass REAL NOT NULL,UNIQUE(start_year,end_year))''')
                dst.executemany('INSERT INTO periods VALUES (?,?,?,?,?)',[(i,a,b,totals[i],model_mass[i]) for i,(a,b) in enumerate(periods)])
                static = ['id INTEGER PRIMARY KEY','name TEXT NOT NULL',"role TEXT NOT NULL CHECK(role IN ('given','surname'))",
                    'national_count REAL','char_length INTEGER NOT NULL','source_id INTEGER REFERENCES sources(id)',
                    'female_share INTEGER CHECK(female_share BETWEEN 0 AND 10000)',
                    'sex_source_id INTEGER REFERENCES sources(id)','period_evidence BLOB']
                static += [f'{g}_count REAL' for g in GROUPS]
                dynamic = []
                for a,b in periods:
                    dynamic += [f'frequency_{a}_{b} INTEGER CHECK(frequency_{a}_{b} BETWEEN 0 AND {FREQUENCY_SCALE})',
                                f'female_{a}_{b} INTEGER CHECK(female_{a}_{b} BETWEEN 0 AND {SHARE_SCALE})']
                dst.execute('CREATE TABLE names('+','.join(static+dynamic)+',UNIQUE(name,role))')
                sex_sources = dict(src.execute('SELECT name_id,MIN(source_id) FROM name_sex_counts GROUP BY name_id'))
                given_index = {r[0]:i for i,r in enumerate(given)}
                insert = 'INSERT INTO names VALUES ('+','.join('?' for _ in static+dynamic)+')'
                for ident,name,role,total,length,source in rows:
                    f,t = overall.get(ident,(0,0))
                    idx = given_index.get(ident)
                    data = [ident,name,role,total,length,source_ids[source],round(f/t*SHARE_SCALE) if t else None,
                            source_ids.get(sex_sources.get(ident)),evidence_rows[idx] if idx is not None else None]
                    data += [groups.get(ident,{}).get(g) for g in GROUPS]
                    for bucket in range(len(periods)):
                        data += [frequencies[bucket][idx],female_rows[idx][bucket]] if idx is not None else [None,None]
                    dst.execute(insert,data)
                dst.execute('CREATE INDEX names_role_length ON names(role,char_length,id)')
                projections = []
                for declaration in static+dynamic:
                    column = declaration.split()[0]
                    scale = FREQUENCY_SCALE if column.startswith('frequency_') else SHARE_SCALE if column.startswith('female_') else None
                    projections.append(f'{column}/{scale}.0 AS {column}' if scale else column)
                dst.execute('CREATE VIEW names_normalized AS SELECT '+','.join(projections)+' FROM names')
                # Preserve any future evidence already present in staging; currently empty.
                dst.execute('CREATE TABLE name_origin_associations(name_id INTEGER REFERENCES names(id),label TEXT,evidence TEXT,source_id INTEGER REFERENCES sources(id))')
                dst.executemany('INSERT INTO name_origin_associations VALUES (?,?,?,?)',[(i,l,e,source_ids[s]) for i,l,e,s in src.execute('SELECT * FROM name_origin_associations')])
                model = {'bucket_years':3,'bucket_anchor':bucket_anchor,'frequency_scale':FREQUENCY_SCALE,
                    'share_scale':SHARE_SCALE,'interpolation':'linear between bucket midpoints',
                    'extrapolation':'constant nearest endpoint','no_annual_frequency':'constant Census count share; sex count or 1 if no total',
                    'no_annual_female':'overall recorded female share, else neutral 0.5',
                    'normalization':'per-period sum across ALL retained given names is exactly frequency_scale',
                    'quantization':'reserve one unit per positive name, then largest remainder',
                    'evidence_codes':dict(enumerate(EVIDENCE)),
                    'evidence_encoding':'2 bits per period, low bits first; indicates pre-normalization observations',
                    'surnames':'period values not applicable (NULL); Census national and group counts retained',
                    'limitations':'For fictional-name generation. Interpolated/extrapolated values and source data do not fully represent reality. SSA observations are births, not living population.'}
                fingerprint = hashlib.sha256(json.dumps({'sources':metadata.get('sources',{}),'model':model},sort_keys=True).encode()).hexdigest()[:12]
                metadata.update(schema_version=3,dataset_version=f'{VERSION}-{fingerprint}',built_at_utc=datetime.now(timezone.utc).isoformat(),model=model)
                metadata['statistics'] = {**metadata.get('statistics',{}),'retained_names':len(rows),'given_names':len(given),
                    'dropped_names':0,'periods':len(periods),'year_range':[lo,hi],
                    'period_evidence_counts':dict(zip(EVIDENCE,evidence_counts)),
                    'max_frequency_quantization_error':max(max_error)}
                dst.executemany('INSERT INTO metadata VALUES (?,?)',[(k,json.dumps(v)) for k,v in metadata.items()])
                dst.commit()
                dst.execute('ANALYZE');dst.commit()
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or dst.execute('PRAGMA foreign_key_check').fetchall():
                    raise ValueError('Compact database failed validation')
            os.link(staged,output)
    manifest_path.write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    return metadata
