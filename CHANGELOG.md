# Changelog

All notable changes to this project. Format follows Keep a Changelog; versions are
pre-1.0 and follow the phase gates in `tasks.md`.

## [Unreleased]

### Added
- Phase 0 scaffold: typed config (`config.py`), path layout (`paths.py`), logging setup
  (`logging_setup.py`), run manifests (`manifest.py`), errors and an argument-parsed CLI.
- Phase 1 LLM layer: synchronous OpenRouter caller restricted to `:free` models, disk
  cache keyed on model/temperature/max_tokens/prompt, thread-safe budget ledger, prompt
  loading with `StrictUndefined`, structured extraction with bounded repair turns.
- Phase 2 ingestion: EDGAR 8-K Item 2.02 discovery with EX-99 exhibit selection, a local
  manifest adapter, and a parquet document index.
- Phase 2B universe builder: S&P 500 membership reconstructed from Wikipedia's current
  and changes tables (or a historical snapshot CSV), CIK resolution with overrides, a
  member-count audit, overlap checks and an offline scope estimate.
- Phase 3 extraction: schema, validators, review queue and a resumable runner.
- `--strict` on `validate-config`; every ingest/extract run writes a manifest with config
  hash, git sha, package versions, prompt hashes and input fingerprints.

### Fixed
- `active_on` no longer drops every open-ended membership: `NaT >= date` is always False,
  so blank `effective_to` is filled with an open-ended sentinel before comparison. This
  silently excluded all 503 current members from every point-in-time slice.
- `reconstruct_membership` keeps a per-ticker stack of pending memberships, so a reused
  ticker produces two intervals rather than one merged interval.
- `snapshots_to_intervals` splits contiguous runs, so a member that leaves and rejoins
  the index gets two intervals instead of one spanning its absence.
- The 8-K ingest window comes from config; it no longer falls back to `date.today()`.
- Budget exhaustion inside structured extraction is re-raised instead of being swallowed
  as a parse failure.
- Retries honour a provider's `Retry-After` / `retry_after_ms`, capped by
  `llm.retry_max_wait_seconds`.

### Changed
- **2026-10-31 — amendments recorded.** The *R-amendment* (course correction +
  optimization: SQLite as system of record, lossless document→company→sector→index
  hierarchy, context packer, structure-first extraction, measured benchmarks) and
  *Amendment Q* (no number silently missing, excluded or non-comparable; versioned
  taxonomy) are captured in `tasks.md` PART 1 and PART 1B, with decisions D1–D12 in
  `DECISIONS.md` and the standing rules added to `claude.md`. No code changed for this
  entry.
- `data.edgar_index_headers_url_template` now includes the accession directory. See the
  fix below.

### Fixed
- **EDGAR discovery returned zero disclosures for every CIK.** The index-headers URL
  omitted the accession directory; EDGAR's CDN answers **403** (not 404) in that case, so
  the failure looked like a permissions problem. Verified live: broken URL → 403, correct
  URL → 200; afterwards Caterpillar yields 16 earnings disclosures and Coca-Cola 8, and a
  non-earnings 5.02 filing no longer qualifies. `validate_config` rejects a template
  without `{accession_nodash}`; `test_headers_url_carries_the_accession_directory` covers
  it.
- **A surprise exactly at `extraction.eps_tolerance_abs` was graded a beat.** In binary
  floating point `1.0 + 0.05 - 1.0` is `0.050000000000000044`, clearing a strict `>`
  comparison. Beat grading now rounds the surprise to `SURPRISE_DECIMALS = 10` before
  comparing; `test_beat_tolerance_boundaries` pins both edges.
