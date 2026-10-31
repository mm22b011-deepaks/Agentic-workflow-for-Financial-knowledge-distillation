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

### N1 — Retry and cache are not wired into the live path `[CONFIRMED]`
`CachedCaller` appeared only in `tests/unit/test_retry_policy.py`;
`cli._cmd_extract` and `scripts/extract_sample.py` handed the bare `LLMCaller` to
`run_extraction`. `extract_structured` called `cache.set` but never `cache.get`.
- [ ] `make_caller(config, ledger, cache)` composition point used by every entry point
- [ ] Dead write-only cache path removed or made to read
- [ ] `CachedCaller` never caches empty / truncated / unparseable replies
- [ ] Fix `cache.get` returning `''` for an empty entry while callers test `is not None`
- Tests: `test_cli_extract_uses_retrying_caller`, `test_runner_retries_429_with_retry_after`,
  `test_cache_hit_avoids_second_call`, `test_empty_reply_never_cached`,
  `test_unparseable_reply_never_cached`

### N2 — Empty completions from reasoning models `[CONFIRMED]`
`complete()` only logged a warning on empty content with `finish_reason == 'length'`; the
empty text entered the repair loop, spending `1 + max_repairs` calls on nothing.
`message.reasoning` was never read.
- [ ] Raise `TruncatedCompletion` on empty content; not counted as a parse failure
- [ ] Retry once with larger `max_tokens` up to `llm.max_tokens_ceiling`
- [ ] `UNSURE`: reasoning field name and `reasoning` parameter honoured — one live call
- [ ] Read supported parameters from the provider's models list, never hard code
- [ ] Log `completion_tokens` vs `max_tokens` in the ledger
- [ ] `model-bakeoff` command over the same 10 real releases per candidate `:free` model
- Tests: `test_empty_length_completion_raises_truncated`,
  `test_truncated_retries_with_larger_max_tokens_then_gives_up`,
  `test_truncated_not_counted_as_parse_failure`

### N3 — All-null extractions reported as success, on non-earnings documents `[CONFIRMED]`
- [ ] `empty_extraction` review reason when an earnings release yields no `reported_eps`
      and no `revenue`, distinct from `not_stated`; counted in the run summary
- [ ] Never extract a document whose index row lacks Item 2.02
- [ ] After N4/N7: rerun 10 real earnings releases, report per-field coverage
- Tests: `test_all_null_earnings_record_flagged_empty_extraction`,
  `test_non_earnings_document_not_extracted`

### N4 — Ingest sampling biased; S&P universe not wired in `[CONFIRMED]`
- [ ] Seeded sample of point-in-time members per target season (`universe.subset_n`,
      `subset_seed`)
- [ ] One earnings release per (company, filing) by exhibit priority from config
- [ ] K seasons per company across the window, not the latest N documents
- [ ] `data.constituents_csv` points at the built universe
- [ ] Restrict CIKs with `active_on`; record skipped exhibits with a reason
- [ ] Log the sample (companies, seasons) in the manifest
- Tests: `test_sample_spreads_across_ciks_not_lowest_first`,
  `test_sample_deterministic_for_seed`, `test_one_release_per_filing_by_priority`,
  `test_only_members_active_in_window`, `test_seasons_covered_per_company`

### N5 — Aggregation can double-count and mislabel `[CONFIRMED]`
- [ ] Collapse to one record per (cik, season) by a configurable rule
- [ ] `n_reported` counts distinct companies
- [ ] Assert `share_reported <= 1`, raise `DataError` otherwise
- [ ] Rename season columns to `season_year` / `season_quarter`
- [ ] `n_review_excluded` computed per as-of date
- Tests: `test_two_models_do_not_double_count`, `test_two_exhibits_same_filing_count_once`,
  `test_share_reported_never_exceeds_one`, `test_review_excluded_is_per_asof`,
  `test_season_column_names`

### N6 — Ingest hides failures `[CONFIRMED]`
- [ ] `IngestReport` with status-code counts, skips by reason, zero-disclosure companies
- [ ] Abort after N consecutive 403/429 (N from config) with a clear message
- [ ] Write `manifests/ingest_report.json`
- [ ] `UNSURE`: does `filings.recent` reach `data.start_date` for high-volume filers;
      are `filings.files` pages needed — one live high-volume CIK
- [ ] Atomic download (temp file then rename), verify size
- [ ] Strip the SGML `<DOCUMENT><TYPE>..<TEXT>` wrapper before text conversion
- Tests: `test_ingest_report_counts_by_status`, `test_consecutive_403_aborts`,
  `test_partial_download_not_treated_as_complete`, `test_sgml_wrapper_stripped`,
  plus `@pytest.mark.live` on one high-volume CIK

### N7 — The document index is stale `[CONFIRMED]`
- [ ] New column `items`; rebuild from scratch into `data.document_index`
      (default `data/document_index.v2.parquet`) — never overwrite or `mv`
- [ ] Move affected extraction results and review-queue rows to a `superseded/` folder;
      never delete raw files
- [ ] Index validation fails on any row lacking 2.02, outside the window, or non-text
- Tests: `test_index_validation_rejects_non_202_non_text_out_of_window`,
  `test_rebuild_writes_new_path_and_keeps_backup`

---

## HIGH

### H1 — Per-document crash safety incomplete `[CONFIRMED]`
Only the model call is protected in `runner._process`; `document_text`, `validate_record`,
`review_queue.append_rows` and `_write_result` are not.
- [ ] Wrap the whole path; record the failure per document; continue
- Test: `test_runner_survives_missing_raw_file_and_write_error`

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

### H4 — Fingerprint and stored validation `[CONFIRMED]`
Fingerprint omits `max_doc_chars` and the validation thresholds; penalties are baked into
the stored record, so changing a threshold silently reuses old results.
- Test: `test_changing_threshold_invalidates_or_revalidates`

### H5 — Truncation and units `[CONFIRMED]`
`max_doc_chars = 24000` cuts long releases (one real release is 56k chars, a supplement
93k).
- [ ] Measure the share of documents whose guidance or EPS text sits after the cut
- [ ] Until R2: record `doc_truncated` in diagnostics
- [ ] Define the percent convention for `revenue_yoy_growth` (as printed, unit `percent`)
- [ ] Normalize the free-text `units` field in code; tests for `4%` and `0.04`

---

## MEDIUM

### M1 — Dead and duplicate config `[CONFIRMED]`
`cache.dir` unused; `HTTP-Referer` set to the app name, not a URL; SEC client reuses
`llm.timeout_seconds`; `:free` defined in both `config.py` and `caller.py`;
`EXHIBIT_99_RE` / `EXHIBIT_FORMS_PREFIX` unused; dead dict in `runner.document_text`.

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

### M4 — Hidden files `[TO VERIFY]`
Confirm `.gitignore`, `.env.example`, `.git` exist; `data/`, `.env`, `.cache`,
`__pycache__`, `*.egg-info`, nested zips are ignored; no secrets committed.

---

## Answers recorded (from the human)

- **Q1** — this register *is* `DEFECTS.md`. The provisional file is replaced.
- **Q4** — do **not** overwrite or `mv` the index. Add `data.document_index`
  (default `data/document_index.v2.parquet`), write the rebuilt index there, keep the old
  files under `data/index_backup/`. Nothing is deleted.
- **Q3** — `reporting.max_detail_level` stays `index`.
