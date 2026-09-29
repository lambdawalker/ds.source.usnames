"""Download official source files without building a database."""
from __future__ import annotations
import argparse
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

BASE = 'https://www2.census.gov/topics/genealogy/2020surnames/'
SOURCES = {
    'census_sex': BASE + 'Names2020_FirstNames_Sex.xlsx',
    'census_given': BASE + 'Names2020_FirstNames_RaceHispanic.xlsx',
    'census_surname': BASE + 'Names2020_LastNames_RaceHispanic.xlsx',
    'ssa_national': 'https://www.ssa.gov/oact/babynames/names.zip',
}
MANIFEST = 'sources.manifest.json'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
}


def _describe(path, url):
    if not path.is_file():
        raise FileNotFoundError(f'{path} is missing; run python -m us_names_source.download first')
    if not zipfile.is_zipfile(path):
        raise ValueError(f'{path} is not a valid ZIP/XLSX file; download it again with --refresh')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return {'url': url, 'file': path.name, 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def source_manifest(raw_dir, sources=None):
    """Inspect local files, checking saved hashes when a manifest exists. No network."""
    raw_dir = Path(raw_dir)
    sources = SOURCES if sources is None else sources
    saved_path = raw_dir / MANIFEST
    saved = json.loads(saved_path.read_text(encoding='utf-8')) if saved_path.exists() else None
    manifest = {}
    for key, url in sources.items():
        record = _describe(raw_dir / url.rsplit('/', 1)[1], url)
        if saved is not None and saved.get(key) != record:
            raise ValueError(f'Source mismatch for {key}; use --refresh to download a new source snapshot')
        manifest[key] = record
    return manifest


def download_sources(raw_dir='data/raw', refresh=False, sources=None):
    """Cache downloads and record SHA-256. --refresh explicitly fetches current releases."""
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    sources = SOURCES if sources is None else sources
    manifest = {}
    saved_path = raw_dir / MANIFEST
    saved = json.loads(saved_path.read_text(encoding='utf-8')) if saved_path.exists() else None
    for key, url in sources.items():
        path = raw_dir / url.rsplit('/', 1)[1]
        if refresh or not path.exists():
            temp = path.with_suffix(path.suffix + '.part')
            try:
                print(f'Downloading {key}: {url}', flush=True)
                request = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(request, timeout=60) as response, temp.open('wb') as stream:
                    while block := response.read(1024 * 1024):
                        stream.write(block)
                record = _describe(temp, url)
                record['file'] = path.name
                if not refresh and saved is not None and saved.get(key) != record:
                    raise ValueError(f'Source changed for {key}; rerun with --refresh to accept current releases')
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)
        record = _describe(path, url)
        if not refresh and saved is not None and saved.get(key) != record:
            raise ValueError(f'Cached source mismatch for {key}; rerun with --refresh')
        manifest[key] = record
    temporary_manifest = saved_path.with_suffix('.json.part')
    temporary_manifest.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    temporary_manifest.replace(saved_path)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', default='data/raw')
    parser.add_argument('--refresh', action='store_true', help='Replace cached inputs with current official releases')
    args = parser.parse_args()
    try:
        print(json.dumps(download_sources(args.raw_dir, args.refresh), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, f'Error: {error}\n')

if __name__ == '__main__':
    main()
