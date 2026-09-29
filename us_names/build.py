"""Transform downloaded government source files into SQLite; never accesses the network."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import openpyxl
from .core import Dataset, GROUPS, VERSION

from .download import SOURCES, source_manifest

GROUP_HEADERS=(
 'NON-HISPANIC OR LATINO WHITE ALONE',
 'NON-HISPANIC OR LATINO BLACK OR AFRICAN AMERICAN ALONE',
 'NON-HISPANIC OR LATINO AMERICAN INDIAN AND ALASKA NATIVE ALONE',
 'NON-HISPANIC OR LATINO ASIAN AND NATIVE HAWAIIAN AND OTHER PACIFIC ISLANDER ALONE',
 'NON-HISPANIC OR LATINO TWO OR MORE RACES',
 'HISPANIC OR LATINO ORIGIN',
)


def import_census(db, path, role):
    """Read the nonnegative RaceHispanic workbook; fail on schema drift."""
    workbook=openpyxl.load_workbook(path,read_only=True,data_only=True)
    count=0
    try:
        rows=iter(workbook.active.values)
        header=None
        for row in rows:
            if row and row[0] == ('FIRST NAME' if role=='given' else 'LAST NAME'):
                header=list(row)
                break
        required=['FREQUENCY (COUNT)',*GROUP_HEADERS]
        if header is None or any(x not in header for x in required):
            raise ValueError(f'Unexpected Census schema: {path}')
        indices=[header.index(x) for x in GROUP_HEADERS]
        total_index=header.index('FREQUENCY (COUNT)')
        for row in rows:
            if not row[0] or not isinstance(row[total_index],(int,float)):
                continue
            name=str(row[0]).strip()
            if name == 'ALL OTHER NAMES':
                db.set_metadata('census_omitted_' + role, {'aggregate_count': row[total_index], 'reason': 'Unpublished names pooled by Census'})
                continue
            # No fictional estimates: retain six published, noise-adjusted counts.
            groups={g:float(row[i]) for g,i in zip(GROUPS,indices)}
            db.add_name(name,role,float(row[total_index]),groups,'census_2020')
            count+=1
    finally:
        workbook.close()
    return count


def import_ssa(db, path):
    """Sum published sex-specific birth counts; no claim of current population."""
    years=[]
    records=0
    with zipfile.ZipFile(path) as z:
        for filename in sorted(z.namelist()):
            match=re.fullmatch(r'yob(\d{4})\.txt',filename)
            if not match:
                continue
            year=int(match[1])
            years.append(year)
            batch=[]
            with z.open(filename) as f:
                for name,sex,count in csv.reader(io.TextIOWrapper(f,encoding='utf-8-sig')):
                    n=int(count)
                    if n < 0:
                        raise ValueError('Negative SSA count')
                    batch.append((name.upper(),year,n))
            db.connection.executemany('INSERT INTO annual VALUES (?,?,?) ON CONFLICT(name,year) DO UPDATE SET count=count+excluded.count',batch)
            records+=len(batch)
        if not years:
            raise ValueError('SSA ZIP contains no annual files')
    # Zero means no Census count available, not zero actual prevalence.
    db.connection.execute("INSERT OR IGNORE INTO names(name,role,total,groups_json,source) SELECT DISTINCT name,'given',0,'{}','ssa_national' FROM annual")
    return {'year_range':[min(years),max(years)],'raw_name_sex_year_rows':records,
            'name_year_rows':db.connection.execute('SELECT COUNT(*) FROM annual').fetchone()[0]}


def build(raw_dir, output):
    raw_dir,output=Path(raw_dir),Path(output)
    raw_dir.mkdir(parents=True,exist_ok=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        raise FileExistsError(f'{output} already exists; use a new output path')
    manifest=source_manifest(raw_dir)
    temp=output.with_suffix('.building.sqlite')
    if temp.exists():
        raise FileExistsError(f'Unfinished build exists: {temp}')
    try:
        with Dataset.create(temp) as db:
            stats={}
            for key,role in [('census_given','given'),('census_surname','surname')]:
                stats[key]=import_census(db,raw_dir/manifest[key]['file'],role)
                print(f'Imported {stats[key]:,} {role} Census names',flush=True)
            stats['ssa']=import_ssa(db,raw_dir/manifest['ssa_national']['file'])
            stats['total_tokens']=db.connection.execute('SELECT COUNT(*) FROM names').fetchone()[0]
            fingerprint=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()[:12]
            db.set_metadata('dataset_version',f'{VERSION}-{fingerprint}')
            db.set_metadata('built_at_utc',datetime.now(timezone.utc).isoformat())
            db.set_metadata('sources',manifest)
            db.set_metadata('statistics',stats)
            db.set_metadata('group_measure','published noise-adjusted counts, not linguistic origin or normalized prevalence')
            db.commit()
            db.connection.execute('ANALYZE')
            db.commit()
            metadata=db.metadata()
        temp.replace(output)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    output.with_suffix('.manifest.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return metadata


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw-dir',default='data/raw')
    p.add_argument('--output',default='data/names.sqlite')
    a=p.parse_args()
    try:
        print(json.dumps(build(a.raw_dir,a.output),indent=2))
    except (OSError, ValueError) as error:
        p.exit(2, f'Error: {error}\n')

if __name__=='__main__':main()
