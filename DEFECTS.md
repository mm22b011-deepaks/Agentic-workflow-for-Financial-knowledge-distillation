# DEFECTS.md — R0 defect register (authoritative, from 2026-10-31)

This register replaces the provisional candidate list. It is the `DEFECTS.md` the
R-amendment refers to. R1 does not start until this pass is green.

Status values: `CONFIRMED` · `ALREADY-FIXED (test)` · `NOT-REPRODUCIBLE (why)` ·
`UNSURE (needs a live call)`.

Baseline gate before any work on this register (measured 2026-10-31):

```
ruff check .            -> All checks passed
ruff format --check .   -> 78 files already formatted
mypy src                -> Success: no issues found in 37 source files
pytest -q               -> 167 passed
```

---

## BLOCKERS

### N1 — Retry and cache are not wired into the live path `[CONFIRMED]` → `[FIXED 2026-10-31]`
`CachedCaller` appeared only in `tests/unit/test_retry_policy.py`;
`cli._cmd_extract` and `scripts/extract_sample.py` handed the bare `LLMCaller` to
`run_extraction`. `extract_structured` called `cache.set` but never `cache.get`.
- [x] `compose_caller(config, ledger, cache)` composition point used by every entry point
- [x] Dead write-only cache path removed or made to read
- [x] `CachedCaller` never caches empty / truncated / unparseable replies
- [x] Fix `cache.get` returning `''` for an empty entry while callers test `is not None`
- Tests: `test_cli_extract_uses_retrying_caller`, `test_runner_retries_429_with_retry_after`,
  `test_cache_hit_avoids_second_call`, `test_empty_reply_never_cached`,
  `test_unparseable_reply_never_cached`

### N2 — Empty completions from reasoning models `[CONFIRMED]` → `[PARTIALLY FIXED 2026-10-31; live items blocked]`
`complete()` only logged a warning on empty content with `finish_reason == 'length'`; the
empty text entered the repair loop, spending `1 + max_repairs` calls on nothing.
`message.reasoning` was never read.
- [x] Raise `TruncatedCompletion` on empty content; not counted as a parse failure
- [x] Retry once with larger `max_tokens` up to `llm.max_tokens_ceiling`
- [ ] `UNSURE`: reasoning field name and `reasoning` parameter honoured — **blocked on
      the OpenRouter 401**; no live call has been made
- [ ] Read supported parameters from the provider's models list, never hard code —
      **not implemented**
- [x] Log `completion_tokens` vs `max_tokens` in the ledger
- [ ] `model-bakeoff` command over the same 10 real releases per candidate `:free` model
      — **not implemented**; needs the live key first
- Tests: `test_empty_length_completion_raises_truncated`,
  `test_truncated_retries_with_larger_max_tokens_then_gives_up`,
  `test_truncated_not_counted_as_parse_failure`

### N3 — All-null extractions reported as success, on non-earnings documents `[CONFIRMED]` → `[PARTIALLY FIXED 2026-10-31; live rerun blocked]`
- [x] `empty_extraction` review reason when an earnings release yields no `reported_eps`
      and no `revenue`, distinct from `not_stated`; counted in the run summary
      (`cli.py` sums it from the outcomes)
- [x] Never extract a document whose index row lacks Item 2.02
- [ ] After N4/N7: rerun 10 real earnings releases, report per-field coverage —
      **blocked on the OpenRouter 401**
- Tests: `test_all_null_earnings_record_flagged_empty_extraction`,
  `test_non_earnings_document_not_extracted`

### N4 — Ingest sampling biased; S&P universe not wired in `[CONFIRMED]` → `[FIXED 2026-10-31]`
- [x] Seeded sample of point-in-time members per target season (`universe.subset_n`,
      `subset_seed`)
- [x] One earnings release per (company, filing) by exhibit priority
- [x] K seasons per company across the window, not the latest N documents
- [x] `data.constituents_csv` points at the built universe
- [x] Restrict CIKs with `active_on`; record skipped exhibits with a reason
- [x] Log the sample (companies, seed, seasons, skips) in the manifest
- Tests: `test_sample_spreads_across_ciks_not_lowest_first`,
  `test_sample_deterministic_for_seed`, `test_one_release_per_filing_by_priority`,
  `test_only_members_active_in_window`, `test_seasons_covered_per_company`

Measured: the CLI walk on the built universe logs
`ingesting for 519 companies sampled across 2025-01-01..2026-10-31 (cap 100 documents,
3 per company)` and `ingest_summary.json` records
`{"companies": 519, "seed": 42, "seasons": ["2025Q1", ..., "2026Q4"], "skipped": {}}`.
The walk order is a seeded permutation drawn per season, so a capped run is a spread
sample rather than the alphabetically first filers; each filing contributes exactly one
document (its highest-priority exhibit), and each company at most one document per
calendar quarter. `select_filings` records `duplicate_exhibit` and `duplicate_season`
as skips, so the report says what was set aside and why.
Deviations: `EXHIBIT_PRIORITY` is a code constant rather than a config key (the register
said "from config"); a config key would add a knob no other code reads and the list is a
property of EDGAR's filing convention, not of a deployment. Noted for the human.

### N5 — Aggregation can double-count and mislabel `[CONFIRMED]` → `[FIXED 2026-10-31]`
- [x] Collapse to one record per (cik, season) by a configurable rule
- [x] `n_reported` counts distinct companies
- [x] Assert `share_reported <= 1`, raise `DataError` otherwise
- [x] Rename season columns to `season_year` / `season_quarter`
- [x] `n_review_excluded` computed per as-of date
- Tests (all present and green in the 248-test suite):
  `test_two_models_do_not_double_count`, `test_two_exhibits_same_filing_count_once`,
  `test_share_reported_never_exceeds_one`, `test_review_excluded_is_per_asof`,
  `test_season_column_names`

### N6 — Ingest hides failures `[CONFIRMED]` → `[FIXED OFFLINE 2026-10-31; live CIK check blocked]`
- [x] `IngestReport` with status-code counts, skips by reason, zero-disclosure companies
- [x] Abort after N consecutive 403/429 (N from config) with a clear message
- [x] Write `manifests/ingest_report.json`
- [ ] `UNSURE`: does `filings.recent` reach `data.start_date` for high-volume filers;
      are `filings.files` pages needed — **blocked on the OpenRouter 401**
- [x] Atomic download (temp file then rename), verify size
- [x] Strip the SGML `<DOCUMENT><TYPE>..<TEXT>` wrapper before text conversion
- Tests: `test_ingest_report_counts_by_status`, `test_consecutive_403_aborts`,
  `test_partial_download_not_treated_as_complete`, `test_sgml_wrapper_stripped`,
  plus a live-marked high-volume CIK test that has **not** been run (no live access).

### N7 — The document index is stale `[CONFIRMED]` → `[FIXED OFFLINE 2026-10-31; rebuild run blocked]`
- [x] New column `items`; rebuild from scratch into `data.document_index`
      (default `data/document_index.v2.parquet`) — never overwrite or `mv`
- [x] Move affected extraction results and review-queue rows to a `superseded/` folder;
      never delete raw files
- [x] Index validation fails on any row lacking 2.02, outside the window, or non-text
- Tests: `test_index_validation_rejects_non_202_non_text_out_of_window`,
  `test_rebuild_writes_new_path_and_keeps_backup`,
  `test_rebuild_moves_superseded_results_and_queue_rows`.
- **Not run on live data.** The zero-cap smoke run wrote a headers-only
  `data/document_index.v2.parquet`; a real rebuild is blocked by the 401. Nothing old
  was deleted.

---

## HIGH

### H1 — Per-document crash safety incomplete `[CONFIRMED]` → `[FIXED 2026-10-31]`
Only the model call is protected in `runner._process`; `document_text`, `validate_record`,
`review_queue.append_rows` and `_write_result` are not.
- [x] Wrap the whole path; record the failure per document; continue
- Test: `test_runner_survives_missing_raw_file_and_write_error` — a missing raw file and
  an unwritable result fail one document each, while the third succeeds.

### H2 — Weak or misleading tests `[CONFIRMED]` → `[FIXED 2026-10-31]`
`test_runner_stops_on_budget_and_keeps_results` accepts either outcome.
- [x] Assert `budget_stopped` explicitly and that completed results are kept
- [x] Audit every test for "either outcome" assertions and for helpers tested while the
      live path is not — no remaining "either outcome" assertion found
- [x] Mutation testing on `validators.py`, `edgar.py`, `runner.py`, `aggregate.py`;
      report surviving mutants

First run: **20 mutants, 15 killed, 5 survived**. Each survivor was a behaviour nothing
pinned, and each got a test that fails only under that mutant:

| Survivor | Test that now kills it |
|----------|------------------------|
| quote threshold becomes `<=` | `test_quote_at_exactly_the_threshold_is_accepted` |
| confidence penalty dropped | `test_missing_evidence_penalises_confidence` |
| window lower bound exclusive | `test_window_bounds_are_inclusive` |
| blocked counter never resets | `test_a_success_clears_the_blocked_run` |
| company collapse removed | `test_duplicate_rows_do_not_weight_one_company_twice` |

Second run (after those tests, and again after the H3 refactor):
**20 mutants, 20 killed, 0 survived** — `python scripts/mutation_check.py`.

Third run (2026-10-31, after H5 added `units.py` / `prompts.py` mutants and a truncation
diagnostics mutant): **24 mutants, 23 killed, 1 survived**. The survivor was
`non-text exhibits allowed`: the existing image test pairs the `.jpg` with a text exhibit,
so the per-filing exhibit reduction kept the scan out even with the suffix check gone.
`test_image_only_filing_is_skipped_not_downloaded` pins a filing whose *only* exhibit is
a scan, which the guard alone can drop. Final: **24 mutants, 24 killed, 0 survived**.

### H3 — Reproducibility and portability leftovers `[CONFIRMED]` → `[FIXED 2026-10-31]`
- [x] No `load_dotenv(override=True)` in scripts; no `ROOT/'data'` or `ROOT/'inputs'`;
      no `print`
- [x] `make_inputs.py` / `probe_models.py`: no hard-coded tickers, URLs or model IDs
- [x] `requirements.lock.txt`: no `-e file:///home/...`; regenerate clean; split dev pins

Measured after the fix: `grep -n 'print(' scripts/{make_inputs,probe_models,smoke_llm,
ingest_real,extract_sample}.py` → no matches; scripts report through the same
`setup_logging` formatter the CLI uses. One dotenv implementation
(`nowcast.envfile.load_dotenv_without_overriding`, `override=False` only) serves both the
CLI and every script; `test_scripts_and_cli_share_one_dotenv_rule` pins that. Tickers come
from `--tickers` (default `inputs/tickers.txt` under the data root); models from
`--models` / `--models-file` / config. Lock files regenerated with uv:
`requirements.lock.txt` 58 pins (`--no-dev`), `requirements-dev.lock.txt` 76 pins
(`--extra dev`), neither containing a local path. `requests` stays pinned: it is a
transitive dependency of `langchain-core`/`langsmith`, not a direct one.

### H4 — Fingerprint and stored validation `[CONFIRMED]` → `[FIXED 2026-10-31]`
Fingerprint omits `max_doc_chars` and the validation thresholds; penalties are baked into
the stored record, so changing a threshold silently reuses old results.
- Fixed by hashing `validation_settings(config)` (max_doc_chars, quote ratio, confidence
  penalty, min confidence, EPS tolerance, evidence words, themes, section patterns,
  schema version) into the fingerprint.
- Test: `test_changing_threshold_invalidates_or_revalidates` covers every setting and
  also asserts that identical settings produce an identical digest.
- Related gap found during H5 (D16): the few-shot pairs were sent to the model but not
  hashed; they are now part of `prompt_hash`.

### H5 — Truncation and units `[CONFIRMED]` → `[FIXED OFFLINE 2026-10-31; live rerun blocked]`
`max_doc_chars = 24000` cuts long releases (one real release is 56k chars, a supplement
93k).
- [x] Measure the share of documents whose guidance or EPS text sits after the cut.
      Measured on the real index (`data/document_index.parquet`, 61 parseable text
      documents, `max_doc_chars = 24000`): **14 of 61 (23.0%)** exceed the cut, and
      **515,868 of 1,232,947 corpus characters (41.8%)** never reach the prompt.
      Search terms applied to the same converted text the runner prepares (case
      insensitive): EPS = `earnings per share|EPS`, revenue = `revenue|net sales`,
      guidance = `guidance|outlook`, growth = `growth|grew`. First occurrence only after
      the cut: guidance **4/14**, growth **1/14**, EPS 0/14, revenue 0/14. Any occurrence
      after the cut: revenue 6/14, EPS 5/14, guidance 4/14, growth 1/14. The four
      guidance-only-after-the-cut documents are JPMorgan supplements (77k–90k chars);
      the other over-cut documents are six Caterpillar 8-Ks (48k–55k), three IBM
      releases (25k–27k) and one 114,744-char release with no term after the cut.
      Reproduce with `python scripts/measure_truncation.py --index
      document_index.parquet`.
- [x] Until R2: record how much text was sent. `runner.prepare_text` returns
      `DocumentText(text, chars_total, chars_sent)`; the result payload carries
      `diagnostics: {chars_total, chars_sent, truncated}`, the outcome carries
      `truncated`, `consolidate` writes the three columns (absent diagnostics → `None`,
      "not measured", not `False`), and a warning logs the cut percentage. Naming
      deviation: the register says `doc_truncated`; the payload key is `truncated` to
      match Q-PART 3 and the outcome flag. The `doc_truncated` *reason code* remains a
      Q-PART 3 task.
- [x] Define the percent convention for `revenue_yoy_growth` (as printed, unit
      `percent`): `4%` is `4.0`, never `0.04`. Rule added to the system prompt; the
      consolidated column is named `revenue_yoy_growth_pct`.
- [x] Normalise the free-text `units` field in code (`extraction/units.py`) into
      `<CCY> [scale]` ("dollars" → "USD", "USD billions" → "USD billion"), with the
      record's currency as fallback and unrecognised labels preserved. Growth is
      corrected from the evidence quote when it shows a percent sign; a sub-1% printed
      figure such as 0.5% is left as 0.5. Normalisation runs **before** validation so a
      correctable fraction is not penalised.
- [x] **Interim packer** (Step 5): `parsing/packing.py` keeps the first third of the
      limit plus windows around `extraction.pack_phrases`, merges overlapping regions,
      joins them in document order with `[... omitted ...]`, and records `windows_used`.
      Measured on the same 61 text documents after the change
      (`scripts/measure_truncation.py --index document_index.parquet`): 14 of 61 still
      over the limit and 558,647 characters still not sent, but the terms that matter
      now reach the model — `terms_missing_from_sent: {eps: 0, revenue: 0, guidance: 0,
      growth: 1}`. Before the packer, guidance was missing from 4 documents and revenue
      from 6. The one remaining growth miss is a document whose only "growth" word is not
      near a configured phrase.
- Tests: `tests/unit/test_units.py` (parametrised units/growth cases, `prepare_text`
  measurement, and a runner-to-parquet end-to-end case), `tests/unit/test_packing.py`
  (guidance window kept past the cut, document order, omission markers, short text,
  plain head cut), plus `test_runner_stores_diagnostics_and_corrected_values`.
- Deviation, logged in `DECISIONS.md` D16: `tests/fixtures/documents/records.json`
  keeps `0.08` as a *model reply* for "up 8%", and the integration/end-to-end tests
  assert the stored and consolidated value is `8.0`. Correcting the input is the
  behaviour under test, so a pre-corrected fixture would hide it.

---

## MEDIUM

### M1 — Dead and duplicate config `[CONFIRMED]` — partially fixed
`cache.dir` unused; `HTTP-Referer` set to the app name, not a URL; SEC client reuses
`llm.timeout_seconds`; `:free` defined in both `config.py` and `caller.py`;
`EXHIBIT_99_RE` / `EXHIBIT_FORMS_PREFIX` unused; dead dict in `runner.document_text`.
- [x] Dead `sections` dict removed when `runner.document_text` became `prepare_text` (H5)
- [ ] `cache.dir` — `config.paths.cache_dir` is used; confirm no second unused key
- [ ] `HTTP-Referer` should be a URL, not the app name (OpenRouter reads it as one)
- [ ] SEC client should not borrow `llm.timeout_seconds`
- [ ] One `:free` suffix constant, not two
- [ ] Remove or use `EXHIBIT_99_RE` / `EXHIBIT_FORMS_PREFIX`

### M2 — Unknown key raises `TypeError` `[UNSURE]` → `[ALREADY-FIXED (test) + one real gap]`
`_section` already rejected unknown keys inside a known section with `ConfigError`.
Probing through `load_config` found the gap the `[UNSURE]` was hiding: an unknown
**top-level** section (`aggregaton:`, `nope:`) was accepted silently, so a misspelled
section name left the defaults in force and the run succeeded against settings nobody
chose. `_reject_unknown_sections` now fails on it, naming the key and the known sections.
Test: `test_unknown_top_level_section_is_rejected`; the per-section case keeps
`test_unknown_section_key_is_rejected` and the CLI-level
`test_unknown_config_key_is_a_config_error`.

### M3 — Docs report only measured state `[ONGOING]`
`DEFECTS.md`, `status.md`, `tasks.md` updated with real counts after each item.

### M4 — Hidden files `[VERIFIED 2026-10-31, one known deviation]`
Confirmed: `.gitignore` and `.env.example` exist; `.git` is present; `.env` and every
`*.parquet` are untracked; `data/`, `__pycache__/`, `*.egg-info/`, `.venv/` and the
tool caches are ignored. The LLM cache resolves under `data/`, so it is covered.
**Deviation:** `tresata.zip` is tracked in git by accident (added in commit `008add1`;
it contains `tests/__pycache__`). Removing it is a deliberate repository change that
needs the human's go-ahead, so it is recorded here rather than deleted. A `.gitignore`
entry for nested zips goes with that removal.

---

## Answers recorded (from the human)

- **Q1** — this register *is* `DEFECTS.md`. The provisional file is replaced.
- **Q4** — do **not** overwrite or `mv` the index. Add `data.document_index`
  (default `data/document_index.v2.parquet`), write the rebuilt index there, keep the old
  files under `data/index_backup/`. Nothing is deleted.
- **Q3** — `reporting.max_detail_level` stays `index`.

---

## Reviewer pass 2 status (2026-11-01)

The register below is the pass-1 text. Pass 2 added F1–F19, plus the N/H/M remainders.
Per-item status and reasoning are in `DECISIONS.md` D17 and `tasks.md`; the test that
covers each is mapped in `evidence/phase_R0.txt`. Summary of what is still open:

| Item | State |
|------|-------|
| F2 key provenance | FIXED; live cause measured (an exported, too-short value shadows `.env`) |
| F12 auth fail-fast | FIXED |
| N1 one cache | FIXED |
| N2 | FIXED offline; live reasoning probe + bakeoff BLOCKED (H-A) |
| F9 sample | FIXED |
| N3 | FIXED offline; live coverage rerun BLOCKED (H-A) |
| F7 / F11 / F6 / F5 / F4 / F8 / H1 | FIXED |
| F10 vocabularies | FIXED; `withdrawn` guidance has no share column (recorded, D17) |
| F1 cohort share | FIXED |
| F3 per-metric minimums | FIXED |
| F15 | decision recorded; `fiscal_period_consistency` NOT implemented |
| F14 | window/status fixes done; `filings.files` pagination NOT implemented |
| F16 | `aggregate` command FIXED; `nowcast`/`evaluate`/`report` intentionally absent |
| N4, N5, N6 (offline), N7 (offline), H2–H5, M2 | FIXED in pass 1 |
| M1 | FIXED except `tresata.zip` tracking (H-B) |
| M4 | VERIFIED except `tresata.zip` (H-B) |
| Gate R0 live items | BLOCKED (H-A) |

Measured 2026-11-01 and recorded in `evidence/phase_R0.txt`:
`ruff` clean, 100 files formatted, `mypy` clean on 45 files, **303 passed**,
**mutation check 33/33 killed, 0 survived**. Offline index rebuild: 100 rows → 0 kept
(`no_earnings_item: 61, non_text: 39`), old files untouched, results moved to
`superseded/`.
