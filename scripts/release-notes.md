US-wide synthetic-name dataset, built from pinned Census 2020 and SSA national data (1880–2025).

- Normalized, indexed SQLite tables for name frequencies, demographic counts, sex counts, and birth-year counts.
- Python generator supports consistent given-name sex selection, initials, multiple given names and surnames, length constraints, and weighted or uniform sampling.
- Download `names.sqlite.gz` and decompress it for use with the Python source at this release tag. `tokens.jsonl.gz` is the portable export.
- `names.manifest.json` records original URLs and SHA-256 hashes; `SHA256SUMS` verifies the release assets.

These are approximate synthetic distributions. Census demographic groups do not establish linguistic or cultural origin. Joint name, demographic, sex, and cohort relationships are approximated; source suppression and missing names limit coverage. Source-recorded sex is not an individual's gender identity. See README.md for limitations and defaults.
