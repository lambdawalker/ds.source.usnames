# US names dataset — source and release pipeline

This repository downloads government name aggregates, builds the normalized SQLite database, validates it, and publishes versioned GitHub Releases. **Random-name generation lives in [ds.python.usnames](https://github.com/lambdawalker/ds.python.usnames).** No generator package is installed by this project.

Download the [published datasets](https://github.com/lambdawalker/ds.source.usnames/releases), or rebuild them with the commands below. Large source files and generated databases are excluded from Git.

## Build from originals

Python 3.11+ (release CI uses 3.12). From this checkout:

```sh
python -m pip install -e .
mkdir -p data/raw
cp scripts/sources.manifest.json data/raw/sources.manifest.json
python -m us_names_source.download
python -m us_names_source.build
mkdir -p dist
python -m us_names_source.export --output dist/tokens.jsonl.gz
python scripts/package_release.py
(cd dist && sha256sum --check SHA256SUMS)
```

Windows users can create directories and copy the manifest with their shell equivalents. `uv sync` / `uv run` are also supported by the committed lockfile.

The downloader retrieves three Census workbooks and the SSA national ZIP, records their SHA-256 hashes, and reuses verified cached files. The existing browser-header fix for SSA downloads is preserved. Pinning the manifest before download requires the exact committed source snapshot. Rolling government URLs may change; a hash mismatch fails rather than accepting new data silently.

The builder is offline. It checks input hashes and workbook headers, imports normalized counts, creates indexes, and writes `data/names.sqlite` with `data/names.manifest.json`. Existing output databases are never overwritten. A failed import removes its temporary database.

To update the source snapshot intentionally, download to a new directory with `--refresh`, review the new data and manifest, then update `scripts/sources.manifest.json` before the next release. Increment the dataset version in `us_names_source/__init__.py` and the package version when appropriate. Preserve the old manifest/release for reproducibility.

```sh
python -m us_names_source.download --raw-dir data/new-raw --refresh
python -m us_names_source.build --raw-dir data/new-raw --output data/new.sqlite
```

## Publish a release

On the `main` branch, open **Actions → Release names dataset → Run workflow** and supply a new tag such as `dataset-v0.2.1`. The workflow tests the producer, downloads pinned originals, builds and exports the dataset, validates integrity and foreign keys, verifies checksums, and uploads the assets before publishing. Existing release tags are rejected. Ordinary pushes run tests without creating releases.

If uploading fails after a draft is created, inspect the draft and complete that upload or delete the failed draft/tag before retrying. Published releases must not be replaced in place.

Release assets:

- `names.sqlite.gz`: compressed schema-2 database.
- `tokens.jsonl.gz`: token records with group and overall sex counts; annual observations remain in SQLite.
- `names.manifest.json`: source URLs, hashes, versions, build time and statistics.
- `VALIDATION.json`: SQLite integrity results and table counts.
- `SHA256SUMS`: asset checksums.
- `README.md`: build instructions and data limitations.

The generator downloads these assets from this repository's releases. Its version can advance without rebuilding the data. See [the dataset contract](docs/dataset-contract.md).

## Normalized SQLite schema

| Table | Purpose and key |
|---|---|
| `names` | Integer ID, text, role, nullable Census total, stored grapheme length, source ID; unique text/role |
| `name_group_counts` | Published count per name/group; primary key `(name_id, group_id)` |
| `name_sex_counts` | Preferred overall male/female counts and derived shares per name; primary key `(name_id, sex)` |
| `name_year_sex_counts` | SSA counts retaining year and recorded sex; primary key `(name_id, year, sex)` |
| `sources` | Source IDs, URLs, filenames, SHA-256 hashes and sizes |
| `name_origin_associations` | Sourced origin labels/evidence, currently unpopulated |
| `metadata` | Version, source manifest, build time and statistics |

Counts are numeric rows with foreign keys and nonnegative checks. Group counts are no longer stored in a JSON field. `metadata` still uses JSON for descriptive information; JSON is also used for portable exports.

Indexes cover role/length, group/count, sex/share and year/sex. `share` is count divided by the sum of source sex counts for a name; it is a derived value, not a separately observed statistic.
## Sources and limitations

1. [Census 2020 name tables](https://www.census.gov/topics/population/genealogy/data/2020_names.html)
2. [Census first-name methodology](https://www2.census.gov/library/publications/decennial/2020/c2020br-13.pdf)
3. [Census surname methodology](https://www2.census.gov/library/publications/decennial/2020/c2020br-14.pdf)
4. [SSA downloads](https://www.ssa.gov/oact/babynames/limits.html)
5. [SSA qualifications](https://www.ssa.gov/oact/babynames/background.html)


Counts are approximate government aggregates. Census groups (white, black, aian, asian_nhpi, multiracial, hispanic) are not linguistic origins; the first five are non-Hispanic groups. Detailed cultural origins remain unknown rather than guessed. Group and sex totals can differ due to separate disclosure noise. No full-name, middle-name, paired-surname, or joint group/sex/year frequencies are observed.

Census's `ALL OTHER NAMES` aggregate is excluded from name tokens and retained in metadata. SSA suppresses small cells and covers births rather than all current residents; it cannot account for migration, survival or later name changes. SSA removes spaces and hyphens; uppercase matching does not restore missing accents. Rare or unusual names may remain. Source-recorded sex is not individual gender identity.

The manifest is authoritative for the exact counts and year range of each release. Source data retains its attribution; no exclusive rights to government data are claimed. No INE, INSEE or Wikidata dataset has been imported.

## Development

```sh
python -m unittest discover -s tests -v
```

Tests cover source caching, hash validation, the SSA request headers, offline builds, import columns and preservation of annual sex counts. The package namespace is `us_names_source`, distinct from the consumer's `us_names`; both can be installed in one environment without collisions.
