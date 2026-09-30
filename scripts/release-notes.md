Compact schema-3 US names model for fictional-name generation.

- All source name/role records retained; no rarity filtering.
- Three-year name-frequency and female-share buckets, with linear interpolation, constant endpoint extrapolation and marked fallbacks.
- Compact scaled integers; normalized SQL view and decoded JSONL export.
- Source hashes, model assumptions, estimation totals and validation included.

**This data is approximate and not fully representative of reality.** It is intended for fictional names, not demographic inference. Demographic counts remain unchanged in this revision.

**Breaking schema change:** the currently released generator in https://github.com/lambdawalker/ds.python.usnames reads schema 2 and must be updated separately before using this database. Its pinned `dataset-v0.2.0` remains available.

Verify release assets with `SHA256SUMS`. See README.md and the manifest for scales, provenance, source years and limitations.
