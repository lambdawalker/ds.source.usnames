US-wide names dataset built from pinned Census and SSA government aggregates.

Download `names.sqlite.gz` for SQLite or `tokens.jsonl.gz` for portable token records. See `names.manifest.json` for the exact source snapshot, years, version and counts. Verify downloads against `SHA256SUMS`; database integrity results are in `VALIDATION.json`.

The Python generator is maintained separately at https://github.com/lambdawalker/ds.python.usnames and consumes these release assets.

Census demographic groups are not linguistic or cultural origins. Frequencies are approximate: source disclosure noise, suppression, normalization, and missing names affect coverage. Source-recorded sex is not an individual's gender identity. See README.md for source methods and limitations.
