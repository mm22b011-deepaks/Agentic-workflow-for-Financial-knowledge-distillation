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

### Added
- **2026-10-31 — H5: units normalisation and truncation diagnostics.**
  `extraction/units.py` canonicalises the free-text `units` label to `<CCY> [scale]`
  (`dollars` → `USD`, `USD billions` → `USD billion`, scale-only labels take the record's
  currency, unrecognised labels are preserved) and corrects a fractional
  `revenue_yoy_growth` to the printed percentage when the evidence quote shows one.
  `runner.prepare_text` reports `chars_total` / `chars_sent` / `truncated`; the result
  payload, the per-document outcome and the consolidated frame all carry them. A
  truncated document logs a warning with the cut percentage.
- **Prompt hardening for weak free models.** The v1 system prompt is now a field-level
  data-entry contract: every field defined, allowed vocabularies for `eps_basis`,
  `guidance_direction` and `tone`, GAAP preferred when both EPS bases are printed,
  segment revenue excluded from `revenue`, growth as printed percent, canonical `units`,
  per-field null policy, evidence quote must contain digits and unit, no arithmetic,
  bare-JSON output, and document-is-data. The user message restates all sixteen keys
  before the document. Three synthetic few-shot examples now cover GAAP+growth,
  revenue-only with missing EPS and explicitly unavailable guidance, and adjusted EPS
  with a "flat" quarter left null rather than inferred as 0.0.
- `tests/unit/test_units.py`: parametrised unit/growth cases, the text-cut measurement,
  and a runner-to-parquet end-to-end case for the corrected values and diagnostics.
- `scripts/measure_truncation.py`: reproduces the H5 cut measurement (documents over the
  cut, characters dropped, key-term positions) using the runner's own conversion and
  `max_doc_chars`, with the search terms printed in the report.

### Fixed
- **Few-shot examples were not part of the prompt hash.** They are sent to the model as
  messages, so editing one changed the prompt while a stored result still resumed as
  current. `prompt_hash` now hashes them too; `test_prompt_hash_changes_with_few_shots`
  pins it.
- **`revenue_yoy_growth` had two conventions.** The few-shot used `4.0` for "up 4%" and
  the fixture used `0.08` for "up 8%". The convention is now percent as printed
  everywhere; normalisation corrects a fraction before validation, and the consolidated
  column is named `revenue_yoy_growth_pct`.
- **Document truncation was invisible.** The cut is now measured and recorded rather
  than silently applied; on the real 61-document text corpus 14 documents (23.0%) are
  cut and 41.8% of characters never reach the prompt (DEFECTS.md H5).
- **Dead `sections` dict removed** from the runner's text path (M1 item).

### Changed
- Consolidated extraction columns gain `chars_total`, `chars_sent`, `truncated`;
  `revenue_yoy_growth` is renamed `revenue_yoy_growth_pct`. Pre-H5 results read `None`
  for the diagnostics columns ("not measured"), never `False`.
- **Every extraction fingerprint changes** because the prompt text and few-shot examples
  changed. Existing stored results are therefore stale and will be re-extracted on the
  next live run; this is intended, not a resume bug.

### Fixed
- **R0 defect-remediation pass (2026-10-31).** Retry and cache composed on the live call
  path (N1); empty length completions classified as truncation with one doubled-budget
  retry (N2); all-null earnings records flagged `empty_extraction` and non-2.02 filings
  refused (N3); seeded point-in-time sampling with one release per filing and per
  company-season (N4); distinct-company aggregation with a `share_reported <= 1` guard
  (N5); ingest status/skip report, consecutive-block abort and atomic downloads (N6);
  a rebuild command that writes the new `items`-bearing index to `data.document_index`
  without touching the old files (N7, execution blocked on the live 401); per-document
  crash guard and settings-complete fingerprint (H1, H4); 24-mutant check green (H2);
  one dotenv path and portable scripts (H3); unknown top-level config sections rejected
  (M2). Status and measurements per item are in `DEFECTS.md`.
