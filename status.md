# status.md — where the build actually stands

Last updated: 2026-10-31

## Governing spec

Two amendments now sit on top of the frozen Build Pack, recorded in full in `tasks.md`:
the **R-amendment** (R0–R8: SQLite as system of record, lossless hierarchy, context
packer, structure-first extraction) and **Amendment Q** (no number silently missing,
excluded or non-comparable). Decisions are in `DECISIONS.md` (D1–D12). Rules are in
`claude.md`.

## Gates (run, not assumed)

```
ruff check .            -> All checks passed
ruff format --check .   -> 76 files already formatted
mypy src                -> Success: no issues found in 37 source files
pytest -q               -> 167 passed
```

These are pre-amendment gates. **Gate R0 is not green** — see Open.

## Done and verified

### Phase 0 — scaffold
`paths.py` owns the layout (`config.py` re-exports, one implementation);
`manifest.py` writes config hash / git sha / package versions / prompt hashes / input
fingerprints and redacts secrets; `logging_setup.py` uses named handlers so nothing
double-logs. All `print()` calls are gone; CLI output on stdout, errors on stderr.

### Phase 1 — LLM layer
Free-model enforcement twice (config validation + caller), disk cache keyed on model,
temperature, max tokens and prompt digest, thread-safe ledger, `Retry-After` honoured.

### Phase 2 — ingestion
EDGAR 8-K Item 2.02 discovery with EX-99 selection by `<TYPE>` header; local manifest
adapter; parquet document index; configured ingest window.

**Fixed 2026-10-31 (D12a):** the index-headers URL omitted the accession directory, and
EDGAR answers **403** (not 404) for that, so discovery silently returned 0 disclosures
for every CIK. Verified live both ways: broken URL → 403, correct URL → 200; then
Caterpillar → 16 disclosures, Coca-Cola → 8, with the non-earnings 5.02 filing correctly
excluded. `validate_config` now rejects a template without `{accession_nodash}`.

### Phase 2B — S&P 500 universe
Live build: **637 intervals, 635 companies, CIK coverage 0.991, 292 anomalies, 74
unmapped**. Member-count audit on 8 quarters: 493, 493, 493, 495, 498, 498, 501, 504 —
none flagged. Anomaly breakdown: `unknown_start 252, remove_missing 23, name_mismatch 10,
start_conflict 5, add_existing 2`; the name mismatches are genuine renames
(Avago→Broadcom, Google→Alphabet, FMC Technologies→TechnipFMC), recorded not corrected.

### Phase 3 — extraction
Schema, validators, review queue, resumable runner. C2 integration test passes on three
fixture documents (parse → extract → consolidate, resume makes zero calls, an unparseable
reply costs exactly `1 + max_repairs` and lands in the review queue as `llm_failed`).

**Real run 2026-10-31 (D12b):** `scripts/extract_sample.py 10` →
**ok=3, failed=7**, every failure an empty completion
(`reasoning used the whole token budget`). The model spent its `max_tokens` on reasoning
and returned no content. Open, and the first genuine R0 defect.

### Aggregation (pre-amendment Phase 4)
`aggregation/aggregate.py` + 19 tests, including the index-level privacy guardrail.
A live test caught a real boundary defect: a surprise exactly at `eps_tolerance_abs` was
graded a beat because `1.0 + 0.05 - 1.0 = 0.050000000000000044`. Comparisons now round to
`SURPRISE_DECIMALS = 10` first (D6). This code becomes the independent pandas recompute
that R4's SQL is checked against (D7).

## Open

1. **Gate R0 blocked on `DEFECTS.md`** (D4). The amendment orders fixes to defects B1–B5
   "from `DEFECTS.md`", but that file has never existed in this repo or arrived in any
   message. I will not invent five defect definitions and call the gate green. A
   provisional candidate list sits in `DEFECTS.md` for confirmation.
2. **D12b — empty completions** from the reasoning model on 7 of 10 documents. Needs a
   measured model choice, not a guess.
3. **Index swap blocked.** `data/document_index.parquet` still carries 39 `.jpg` rows;
   the cleaned 61-row file is `data/document_index.text_only.parquet`. Three attempts to
   replace it were refused by the local-destruction guard. Needs an approved `mv`.
   Rebuilding the index from scratch is now also possible, since D12a is fixed.
4. **Gate 2B items 4–5** — human judgement: review `data/universe/unmapped.csv`
   (74 delisted tickers) and spot-check 10 intervals against a second source.
5. **`requirements.lock.txt` stale** — `sqlalchemy`, `alembic`, `langchain-openai`,
   `tenacity` are required by R1/R6 and are not installed yet.
6. **Colab notebook never actually run in Colab** — the Gate 7 requirement stands.
7. **Needle-recall margin** — "within an agreed margin of edge recall" is the human's
   call; a proposal will follow the first sweep's real numbers.

## Amendment Q — nothing built yet

Recorded in `tasks.md` PART 1B and `DECISIONS.md` D8–D11. Folded into the R phases
(taxonomy at R0/R3, tables on R1's migration, events in R4, JSON writers at R7) rather
than built as a parallel track, because Q's tables are foreign-keyed to R1 and R4.

## Constraints in force

- Free OpenRouter models only; every model id must end in `:free`.
- Numbers are computed by code, never by an LLM.
- No output under `outputs/json/index`, `aggregates/` or `reports/` may carry a ticker,
  CIK, company name or sector.
- No NaN without a status and reason code (Amendment Q).
- Downloads capped (~100) and per-CIK limited.
- `.env` is untracked and mode 600; secrets are never printed or logged.
