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
            db.add_name(name,role,float(row[total_index]),groups,'census_given' if role=='given' else 'census_surname')
            count+=1
    finally:
        workbook.close()
    return count


def import_census_sex(db, path):
    workbook=openpyxl.load_workbook(path,read_only=True,data_only=True)
    ids=dict(db.connection.execute("SELECT name,id FROM names WHERE role='given'"))
    db.add_source('census_sex')
    count=0
    try:
        rows=iter(workbook.active.values)
        header=None
        for row in rows:
            if row and row[0]=='FIRST NAME':header=list(row);break
        if header is None or not {'MALE','FEMALE'}.issubset(header):raise ValueError('Unexpected Census sex schema')
        mi,fi=header.index('MALE'),header.index('FEMALE')
        for row in rows:
            if not row[0] or row[0]=='ALL OTHER NAMES' or not isinstance(row[mi],(int,float)):continue
            name=str(row[0]).strip()
            if name not in ids:ids[name]=db.add_name(name,'given',None,{},'census_sex')
            male,female=float(row[mi]),float(row[fi]);total=male+female
            db.connection.executemany('INSERT INTO name_sex_counts VALUES (?,?,?,?,?)',
                [(ids[name],sex,n,n/total if total else 0,'census_sex') for sex,n in [('M',male),('F',female)]])
            count+=1
    finally:workbook.close()
    return count


def import_ssa(db, path):
    """Retain the recorded sex in every annual observation; never sum it away."""
    years=[];records=0
    ids=dict(db.connection.execute("SELECT name,id FROM names WHERE role='given'"))
    db.add_source('ssa_national')
    with zipfile.ZipFile(path) as z:
        for filename in sorted(z.namelist()):
            match=re.fullmatch(r'yob(\d{4})\.txt',filename)
            if not match:continue
            year=int(match[1]);years.append(year);batch=[]
            with z.open(filename) as f:
                for name,sex,count in csv.reader(io.TextIOWrapper(f,encoding='utf-8-sig')):
                    n=int(count);name=name.upper()
                    if n<0 or sex not in ('M','F'):raise ValueError('Invalid SSA count or sex')
                    if name not in ids:ids[name]=db.add_name(name,'given',None,{},'ssa_national')
                    batch.append((ids[name],year,sex,n,'ssa_national'))
            db.connection.executemany('INSERT INTO name_year_sex_counts VALUES (?,?,?,?,?)',batch)
            records+=len(batch)
        if not years:raise ValueError('SSA ZIP contains no annual files')
    # Only names without ANY Census sex record receive SSA all-years fallback.
    db.connection.execute("""INSERT INTO name_sex_counts(name_id,sex,count,share,source_id)
        SELECT a.name_id,a.sex,SUM(a.count),0,'ssa_national' FROM name_year_sex_counts a
        WHERE NOT EXISTS(SELECT 1 FROM name_sex_counts s WHERE s.name_id=a.name_id)
        GROUP BY a.name_id,a.sex""")
    db.connection.execute("""UPDATE name_sex_counts AS s SET share=count/(SELECT SUM(t.count) FROM name_sex_counts t WHERE t.name_id=s.name_id)
        WHERE source_id='ssa_national'""")
    return {'year_range':[min(years),max(years)],'raw_name_sex_year_rows':records,
        'name_year_sex_rows':db.connection.execute('SELECT COUNT(*) FROM name_year_sex_counts').fetchone()[0]}


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
            for key,value in manifest.items():db.add_source(key,value)
            for key,role in [('census_given','given'),('census_surname','surname')]:
                stats[key]=import_census(db,raw_dir/manifest[key]['file'],role)
                print(f'Imported {stats[key]:,} {role} Census names',flush=True)
            stats['census_sex']=import_census_sex(db,raw_dir/manifest['census_sex']['file'])
            stats['ssa']=import_ssa(db,raw_dir/manifest['ssa_national']['file'])
            stats['total_tokens']=db.connection.execute('SELECT COUNT(*) FROM names').fetchone()[0]
            fingerprint=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()[:12]
            db.set_metadata('schema_version',2)
            db.set_metadata('gender_measure','Source-recorded sex counts; Census overall preferred, SSA cohort or fallback. Not individual gender identity.')
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
