# US names dataset — compact fictional-name model

This repository downloads government name aggregates, builds a compact SQLite model, and publishes it through GitHub Releases. **The output is for generating fictional names. It includes interpolation, extrapolation and fallback estimates, and is not fully representative of reality.** It must not be interpreted as a demographic research dataset.

Schema **3** keeps every source name/role record, uses three-year periods, and stores normalized name frequencies and female shares as scaled integers in a wide `names` table. Demographic counts are preserved unchanged for now. Generation code lives in [ds.python.usnames](https://github.com/lambdawalker/ds.python.usnames).

**Compatibility:** the currently released Python generator consumes schema 2 and remains pinned to `dataset-v0.2.0`. It needs a separate schema-3 reader/sampler update before using this new database. This source-repository change does not replace existing release assets or silently upgrade library users.

## Build

Python 3.11+; release CI uses Python 3.12.

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

Use shell equivalents for creating directories and copying files on Windows. `uv sync` and `uv run` are also supported. The downloader preserves the SSA browser-header fix and verifies source hashes. The build is offline: a temporary schema-2 database preserves the original observations during import, then is converted into schema 3 and deleted. Allow extra disk space during the build. Generated databases and government files are excluded from Git.

An existing output database or manifest is never overwritten. `--raw-dir` and `--output` select alternate paths. To intentionally refresh source inputs, download into a new directory with `--refresh`, review the result, and update `scripts/sources.manifest.json` for the next release.

## Stored values

`names` has one row per name/role, keeping given names and surnames distinct. It includes IDs, text, role, character length, source IDs, national count, unchanged Census demographic counts, overall female share, and two numeric columns per period:

| Column example | Meaning | Stored integer scale |
|---|---|---:|
| `frequency_1991_1993` | Name's share of the modeled given-name distribution in this period | 1,000,000,000 |
| `female_1991_1993` | Female share among occurrences of this name in this period | 10,000 |
| `female_share` | Overall female share from Census, or SSA fallback | 10,000 |

For example, stored `female_1991_1993 = 7000` means `0.7`, or 70% female. Male share is `1 - female_share`; no second column is needed. Name popularity and female share have different denominators.

The `names_normalized` SQL view exposes all share columns as fractions from 0 to 1 without duplicating stored data:

```sql
SELECT name, frequency_1991_1993, female_1991_1993
FROM names_normalized
WHERE role = 'given' AND female_1991_1993 >= 0.7;
```

`periods` stores each period's boundaries, original published SSA occurrence total, and the pre-normalization model mass. To combine periods, weight name frequencies by those original totals. `observed_total * frequency` is an approximate modeled occurrence count after estimation, not an original source count.

Buckets are anchored at 1880: 1880–1882, 1883–1885, etc. The current inputs end in 2025, so the last bucket is **2024–2025**, rather than inventing 2026 observations. There are 49 periods. Exact annual queries are not supported by this compact output; arbitrary partial-period queries require an explicit approximation in the consumer.

## Missing periods and precision

For each given name:

1. Aggregate published SSA counts into each period. Compute name frequency against the period's total, and female share against that name's male-plus-female count.
2. Fill interior gaps by linear interpolation between bucket midpoints.
3. Extrapolate beyond the first/last observed period by carrying the nearest endpoint value. A name observed in only one period gets constant values elsewhere.
4. If there are no annual observations, use a constant frequency prior based on available Census counts (overall sex counts, then weight 1, if no national total). Use overall female share, or a neutral 50% when no sex evidence exists. These are explicit modeling assumptions.
5. Renormalize frequencies across **all retained given names** in each period. Reserve one integer unit per positive name, then use largest-remainder allocation so the stored frequency sum is exactly 1,000,000,000. This keeps rare names sampleable and introduces a small documented quantization bias. Female shares are rounded to 0.01 percentage points.

`period_evidence` packs two bits per period: observed, interpolated, extrapolated or fallback. Even observed frequencies are renormalized after adding estimated names. Evidence describes the pre-normalization input, not a claim that the final stored value is an untouched observation. The manifest reports evidence totals and maximum frequency quantization error.

Surnames have no SSA birth-period observations. Their period fields remain NULL (not applicable); surname sampling uses the preserved Census counts. Missing demographic evidence also remains NULL; interpolation applies to the given-name time series, not unrelated static fields.

## Accuracy and provenance

- No names are removed. Rows represent name/role pairs, not people.
- Extrapolation can assign a modern name to an old period, or an old name to a modern period. This is intentional for fictional generation.
- SSA suppresses small cells. Within an observed name/period, an unreported sex contributes zero to the published-count ratio; this does not prove there were no real occurrences.
- SSA measures recorded births, not the living US population. Migration, deaths, later name changes and suppressed observations are not modeled.
- Census demographic groups are not linguistic or cultural origins. Unknown origins remain unknown. Group counts retain disclosure noise and are not normalized or imputed in this revision.
- Overall source-recorded sex and birth-period sex associations do not establish anyone's gender identity.
- `ALL OTHER NAMES` remains an excluded aggregate in source metadata; no individual source tokens are removed.

Original source URLs, hashes, source statistics and model settings are in the manifest and SQLite metadata. Fine-grained annual source rows are temporary build inputs, not part of the distributed model. See [the schema-3 contract](docs/dataset-contract.md).

Sources: [Census 2020 names](https://www.census.gov/topics/population/genealogy/data/2020_names.html), [SSA downloads](https://www.ssa.gov/oact/babynames/limits.html), and [SSA qualifications](https://www.ssa.gov/oact/babynames/background.html).

## Release and test

Run **Actions → Release names dataset → Run workflow**, supplying a new tag such as `dataset-v0.3.0`. Existing tags are rejected. The workflow builds, exports, checks SQLite integrity, foreign keys, retained-name count and per-period normalization, and publishes compressed data with its manifest, README, validation report and SHA-256 checksums. No database is committed to Git.

```sh
python -m unittest discover -s tests -v
```

Tests cover source import/download behavior, interpolation, extrapolation, fallback evidence, quantization, name retention, normalized SQL values, export and overwrite protection.
