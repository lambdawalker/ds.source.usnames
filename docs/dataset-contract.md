# Dataset contract: schema 2

The producer is `ds.source.usnames`; the consumer is `ds.python.usnames`. Their runtime code has no dependency on the other repository. SQLite `PRAGMA user_version = 2` defines their shared interface.

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

## Release interface

Every compatible release provides `names.sqlite.gz` and `SHA256SUMS` at `/releases/download/<tag>/` in `lambdawalker/ds.source.usnames`. The checksum file uses `sha256sum` format, with exactly one entry for the compressed database. Data is UTF-8; name strings are NFC normalized. Counts are nonnegative, and missing totals stay null.

The manifest and SQLite metadata identify source hashes, build timestamp, dataset version, source years and statistics. IDs are local to a snapshot, not stable cross-release identifiers. Consumers pin the release tag; they must not mix tables from different releases. Published assets must remain unchanged.

Government source snapshots can change without changing the schema. Incompatible table/column/meaning changes require a new `user_version`; consumers reject unsupported versions. The library reads persistent tables without modifying them and may create temporary tables for cohort queries.

The published `dataset-v0.2.0` remains compatible. Splitting the repositories does not modify that release. Producer versions, release tags and library versions have separate lifecycles; choose a new release tag for any newly published build.
