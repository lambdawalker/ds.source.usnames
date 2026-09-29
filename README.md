# US synthetic names — v0.2.0

Python name generator for synthetic ID-card tests, backed by government aggregate data. Supports frequency weighting, length constraints, initials, multiple given names and surnames, optional birth-year ranges, and a shared gender category for given names.

**Results are plausible approximations.** Broad Census groups are not detailed naming traditions or linguistic origins. Unknown origins stay unknown. Source-recorded sex is used for synthetic generation, not to infer a real person's gender identity.

## Build from original sources

Python 3.10+. Run from this directory:

```sh
python -m pip install -e .
python -m us_names.download
python -m us_names.build
python -m us_names generate --format full --count 20 --seed 42
```

The downloader retrieves three Census workbooks (given-name groups, surname groups, given-name sex) and the SSA national ZIP. It records SHA-256 hashes in `data/raw/sources.manifest.json`. Repeating it verifies and reuses cached files. `--refresh` fetches current source releases. Use a different `--raw-dir` to preserve an older snapshot.

The builder is entirely offline: it checks input hashes, validates workbook headers, normalizes the counts, creates SQLite indexes, and writes `data/names.manifest.json`. It refuses to overwrite an existing database. A failed build removes its temporary database. Schema 1 databases must be rebuilt; they are not silently interpreted as schema 2.

The source-only Git branch excludes downloaded files and generated datasets. This prepared release bundle includes `names.sqlite.gz`, `tokens.jsonl.gz`, source code, a manifest, validation report, and `SHA256SUMS`. To use the prepared SQLite file:

```sh
python -m gzip -d names.sqlite.gz
python -m us_names generate --db names.sqlite --format full --count 20
```

The Python wheel does not embed the database; supply its path when running elsewhere.

## Python API

```python
from us_names import Dataset, Generator, Query

with Dataset('data/names.sqlite') as dataset:
    generator = Generator(dataset, seed=42)
    query = Query(
        format='double_surname',
        group='hispanic',
        gender='female',
        birth_year_range=(1980, 1989),
        min_length=11,
        max_length=30,
        use_frequency_weights=True,
    )
    result = generator.generate(query)
    print(result['text'])
    print(result['given_names'], result['surnames'])
    print(result['gender'])
```

Results include the original components, final character length, selected group/gender, published counts, selected gender share, cohort counts when requested, sources, and dataset/generator versions. Origin lists are empty when unknown. The CLI adds seed and result index in JSONL mode. Reproducibility requires the same source snapshot, software/dependency versions, query, seed, and call order. Create a connection/generator per worker; instantiate after edits to the dataset.

## Gender behavior

- `gender='auto'` (default) selects one male or female category for the entire generated name.
- `gender='female'` or `'male'` explicitly selects that category.
- `gender='unrestricted'` disables the filter and permits mixed given names.
- Surnames are not filtered by sex; surname-only queries have no selected gender.
- `min_gender_share=0.05` requires at least 5% of a token's recorded uses to belong to the selected category. This is a configurable compatibility heuristic, not a claim of certainty.
- Frequency-weighted sampling favors counts for the chosen category. Uniform sampling still enforces the category and threshold.
- Names without usable sex evidence are excluded from gender-constrained generation. Missing values are not assigned guessed genders.

Without a birth-year filter, Census sex counts are preferred. Where a name has no Census sex record, an explicitly source-labeled SSA all-years aggregate supplies the association. With a year filter, eligibility and frequency use SSA sex counts for that cohort, not overall Census associations.

**Ordered compound exceptions:** `Query(format='full', given_pair=('JOSE','MARIA'))` explicitly requests the curated male compound; `('MARIA','JOSE')` requests the female compound. These two manually curated exceptions bypass individual gender thresholds only for the requested pair and mark `compound_exception=true` in the result. They still obey group, year, length and formatting constraints. No probability or population frequency is invented for these pairs; they are never automatically injected into random sampling. Other explicitly requested pairs must pass ordinary shared-gender rules. This is a narrow formatting rule, not an exhaustive compound-name dataset.

CLI examples:

```sh
python -m us_names generate --format full --gender female --count 10
python -m us_names generate --format full --gender male --birth-years 1980 1989 --count 10
python -m us_names generate --format full --uniform --count 10
python -m us_names generate --gender unrestricted --group none --format full --count 10
python -m us_names generate --format '{surname}, {given_initial} {middle_initial}' --count 10
python -m us_names generate --jsonl --count 100 --output generated.jsonl
```

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

Indexes support role/length, group, sex/share, and year/sex candidate selection. SQLite filters candidate rows before Python loads them; the generator no longer parses every token's group JSON. Source grapheme length can be filtered in SQL. Transform-dependent lengths (ASCII/case conversion) are checked after transformation. Cohort observations are aggregated into an indexed temporary table, reused for that range. Sampling pools and record caches are bounded and instance-local.

`share` in `name_sex_counts` is a derived sampling value: count divided by the sum of both source sex counts for that name. It is not a separately observed statistic. Census group and sex totals can differ due to independent disclosure noise; denominators are not mixed.

## Formats and length rules

| Preset | Template |
|---|---|
| `given` | `{given}` |
| `surname` | `{surname}` |
| `name` (default) | `{given} {surname}` |
| `full` | `{given} {middle} {surname}` |
| `double_surname` | `{given} {middle} {surname} {surname2}` |
| `middle_initial` | `{given} {middle_initial} {surname}` |
| `given_initials` | `{given_initial} {middle_initial} {surname}` |
| `initials` | `{given_initial} {middle_initial} {surname_initial}` |
| `surname_first` | `{surname}, {given} {middle_initial}` |

Each component supports `_initial`, including `{surname2_initial}`. Custom literals/separators are preserved. Two given components and two surname components are supported. The slot `middle` means a second given component; it does not impose a universal naming tradition. Multiword source components stay intact; their initial is the first visible character. Repeated placeholders use the same sampled component.

Length limits are inclusive. “More than 10 and fewer than 20” means 11–19. Count Unicode extended grapheme clusters, including spaces and punctuation, after casing, ASCII folding and initial formatting. Font width is not modeled. Full components can have separate bounds: `component_lengths={'given': (4,8), 'surname': (5,12)}`. These apply before replacing a component by an initial.

Defaults: `min_length=1`, `max_length=None`, `component_lengths={}`, `use_frequency_weights=True`, `group='auto'`, `min_group_share=0.05`, `gender='auto'`, `min_gender_share=0.05`, `given_pair=None`, `birth_year_range=None`, `casing='source'`, `ascii_only=False`, `initial_period=True`, `max_attempts=10000`.

Use `--query query.json` for all API options; JSON keys override CLI query options. `--group none` disables group compatibility. `--no-initial-period` removes periods. `--casing` accepts source, upper, lower, title. ASCII folding is lossy character removal, not linguistic transliteration; mechanical title casing may be inappropriate for some names.

`NoCandidates` means no eligible token pools. `SamplingExhausted` means rejection sampling found no final-length match within the attempt budget; it does not prove the query impossible. No truncation or silent gender relaxation occurs. Duplicate names/components are possible. Failed CLI batches can leave partial output; existing output files are never overwritten.

## Frequency model and limitations

For a specified Census group, eligibility requires the group's count to represent at least `min_group_share` of that token's national count. Counts are not linguistic-origin probabilities. Census groups are white, black, aian, asian_nhpi, multiracial, hispanic. The first five denote non-Hispanic groups; Asian and Pacific Islander categories are combined and cannot distinguish individual naming traditions.

Without a cohort, weighted given-name sampling uses national count (or selected group count) multiplied by the selected sex share. With a cohort, it uses SSA counts for the selected sex and years, multiplied by the Census group share when enabled. These are approximations combining separate marginal tables; joint group/sex/year counts are not available. Surnames use Census counts.

Auto mode chooses among eligible group/gender combinations using the first component's eligible mass, then samples components within that combination. Uniform mode gives equal probability to eligible tokens within a combination. Overlapping groups and sex associations mean unconditional token probabilities need not be uniform. Use both `group=None` and `gender='unrestricted'` for globally uniform token sampling. Final-length rejection conditions the distribution on the requested constraints.

A name's group composition is not its prevalence within the entire group. We preserve source counts rather than inventing population denominators. This release does not establish full-name joint frequencies, middle-name distributions, paired-surname frequencies, or detailed cultural origins. Gender consistency reduces clearly implausible combinations but does not make every name culturally plausible.

Census counts include disclosure noise; SSA suppresses small cells. `ALL OTHER NAMES` is excluded from tokens and retained only as metadata. SSA covers US births, not all current residents, and cannot account for migration, survival or later name changes. It removes spaces and hyphens; uppercase matching does not restore these or missing accents. Rare or unusual source entries may remain. Some names used by both sexes remain eligible for both categories. Requested year ranges use available published observations only. Names are not guaranteed unique or unlike real names.

## Sources and rebuild

1. [Census 2020 name tables](https://www.census.gov/topics/population/genealogy/data/2020_names.html)
2. [Census first-name methodology](https://www2.census.gov/library/publications/decennial/2020/c2020br-13.pdf)
3. [Census surname methodology](https://www2.census.gov/library/publications/decennial/2020/c2020br-14.pdf)
4. [SSA downloads](https://www.ssa.gov/oact/babynames/limits.html)
5. [SSA qualifications](https://www.ssa.gov/oact/babynames/background.html)

The validated snapshot contains 270,062 text/role records, 53,615 Census first-name group rows, 156,621 Census surname group rows, 53,615 Census first-name sex rows, and 2,181,032 SSA name/year/sex observations across 1880–2025. Source data retains its attribution; no exclusive rights to government data are claimed. Source hashes and build date are included in the manifest. No INE, INSEE or Wikidata dataset has been imported.

```sh
python -m us_names.download --refresh
python -m us_names.build --output data/rebuilt.sqlite
python -m us_names export --db data/rebuilt.sqlite --output data/tokens.jsonl.gz
python -m unittest discover -s tests -v
```

The export includes all available group and overall sex counts per token; annual observations remain in SQLite. Test fixtures contain deliberately simplified counts and are not demographic estimates. Source-only Git publishing and a GitHub Release upload are separate steps; this prepared bundle has not been uploaded as a Release.
