"""Export schema-3 fictional-name model with decoded shares in [0,1]."""
import argparse
from contextlib import closing
import gzip
import json
from pathlib import Path
import sqlite3
from .compact import FREQUENCY_SCALE, SHARE_SCALE, EVIDENCE, decode_flags


def iter_records(db):
    if db.execute('PRAGMA user_version').fetchone()[0]!=3:
        raise ValueError('Expected schema 3')
    db.row_factory=sqlite3.Row
    periods=db.execute('SELECT * FROM periods ORDER BY id').fetchall()
    sources={r['id']:r['label'] for r in db.execute('SELECT id,label FROM sources')}
    for row in db.execute('SELECT * FROM names ORDER BY role,name'):
        record=dict(row)
        evidence=record.pop('period_evidence')
        flags=decode_flags(evidence,len(periods)) if evidence is not None else None
        record['source']=sources[record.pop('source_id')]
        record['sex_source']=sources.get(record.pop('sex_source_id'))
        if record['female_share'] is not None:record['female_share']/=SHARE_SCALE
        record['periods']={}
        for i,p in enumerate(periods):
            label=f"{p['start_year']}_{p['end_year']}"
            freq=record.pop('frequency_'+label)
            female=record.pop('female_'+label)
            if freq is not None:
                record['periods'][label]={'frequency':freq/FREQUENCY_SCALE,'female_share':female/SHARE_SCALE,
                    'evidence':EVIDENCE[flags[i]]}
        yield record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default='data/names.sqlite')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    opener=gzip.open if args.output.suffix=='.gz' else open
    with closing(sqlite3.connect(Path(args.db).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        with opener(args.output,'xt',encoding='utf-8') as out:
            for record in iter_records(db):out.write(json.dumps(record,ensure_ascii=False)+'\n')

if __name__=='__main__':main()
