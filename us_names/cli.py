"""Command-line generation and dataset export."""
import argparse
import csv
import gzip
import json
import sys
from pathlib import Path
from .core import Dataset, Generator, Query, FORMATS, GROUPS, NoCandidates, SamplingExhausted


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    g=sub.add_parser('generate')
    g.add_argument('--db',default='data/names.sqlite')
    g.add_argument('--count',type=int,default=10)
    g.add_argument('--seed',type=int)
    g.add_argument('--format',default='name',help='Preset or quoted {given}/{middle}/{surname}/{surname2} template; each supports _initial')
    g.add_argument('--min-length',type=int,default=1)
    g.add_argument('--max-length',type=int)
    g.add_argument('--group',choices=['auto','none',*GROUPS],default='auto')
    g.add_argument('--uniform',action='store_true')
    g.add_argument('--birth-years',nargs=2,type=int,metavar=('FROM','TO'))
    g.add_argument('--casing',choices=['source','upper','lower','title'],default='source')
    g.add_argument('--ascii',action='store_true')
    g.add_argument('--no-initial-period',action='store_true')
    g.add_argument('--jsonl',action='store_true')
    g.add_argument('--query',type=Path,help='JSON Query object; overrides query options')
    g.add_argument('--output',type=Path,help='New output file; existing files are not overwritten')
    e=sub.add_parser('export')
    e.add_argument('--db',default='data/names.sqlite')
    e.add_argument('--output',type=Path,required=True,help='New token JSONL file (.gz supported)')
    i=sub.add_parser('info')
    i.add_argument('--db',default='data/names.sqlite')
    a=p.parse_args(argv)
    try:
        with Dataset(a.db) as db:
            if a.command=='info':
                print(json.dumps(db.metadata(),indent=2))
                return
            if a.command=='export':
                opener=gzip.open if a.output.suffix=='.gz' else open
                with opener(a.output,'xt',encoding='utf-8') as f:
                    for row in db.connection.execute('SELECT * FROM names ORDER BY role,name'):
                        r=dict(row)
                        r['group_counts']=json.loads(r.pop('groups_json'))
                        r['origins']=json.loads(r.pop('origins_json'))
                        r['national_count']=r.pop('total') or None
                        f.write(json.dumps(r,ensure_ascii=False)+'\n')
                return
            if a.count < 1:
                p.error('--count must be positive')
            config=dict(format=a.format,min_length=a.min_length,max_length=a.max_length,
                group=None if a.group=='none' else a.group,use_frequency_weights=not a.uniform,
                birth_year_range=tuple(a.birth_years) if a.birth_years else None,
                casing=a.casing,ascii_only=a.ascii,initial_period=not a.no_initial_period)
            if a.query:
                config.update(json.loads(a.query.read_text(encoding='utf-8')))
            query=Query(**config)
            generator=Generator(db,a.seed)
            stream=a.output.open('x',encoding='utf-8') if a.output else sys.stdout
            try:
                for index in range(a.count):
                    result=generator.generate(query)
                    result['seed']=a.seed
                    result['index']=index
                    print(json.dumps(result,ensure_ascii=False) if a.jsonl else result['text'],file=stream)
            finally:
                if a.output:
                    stream.close()
    except (ValueError,TypeError,OSError,SamplingExhausted) as error:
        p.exit(2,f'Error: {error}\n')

if __name__=='__main__':main()
