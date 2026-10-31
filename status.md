# status.md — where the build actually stands

Last updated: 2026-10-31

## Gates (run, not assumed)

```
ruff check .            -> All checks passed
ruff format --check .   -> 69 files already formatted
mypy src                -> Success: no issues found in 35 source files
pytest -q               -> 141 passed
```

Part D mechanical greps on `src`: no `TODO|FIXME|NotImplementedError`, no URL literals
(two `startswith(('http://', 'https://'))` scheme checks remain, which are protocol tests,
not endpoints), no absolute paths, no `print(`.

## Done and verified

### Phase 0 — scaffold (B1/B2/B3)
- `paths.py` owns the directory layout; `config.py` re-exports it so there is one
  implementation, not two. `DATA_DIR` wins over the YAML.
- `logging_setup.py` installs named handlers, so a CLI run followed by a test does not
  log twice. CLI output goes to stdout, errors to stderr. All `print()` calls are gone.
- `manifest.py` writes `data/manifests/<stage>.manifest.json`: config hash, git sha
  (None without commits), Python version, tracked package versions, seed, prompt hashes,
  input fingerprints and start/end times. Any secret value that reaches the text is
  replaced with `<redacted:VAR>`.
- `validate-config --strict` names a missing environment variable without printing values.

### Phase 1 — LLM layer
Free-model enforcement twice (config validation + caller), disk cache keyed on model,
temperature, max tokens and prompt digest, thread-safe ledger, `Retry-After` honoured.

### Phase 2 — ingestion
EDGAR 8-K Item 2.02 discovery with EX-99 selection by `<TYPE>` header, local manifest
adapter, parquet document index. The window comes from config; ingest raises rather than
using `date.today()`.

### Phase 2B — S&P 500 universe builder
Live build: **637 intervals, 635 companies, CIK coverage 0.991, 292 anomalies, 74
unmapped**. Member-count audit on 8 sampled quarters: 493, 493, 493, 495, 498, 498, 501,
504 — all inside 500 ± 8, none flagged.

Anomalies after the name-normalisation and 30-day-tolerance refinement:
`unknown_start 252, remove_missing 23, name_mismatch 10, start_conflict 5, add_existing 2`
(down from 385 total). Each kind is explained in the README's *Universe: known limits*;
none is a code defect. The remaining name mismatches are genuine renames (Avago→Broadcom,
Google→Alphabet, FMC Technologies→TechnipFMC) and are recorded, not silently corrected.

### Phase 3 — extraction
Schema, validators, review queue and a resumable runner. 100 real 8-K exhibits are indexed
in `data/document_index.parquet` (7 companies, capped by `edgar_docs_per_cik`); extraction
has been exercised on 2 documents with a free model.

### Repairs A1–A15
All fifteen closed, each with a regression test where the fix is behavioural.

## Open

1. **Gate 2B items 4–5** — human judgement, not code: review `data/universe/unmapped.csv`
   (74 delisted tickers) and spot-check 10 intervals against a second source.
2. **C2** extraction integration test through parse+extract on 3 fixture docs.
3. **C3** real run on 10 docs with 5 records hand-read against source text.
4. **E1–E5** phases 4–8 (aggregation, nowcast, evaluation, reporting, hardening).
5. First git commit has not been made yet; the repo has no history.

## Constraints in force
- Free OpenRouter models only; every model id must end in `:free`.
- Document downloads capped (~100) and per-CIK limited.
- Outputs under `reports/` and `aggregates/` will be index-level only.
- `.env` is untracked and mode 600; `.env.example` documents the variables.
