# US synthetic names — Python starter release

Generate plausible synthetic names for ID-card layout and parsing tests. This source-only repository contains a Python API, command-line generator, separate download and SQLite build scripts, and tests. Government data is downloaded and processed locally.

**This is an approximation, not an exact model of US identities.** Initial compatibility uses six broad Census population groups. Detailed language/cultural origin enrichment is not populated yet: an empty `origins` list means unknown. Broad race/Hispanic-origin categories must not be presented as linguistic origins.

## Quick start

Python 3.10 or newer. From the repository root:

```sh
python -m pip install -e .
python -m us_names.download
python -m us_names.build
python -m us_names generate --count 10 --seed 42 --min-length 11 --max-length 19
python -m us_names generate --format double_surname --group hispanic --count 10
python -m us_names generate --format middle_initial --birth-years 1980 1989 --count 10
python -m us_names generate --format given --uniform --count 10
python -m us_names generate --format '{surname}, {given_initial} {middle_initial}' --count 10
python -m us_names generate --jsonl --count 100 --output generated.jsonl
```

The download step fetches Census given names, Census surnames, and SSA annual names into `data/raw`, recording SHA-256 checksums in `sources.manifest.json`. The build step verifies those hashes and creates `data/names.sqlite` entirely offline. Internet access is needed only for dependency installation and source downloads. The data is a project asset, not installed inside the Python wheel. Supply `--db /path/to/names.sqlite` when running elsewhere. Command examples work in bash and PowerShell; use ordinary single quotes around custom templates.

## Python API

```python
from us_names import Dataset, Generator, Query

with Dataset('data/names.sqlite') as dataset:
    generator = Generator(dataset, seed=42)
    query = Query(
        format='double_surname',
        group='hispanic',
        min_length=11,
        max_length=30,
        birth_year_range=(1980, 1989),
        use_frequency_weights=True,
    )
    for _ in range(10):
        result = generator.generate(query)
        print(result['text'], result['given_names'], result['surnames'])
```

Every result includes the formatted text, length, full components (even when displayed as initials), selected population group, source counts, origin metadata, cohort range, and dataset/generator versions. CLI JSONL adds the seed and batch index. Duplicate outputs are allowed. Reproducibility requires the same dataset snapshot, query, seed, package/dependency versions and call order. Create a separate dataset connection and generator per thread/process. Instantiate a generator after dataset edits; its pools are cached.

## Formats

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

Custom templates accept `given`, `middle`, `surname`, `surname2`, and each field's `_initial` variant. `{surname2_initial}` is supported. Literals, punctuation, and separators are preserved. `{{` and `}}` escape literal braces; Python conversion and format specifiers are rejected.

`middle` is a convenient slot name for a second given component, not a claim that every tradition uses middle names. Selecting `double_surname` explicitly requests two given components and two surname components. Formats are not automatically inferred from race or ancestry. A component containing spaces is kept intact; its initial is its first visible character. Use two separate slots when separate initials are wanted. Repeated uses of a placeholder refer to the same sampled component. Up to two given components and two surname components are supported in this release; arbitrary-length lists are a future extension.

## Defaults and constraints

| Query option | Default | Meaning |
|---|---|---|
| `format` | `name` | Preset or custom template |
| `min_length` | `1` | Inclusive final character minimum |
| `max_length` | `None` | No maximum |
| `component_lengths` | `{}` | Optional full-component inclusive limits |
| `use_frequency_weights` | `True` | Frequency-weight eligible tokens |
| `group` | `auto` | Select a shared broad Census group |
| `min_group_share` | `0.05` | Group must account for at least 5% of that token's Census count |
| `birth_year_range` | `None` | Optional inclusive SSA birth years |
| `casing` | `source` | Also `upper`, `lower`, `title` |
| `ascii_only` | `False` | Optional lossy ASCII folding |
| `initial_period` | `True` | Period after each initial |
| `max_attempts` | `10000` | Bounded rejection sampling |

“More than 10 and fewer than 20” is `min_length=11, max_length=19`.

Length counts Unicode extended grapheme clusters (visible characters), including spaces and punctuation, **after** case conversion, ASCII folding, and initial formatting. Font width and rendered fit belong in the card renderer. ASCII folding removes unsupported characters; it is not linguistic transliteration. Source casing is usually uppercase. Title casing is mechanical and may be incorrect for names such as McDonald or particles.

Per-component limits apply to the transformed **full** component before replacing it by an initial:

```python
Query(component_lengths={'given': (4, 8), 'surname': (5, 12)})
```

Pass a JSON object with Query field names through `--query query.json` to access all options; its keys override CLI query options. Use `group=null` in JSON or `--group none` to disable compatibility. Uniform mode (`--uniform`) keeps compatibility enabled unless it is separately disabled.

No eligible token pool raises `NoCandidates`. Rejection sampling reaching its attempt limit raises `SamplingExhausted`: this means **no match was found within the budget**, not that no valid combination exists. Very narrow length queries may need more attempts. Nothing is silently truncated. CLI errors exit with code 2. A failed batch can leave partial output; writes never overwrite an existing output path.

## What compatibility and frequency mean

Census groups are `white`, `black`, `aian`, `asian_nhpi`, `multiracial`, and `hispanic`. The first five are non-Hispanic groups; `asian_nhpi` combines Asian, Native Hawaiian and other Pacific Islander responses. See the source methodology for definitions.

For a chosen group, tokens are eligible when their group count is positive and their group share meets `min_group_share`. Weighted sampling uses the published group count. This 5% cutoff is an explicit heuristic to reduce weak associations; it is configurable and is not evidence of linguistic origin.

With `group='auto'`, select a group using the total eligible mass of the first generated component as a proxy mixture, then sample every component within it. This is **not** a calibrated population model. Uniform mode makes tokens equally likely within the selected group and uses eligible-token counts for the group mixture. Because groups overlap, uniform-with-compatibility does not guarantee equal unconditional probability for all dataset tokens. Use `group=None` for global uniform token sampling.

The generator rejects complete names outside the requested final length. Accepted results follow the resulting distribution conditioned on the constraints; filters necessarily change the original distribution. Components are independent given the selected group and filters; duplicate components are possible.

For a birth-year range, sum SSA birth counts across the selected years. Without a group, use those counts directly. With a group, use **SSA cohort count × Census group share** as an estimated weight. Surnames retain Census frequencies. This combines different sources and is not an observed joint culture/year frequency. Ages are supported through birth years in this release; there is no age-to-year convenience argument yet.

`group_counts` stores counts, not a normalized 0–1 origin probability. A name can be common in multiple groups. Dividing a group count by that name's total gives group composition among people with the name; it does not give prevalence among all members of the group. We do not manufacture group prevalence denominators from these name tables.

## Data, sources and provenance

Locally generated files (excluded from Git):

- `data/raw/`: original downloads and their checksum manifest.
- `data/names.sqlite`: `names`, `annual`, `metadata` tables.
- `data/tokens.jsonl.gz`: optional portable token export generated with `python -m us_names export --output data/tokens.jsonl.gz`; annual history remains in SQLite.
- `data/names.manifest.json`: source URLs, byte counts, SHA-256 checksums, build time, row counts and dataset version.
- `examples/`: generated examples and a complete query file.

Census 2020 provides 53,615 given-name rows and 156,621 surname rows after removing the `ALL OTHER NAMES` aggregate. All published name rows are retained; entries are not split at spaces. Each token is keyed by text and role, so a string that is both a given name and surname has two records.

The initially validated SSA snapshot contributes annual observations from 1880 through 2025; future downloads can contain additional years. Sex-specific SSA records are summed into name/year counts; sex information is not exposed or used to constrain combinations in this release. SSA-only given names are retained with unknown Census count and empty group/origin metadata. They can be sampled with a birth-year range and `group=None`, or in unweighted mode with `group=None`. Their historical birth totals are **not** silently mixed into current Census weights.

Sources:

1. [Census 2020 name datasets](https://www.census.gov/topics/population/genealogy/data/2020_names.html)
2. [First-name methodology](https://www2.census.gov/library/publications/decennial/2020/c2020br-13.pdf)
3. [Last-name methodology](https://www2.census.gov/library/publications/decennial/2020/c2020br-14.pdf)
4. [SSA downloads](https://www.ssa.gov/oact/babynames/limits.html)
5. [SSA source qualifications](https://www.ssa.gov/oact/babynames/background.html)

Government data retains its source attribution; this package does not claim exclusive rights to it. No data from INE, INSEE, NYC, or Wikidata has been incorporated yet. Their potential role is finer usage and origin enrichment, with source-specific reuse terms recorded when imported.

## Known approximations

- Broad Census groups are not languages or detailed naming traditions. They cannot distinguish Chinese, Vietnamese, Japanese, etc. Fine-grained origin metadata is **unknown**, not fabricated.
- Full-name pairs, middle-name distributions, surname pairs, gender consistency, and mixed-tradition households are not modeled. Multiple given names currently use the same eligible given-name pool. More realistic patterns need additional evidence.
- Rare entries are suppressed in source publications. The Census `ALL OTHER NAMES` aggregate is retained only in metadata, never as a token.
- Census counts include disclosure-avoidance noise and nonresponse effects. The importer uses the official nonnegative release.
- SSA records describe US births, not all current residents; immigrants born abroad are not represented by those birth records. Birth frequencies do not account for survival, migration or later name changes.
- SSA removes spaces and hyphens. Matching to Census uses uppercase text; punctuation variants are not guessed or merged. This may lose cohort coverage for some names.
- Initials are derived formatting, not observed initials-frequency data.
- Birth ranges outside available years only use matching published years; a range with no usable observations cannot produce given-name results.
- The generator does not restore accents absent in source data or validate whether an unusual published entry is a name. Names are not guaranteed unique or unlike a real person's name.

## Rebuild and inspect

```sh
python -m us_names.download --refresh
python -m us_names.build --output data/rebuilt.sqlite
python -m us_names info --db data/rebuilt.sqlite
python -m us_names export --db data/rebuilt.sqlite --output data/rebuilt-tokens.jsonl.gz
python -m unittest discover -s tests -v
```

Raw files are cached in `data/raw`. Downloading again reuses and verifies the cache. `--refresh` explicitly fetches current releases; use a separate `--raw-dir` to preserve an older snapshot. The builder never downloads files: missing inputs produce an actionable error. If raw files were placed manually without a download manifest, the builder computes and records their hashes itself.

Builds refuse to overwrite databases, validate source column names, and produce a companion manifest. Pass matching `--raw-dir` values to both commands when using a custom directory. A matching snapshot is reproducible from the same raw bytes; database file bytes and build timestamps need not be identical. Failed downloads do not become final source files. Source checksums detect local changes; they are provenance checks, not independently published government signatures.

All of `data/`, SQLite databases, compressed dataset files, source archives, and partial downloads are ignored by Git. Small generated examples remain for illustration. The repository contains no full dataset or database, including in this branch's parent history.

## Next improvements

1. Add sourced linguistic-origin labels and finer culture-specific usage observations.
2. Add sex-aware given-name sampling with documented mixed-gender compound-name exceptions.
3. Model compound given names and paired surnames from suitable aggregate evidence.
4. Improve very narrow length queries with length-indexed conditional sampling.
5. Add age-range convenience conversion and arbitrary component lists.
