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

### Fixed — reviewer pass 2 (2026-11-01)

- **F2 — the 401 was a shadowed key.** `scripts/smoke_llm.py` reports the API key's source,
  length and sha256 prefix (never the value) and warns when an exported variable differs
  from the one in `.env`. Measured live: an exported value shadows the file and is far shorter than an
  OpenRouter key.
- **F12 — auth errors fail fast.** New `AuthError` (401/403) and `ModelNotFound` (400/404),
  never retried; `run_extraction` stops the run and re-raises instead of queueing one
  `llm_failed` row per document.
- **N2 — per-call token budget and a complete ledger.** `with_max_tokens` and the shared
  ratchet are gone; an empty reply raises `EmptyCompletion` (`TruncatedCompletion` for
  `finish_reason=length`); every attempt is ledgered with `finish_reason` and `outcome`
  before any raise; `reasoning` is sent only when the provider says the model supports it;
  one reasoning control with `validate_config` rejecting both at once.
- **N1 — one cache.** The write-only cache in `extract_structured` is deleted; the cache
  key includes the reasoning parameters.
- **F9 — `--sample` takes a stratified sample** (one document per company first, seeded),
  and `--limit` warns that it is the head of the index.
- **F7 — a number must appear in the matched source window.** A quote with one changed
  digit no longer passes on fuzzy similarity alone (`number_not_in_source`).
- **F10 — vocabularies live in config** and drive the prompt, the validator and the
  aggregator; `mixed` is scored 0.0 and an unknown tone is counted, not silently NaN.
- **F11 — every field with a value is confidence-checked**, theme mentions included, and a
  truncated document is queued as `doc_truncated`.
- **N3 — `eps_missing`** is a separate review reason from `empty_extraction`.
- **H5 — interim packer**: the head of the release plus windows around configured phrases,
  joined in document order with omission markers.
- **F6 — the review queue is a verdict**: rows are replaced per (document, model), the
  replaced rows are archived under `superseded/`, aggregation excludes per (document,
  model), and `n_review_excluded` counts companies.
- **F5 — dedupe uses a stored confidence**: `consolidate` writes `record_confidence`, and a
  missing column raises instead of silently sorting by document id.
- **F1 — cohort share**: `share_of_cohort` and `share_of_index`, a `manifests/cohort.csv`,
  and a `cohort_too_small:<season>` warning instead of lowering `min_constituents`.
- **F3 — per-metric minimums**: `n_obs_*` and `metric_status_*` columns; a metric below
  `aggregation.min_observations` is NaN with a status.
- **F4 — winsorising inside each as-of snapshot**; later documents cannot change earlier
  rows.
- **F8 — gzip downloads are not flagged truncated**; the length check compares bytes
  actually downloaded and skips when a `Content-Encoding` is present.
- **F14 — a bad window is not every company's zero**: window errors abort, missing
  `data.end_date` is a `ConfigError`, and non-404 submissions failures are counted as
  `cik_failed:<status>`.
- **H1 — consolidation survives corrupt result files**, skipping and counting them.
- **F16 — `nowcast aggregate`** runs the privacy guardrail before writing, and `run-all`
  runs through to it and stops at the first failure.
- **Hygiene** — `llm.referer_url` (header omitted when empty), one `:free` constant, dead
  exhibit constants and duplicate `cache.dir` removed, `data.sec_timeout_seconds`,
  `.gitignore` covers `*.zip` and `*.part`, `tenacity` removed and locks regenerated.

### Added — reviewer pass 2

- `nowcast model-bakeoff` (offline-tested): one sample, every configured `:free` model,
  empty-completion rate, parse success, per-field coverage, latency and request count.
- `extraction/selection.py` (stratified sampling), `parsing/packing.py` (interim packer),
  `extraction/bakeoff.py`, `llm` auth/model error types, `manifests/cohort.csv`,
  `evidence/phase_R0.txt`.

### Not done, deliberately

- F15's `fiscal_period_consistency` diagnostic (an R4 output column).
- F14's `filings.files` pagination (needs a live high-volume CIK).
- Every live gate item, blocked on the OpenRouter key (H-A).

### Fixed — pass 3 (2026-11-01)

- **B1 — the cohort is the (company, season) pairs the run targets.** `Sample.pairs`
  records them, ingest only keeps filings from a sampled season
  (`season_not_sampled`), `manifests/cohort.csv` is one row per pair, and aggregation
  reads the cohort per season. Live SEC run: 60 documents, 61 companies, 64 pairs,
  eight seasons, every downloaded pair in the cohort.
- **B2 — `number_in_quote` reads one scale from the quote.** 1000 against "$1.2 billion"
  is now flagged; the printed figure and its expansion still pass.
- **B4 — a review flag withdraws a field, not a company.** Blocking reasons drop the
  record; any other flag withdraws only that field's metric contribution.
- **B5 — the packer allocates budget by priority** (guidance/outlook, per-share, revenue)
  and keeps document order; a negative-budget slice that silently dropped regions is
  gone, and a sweep test pins the limit.
- **B6 — `rebuild-index` refuses a populated target** unless `--force`, and backs the old
  file up with a timestamp first.
- **B7 — ingest persists as it goes**: each document is merged into the index
  immediately, and the cohort, report and summary are written in `finally`, so an abort
  keeps what was downloaded.
- **H-a — request budget instead of a dollar budget**: a shared per-minute and per-day
  limiter, a global cooldown on `Retry-After`, and a model cascade that escalates only on
  failure or low confidence.
- **H-b — `finish_reason=length` is truncation even with content**; a transient empty
  reply is retried once.
- **H-c — only current results are used**: temperature, max tokens, reasoning and the
  units rule are in the fingerprint, stale results move to `superseded/`, and aggregate
  drops rows marked stale.
- **H-h — paths follow the config file**, getters no longer create directories, the
  module-level skipped-results list is gone, and `RetryingCaller.close()` replaces private
  `_caller` access.
- **M-a — SGML stripping is anchored to the start of the file** and keeps everything to
  the final `</TEXT>`, so inline SVG text cannot truncate a page.

### Added — pass 3

- `nowcast.llm.throttle.RequestLimiter`; `llm.requests_per_minute`, `requests_per_day`,
  `cooldown_seconds`, `cascade_min_confidence`; `aggregation.revenue_growth_agg` and
  `metric_status_* = 'no_consensus'`; `extraction/selection` pairing; per-season cohort
  reading; `paths` config-dir anchoring.

### Not done in pass 3

H-d (`filings.files` pagination), H-e (bakeoff ledger, p50/p95, 429, accuracy mode), H-f
(model-priority dedupe), H-g (cache-after-validate, fiscal_year, theme directions,
prior-year basis). M-b/M-c await the decision on tracked files.
