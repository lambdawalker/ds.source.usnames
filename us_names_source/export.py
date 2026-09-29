"""Export built tokens as JSONL, optionally gzip-compressed."""
import argparse
import gzip
import json
from pathlib import Path
from .database import Dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='data/names.sqlite')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    opener = gzip.open if args.output.suffix == '.gz' else open
    with Dataset(args.db) as db, opener(args.output, 'xt', encoding='utf-8') as out:
        for row in db.connection.execute('SELECT id FROM names ORDER BY role,name'):
            out.write(json.dumps(db.record(row[0]), ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
