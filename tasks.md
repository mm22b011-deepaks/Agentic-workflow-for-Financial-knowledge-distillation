# tasks.md — index-earnings-nowcast task board

Status legend: `[x]` done · `[~]` in progress · `[ ]` todo · `[!]` blocked on a decision

Last gate run: `ruff check . && ruff format --check . && mypy src && pytest -q` →
all clean, **141 tests passing** (2026-10-31).

## A. Repair queue (review feedback — do before new phases)
- [x] A1 EDGAR: select 8-Ks whose `items` contain `2.02`; identify EX-99 by `<TYPE>` in
      `<accession>-index-headers.html`, not by filename. (verified live 2026-10-31)
- [x] A2 `runner.py` crash: uses `cache_dir(config)`, not `config.cache_dir`.
- [x] A3 Budget guard: `extract_structured` re-raises `BudgetExceeded` before the generic
      handler; `test_structured_reraises_budget_exceeded` covers it.
- [x] A4 `number_in_quote`: matches numeric tokens against scale words (`$1.20 billion`),
      no substring false positives; few-shot copies the printed number + unit.
- [x] A5 B4 schema fields restored: `prior_year_eps`, `consensus_eps`,
      `revenue_yoy_growth`, `tone`, `guidance_direction` raised/lowered/maintained/
      withdrawn/not_provided.
- [x] A6 Universe: Phase 2B builder replaces the 50 hard-coded mega-caps.
- [x] A7 Ingest window: configured `data.start_date`/`data.end_date`; with neither set,
      ingest raises instead of falling back to `date.today()`.
- [x] A8 Portability: `raw_path` stored relative to DATA_DIR (EDGAR + local adapter);
      scripts honour DATA_DIR; no `load_dotenv(override=True)` in library paths.
- [x] A9 Cache key includes temperature/max_tokens (and schema via prompt hash); only
      successfully parsed replies are cached.
- [x] A10 Retries honour `Retry-After` (header or body `retry_after_ms`), capped by
      `llm.retry_max_wait_seconds`.
- [x] A11 Ledger is lock-guarded; flushed on caller close and by the CLI.
- [x] A12 `consolidated_path` / `extractions.parquet` is written by `consolidate`.
- [x] A13 `<think>`/`<thinking>`/`<reasoning>` blocks stripped, including unclosed ones.
- [x] A14 Unknown config key → `ConfigError` (exit 2 from the CLI), not `TypeError`.
- [x] A15 `.gitignore` covers `.env`/`data/`/caches; `.env.example` added; `.env` is
      untracked and mode 600.

## B. Missing Phase 0 files
- [x] B1 `src/nowcast/paths.py`, `manifest.py`, `logging_setup.py` — path helpers moved
      out of `config.py` (which now re-exports them), named log handlers so nothing
      double-logs, manifests with config hash / git sha / package versions / prompt
      hashes / input fingerprints and secret redaction. Tests: `test_paths`,
      `test_manifest`, `test_config`.
- [x] B2 `src/nowcast/cli.py` — validate-config, build-constituents, estimate-scope,
      ingest, extract, run-all, with `--config` and repeated `--set`.
      (parse/aggregate/nowcast/evaluate/report arrive with their phases)
- [x] B3 `README.md` (input schemas, config table, resume/caching, troubleshooting,
      universe "Known limits"), `CHANGELOG.md`, `.env.example`,
      `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `requirements.lock.txt`.

## C. Extraction pipeline (Phase 3)
- [x] C1 schema, validators, review_queue, runner (tests green)
- [ ] C2 integration test: 3 fixture docs through parse+extract
- [ ] C3 Real run on 10 docs; hand-read 5 records vs source

## D. Phase 2B — S&P 500 universe builder
- [x] D1 config `universe:` section + `config.py` mirror
- [x] D2 `ingestion/universe/{__init__,base,wikipedia_source,historical_csv_source,
      cik_mapper,builder,validate}.py`
- [x] D3 fixtures + all named tests (wikipedia 6, historical 4, cik_mapper 5,
      validate 7, builder 5, subset/estimate 7)
- [x] D4 CLI `build-constituents`, `estimate-scope`
- [~] D5 Gate 2B: coverage 0.991 ≥ 0.98 ✅, audit clean (493–504 on 8 quarters) ✅;
      `unmapped.csv` review and the 10-interval spot-check need human judgement.
- [x] D6 README "Known limits" for universe sources (7 documented limits).

## E. Later phases
- [ ] E1 Phase 4 aggregation + privacy guardrail
- [ ] E2 Phase 5 nowcast + baselines + conformal intervals
- [ ] E3 Phase 6 evaluation + leakage + rule baseline
- [ ] E4 Phase 7 reporting + notebook + CI
- [ ] E5 Phase 8 hardening tests + real smoke run (~100 docs, free models only)

## F. Phase 7 pre-work (done early, because B3 needed it)
- [x] Notebook `notebooks/00_colab_bootstrap.ipynb` (21 cells, no business logic, no
      committed outputs; CI validates the JSON and that no cell carries outputs).
- [ ] `prompts/report/v1/report.md.j2`, `reporting/{charts,report}.py` — land with E4.
- [ ] CLI commands `parse`, `aggregate`, `nowcast`, `evaluate`, `report` — land with E1–E4.
