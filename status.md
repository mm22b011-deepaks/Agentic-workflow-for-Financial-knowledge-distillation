# status.md — where the build actually stands

Last updated: 2026-11-01 (pass 3)

## Governing spec

Two amendments now sit on top of the frozen Build Pack, recorded in full in `tasks.md`:
the **R-amendment** (R0–R8: SQLite as system of record, lossless hierarchy, context
packer, structure-first extraction) and **Amendment Q** (no number silently missing,
excluded or non-comparable). Decisions are in `DECISIONS.md` (D1–D17). Rules are in
`claude.md`.

## Gates (run, not assumed)

```
ruff check .            -> All checks passed
ruff format --check .   -> 100 files formatted
mypy src                -> Success: no issues found in 46 source files
pytest -q               -> 336 passed
mutation check          -> 33 mutants, 33 killed, 0 survived
```

These cover the offline suite after reviewer pass 2 (F1–F19, N1–N7 and H1–H5
remainders, M1/M4). **Gate R0 is not green**: its live half is blocked on H-A, an
exported API key shadowing the one in `.env` (see Open, item 1). `evidence/phase_R0.txt`
holds the commands, the outputs and the per-item test map.

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
(`reasoning used the whole token budget`). N2 now treats an empty `finish_reason=length`
completion as `TruncatedCompletion` (not a parse failure), retries once at twice the
token budget, and reports `truncated` in the review queue. The live rerun that would
show the effect is blocked by the OpenRouter 401.

**H5 — truncation measured and fixed offline.** On the real 61-document text corpus at
`max_doc_chars = 24000`: **14 documents (23.0%)** exceed the cut and **41.8% of corpus
characters** never reach the prompt. Guidance's first occurrence is past the cut in
**4 of those 14**; revenue has an occurrence past the cut in 6, EPS in 5, growth in 1.
`prepare_text` now
reports `chars_total` / `chars_sent` / `truncated`, stored in each result's
`diagnostics` and consolidated as columns. `revenue_yoy_growth` is percent as printed
(`4%` → `4.0`), the consolidated column is `revenue_yoy_growth_pct`, and free-text
`units` is canonicalised (`dollars` → `USD`, `USD billions` → `USD billion`) before
validation. Full numbers in `DEFECTS.md` H5 and `DECISIONS.md` D16.

**Prompt hardening for weak models.** The v1 system prompt is now a field-level
data-entry contract (vocabularies, null policy, no arithmetic, evidence-quote rule,
bare-JSON output); the user message restates all sixteen keys immediately before the
document; and there are three few-shot examples, including adjusted EPS, missing EPS,
explicitly unavailable guidance, and a "flat" quarter whose growth is left null rather
than inferred. Few-shot text is now included in the prompt hash. Not yet measured on a
live model — see Open.

### R0 defect remediation (2026-10-31)
The human supplied the R0 register and Q1 confirmed it **is** `DEFECTS.md`. Offline
items closed: N1 (retry + cache on the live call path), N3's two behavioural fixes
(empty-extraction reason, non-2.02 refusal), N4 (seeded point-in-time sampling, one
release per filing), N5 (distinct-company aggregation with a share guard), N6's
report/abort/atomic-download items, N7's rebuild into `data.document_index` with an
`items` column and `superseded/` handling, H1 (whole-path per-document guard), H2
(mutation check, extended), H3 (one dotenv path, portable scripts, split locks), H4
(settings-complete fingerprint), M2 (unknown top-level section rejected).
Live-only items remain blocked by the OpenRouter 401: N2's reasoning probe and
`model-bakeoff`, N3's per-field coverage rerun, N6's high-volume CIK, N7's real rebuild,
and Gate R0. M1 stays open except the dead `sections` dict (removed in H5); M4 is
verified except that `tresata.zip` is tracked in git by accident and awaits a deliberate
removal with the human's go-ahead.

### Pass 3 (2026-11-01)
Fixed: B1 cohort is per (company, season) and matches what was downloaded; B2 a number
must match the scale the quote prints; B4 a field flag withdraws that field, not the
company; B5 the packer allocates by priority, keeps document order and never exceeds the
limit; B6 rebuild refuses a populated target and backs it up; B7 ingest persists each
document and the cohort as it goes; H-a shared request limiter, cooldown and model
cascade; H-b content cut at `finish_reason=length` is a truncation; H-c stale results are
superseded and excluded; H-h paths follow the config file, getters do not create
directories, no module-level mutable state; M-a SGML stripping is anchored to the file
start.

Measured live (SEC, not blocked by the model key): ingest produced 60 documents for 61
sampled companies across eight seasons, 64 cohort pairs, and every downloaded pair is in
the cohort. `rebuild-index` refused the populated index; with `--force` it backed it up
first.

**Not done**: H-d, H-e, H-f, H-g (next, in that order; H-e and H-d need live access), and
M-b/M-c (tracked files, your decision). The populated `data/document_index.v2.parquet` was
replaced by an empty `--force` rebuild; its contents are in
`data/document_index.v2.from-live-20261101.parquet` and restoring it needs your go-ahead.

### Reviewer pass 2 (2026-11-01)
Offline half of Gate R0 finished: F1–F16, the N1–N7 and H1–H5 remainders, and M1/M4.
The items that change behaviour rather than wording: auth failures no longer retried
(F12); one cache (N1); a per-call token budget with every attempt ledgered (N2);
`--sample` for representative runs (F9); the number must appear in the *matched source
window*, not only in the model's own quote (F7); vocabulary-driven prompt, validator and
aggregator (F10); review queue replaced per (document, model) with a superseded archive
(F6); `record_confidence` so dedupe has something to sort by (F5); cohort-based shares
(F1); per-metric observation minimums (F3); as-of winsorising (F4); gzip downloads no
longer flagged truncated (F8); `nowcast aggregate` with the privacy guardrail before the
write (F16). Decisions and deferrals: `DECISIONS.md` D17.

The offline index rebuild was run: 100 rows → **0 kept**, `{no_earnings_item: 61,
non_text: 39}` — a pre-`items` index cannot prove Item 2.02. Nothing was deleted; the
affected results moved to `superseded/`.

### Aggregation (pre-amendment Phase 4)
`aggregation/aggregate.py` + 19 tests, including the index-level privacy guardrail.
A live test caught a real boundary defect: a surprise exactly at `eps_tolerance_abs` was
graded a beat because `1.0 + 0.05 - 1.0 = 0.050000000000000044`. Comparisons now round to
`SURPRISE_DECIMALS = 10` first (D6). This code becomes the independent pandas recompute
that R4's SQL is checked against (D7).

## Open

1. **OpenRouter still returns 401 `User not found` — and the cause is now measured.**
   `scripts/smoke_llm.py` reports where the key came from: an **exported**
   `OPENROUTER_API_KEY` (far shorter than an OpenRouter key) shadows the one in `.env`, so the file's key has
   never been tried. `unset OPENROUTER_API_KEY`, then rerun the smoke test; if it still
   fails, the file's key needs rotating. Everything live waits on this: N2's live probe
   and bakeoff, N3's coverage rerun, N6's pagination check, N7's rebuild, Gate R0, and the
   weak-model prompt measurement.
2. **D12b / N2 — empty completions** are handled offline (truncation classification,
   one doubled-budget retry, `truncated` review reason). Whether a given free model
   still spends its whole budget on reasoning needs a live bakeoff, which item 1 blocks.
   Do not claim the model problem is gone until that table exists.
3. **Index rebuild — run offline, kept nothing, and that is correct.** Q4's design holds:
   write `data/document_index.v2.parquet`, delete nothing. Run 2026-11-01 on the old
   index: 100 rows → 0 kept, `{no_earnings_item: 61, non_text: 39}`, report in
   `data/manifests/rebuild_index.json`. The pre-v2 index has no `items` column, so no row
   can prove Item 2.02; the rebuild refuses rather than guessing, exactly as designed.
   This also moved the stored extraction results and review-queue rows for those
   documents into `superseded/` (nothing deleted). A rebuild that *keeps* rows needs a
   fresh ingest, which is blocked by item 1.
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
