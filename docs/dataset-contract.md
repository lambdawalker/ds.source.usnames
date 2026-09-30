# Dataset contract: schema 3

Purpose: a compact, approximate model for **fictional-name generation**. Estimated values are not fully representative of reality. This is a breaking schema change; schema-2 consumers must not open it as schema 2. SQLite `PRAGMA user_version = 3`.

## Tables and view

- `names`: `id`, `name`, `role`, `national_count`, `char_length`, `source_id`, `female_share`, `sex_source_id`, `period_evidence`, six `<group>_count` columns, and `frequency_<start>_<end>` / `female_<start>_<end>` for every period. IDs come from staging and are snapshot-local. Unique `(name, role)`; index `(role, char_length, id)`.
- `periods`: zero-based `id`, inclusive `start_year`, inclusive `end_year`, `observed_total` (original published SSA counts), `model_mass` (sum of filled frequencies before renormalization).
- `sources`: integer `id`, original source `label`, URL, filename, SHA-256 and bytes. Integer foreign keys replace repeated source strings.
- `metadata`: JSON descriptive values, source manifest, model configuration, statistics and dataset version.
- `name_origin_associations`: any source-backed origin evidence retained from staging; currently empty. No origins are inferred from demographic groups.
- `names_normalized`: view with the same columns as `names`, but frequency columns divided by 1e9 and female-share columns divided by 1e4. All other fields are unchanged. The view stores no extra rows.

Read scales from `metadata.model`, not from assumptions about the column SQL type. Stored fractions are integer encodings. Female 7000 means 70%; male is the complement. Demographic columns are still original counts and must not be interpreted as shares.

## Periods and missing values

Three-year periods anchored at 1880. Output spans available annual source data only, ending at the latest observed year; the final period can be shorter. The current snapshot spans 1880–2025. Period IDs order the encoded evidence bits and should be read from the table, not hardcoded.

For given names, all period frequencies are positive integers, each period sums to exactly 1e9, and every female value is in [0,10000]. Surname period columns and evidence are NULL because birth cohorts do not apply. Overall female share and demographic counts may be NULL where no static evidence exists.

Observed frequency = published name count / published period count. Observed female share = published female count / published name count. A name absent for the whole bucket is missing, not an observed zero. An unreported sex in an observed bucket contributes zero; suppression limits this inference.

Interior gaps use linear interpolation between bucket midpoints; exterior gaps use constant endpoint extrapolation. No annual evidence uses a constant prior: Census national count, otherwise overall sex count, otherwise weight 1, divided by the sum of those available weights over retained given names. Female fallback uses overall recorded share, otherwise 0.5. Filled frequencies are renormalized per period. Quantization reserves one unit per positive name and distributes the remainder proportionally by largest remainder, with ties broken by original name order.

Evidence code per period: 0 observed, 1 interpolated, 2 extrapolated, 3 fallback. Decode period `i` as `(blob[i // 4] >> (2 * (i % 4))) & 3`. Evidence applies to that period's frequency and female share before renormalization. Every name retains one source label and overall sex-source label; cohort evidence originates from SSA or the documented fallback policy.

To combine periods, sum `frequency * observed_total`; for female-weighted generation, sum `frequency * female_share * observed_total`. Normalize across eligible names after applying constraints. Full-period queries are directly supported; partial-period weighting is a consumer approximation. Synthetic reconstructed counts are not original published counts.

## Release assets and compatibility

`names.sqlite.gz`, `tokens.jsonl.gz`, `names.manifest.json`, `VALIDATION.json`, `README.md`, `SHA256SUMS`. JSONL exports decode shares into [0,1] and evidence into labels; source and sex-source labels replace numeric source IDs. Detailed source manifests accompany exports.

All 270,062 name/role rows in the current inputs are retained. Source and generated files stay outside Git. `dataset-v0.2.0` remains unchanged, and the current `ds.python.usnames` package remains pinned to it until its reader supports schema 3. Never replace published release files in place.
