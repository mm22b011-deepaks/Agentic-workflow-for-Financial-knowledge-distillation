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
