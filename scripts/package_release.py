"""Validate and package the database rebuilt by the release workflow."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

root = Path(__file__).resolve().parents[1]
out = root / 'dist'
out.mkdir(exist_ok=True)
manifest = json.loads((root / 'data/names.manifest.json').read_text())
expected = json.loads((root / 'scripts/sources.manifest.json').read_text())
if manifest['sources'] != expected:
    raise RuntimeError('Source snapshot does not match release pins')
with sqlite3.connect(root / 'data/names.sqlite') as db:
    integrity = db.execute('PRAGMA integrity_check').fetchall()
    foreign_keys = db.execute('PRAGMA foreign_key_check').fetchall()
    if integrity != [('ok',)] or foreign_keys:
        raise RuntimeError(f'Database validation failed: {integrity}, {foreign_keys}')
    counts = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
              for table in ('names', 'name_group_counts', 'name_sex_counts', 'name_year_sex_counts')}
with (root / 'data/names.sqlite').open('rb') as source:
    with (out / 'names.sqlite.gz').open('wb') as target:
        with gzip.GzipFile(filename='', fileobj=target, mode='wb', mtime=0) as compressed:
            shutil.copyfileobj(source, compressed)
shutil.copy2(root / 'data/names.manifest.json', out)
shutil.copy2(root / 'README.md', out)
(out / 'VALIDATION.json').write_text(json.dumps({'integrity_check': 'ok', 'foreign_key_violations': 0, 'counts': counts}, indent=2) + '\n')
lines = []
for path in sorted(out.iterdir()):
    if path.is_file() and path.name != 'SHA256SUMS':
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        lines.append(f'{digest}  {path.name}\n')
(out / 'SHA256SUMS').write_text(''.join(lines))
print(json.dumps(counts))
