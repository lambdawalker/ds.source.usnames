"""Build schema 3 from downloaded government data; never accesses the network."""
import argparse
import json
from pathlib import Path
import tempfile
from .staging import build as build_staging, import_census, import_ssa, import_census_sex
from .compact import build_compact


def build(raw_dir, output):
    output=Path(output)
    if output.exists() or output.with_suffix('.manifest.json').exists():
        raise FileExistsError(f'{output} or manifest already exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.names-build-',dir=output.parent) as tmp:
        staging=Path(tmp)/'observations.sqlite'
        build_staging(raw_dir,staging)
        return build_compact(staging,output)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir',default='data/raw')
    parser.add_argument('--output',default='data/names.sqlite')
    args=parser.parse_args()
    try: print(json.dumps(build(args.raw_dir,args.output),indent=2))
    except (OSError,ValueError) as error: parser.exit(2,f'Error: {error}\n')

if __name__=='__main__': main()
