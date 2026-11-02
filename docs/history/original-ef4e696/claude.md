# claude.md — index-earnings-nowcast build rules

## Task
Proceed with the plan (Build Pack Parts A–E) using the provided instructions. Work in small
phases. Follow the FROZEN SPEC exactly. Stop at every gate until it is green.

Two amendments override parts of the frozen spec. Both are recorded in full in
`tasks.md` (PART 1 and PART 1B) and their decisions in `DECISIONS.md`:

1. **R-amendment — course correction + optimization.** Lossless hierarchy
   (document → company_period → sector_period → index_period); numbers aggregated by
   SQL/pandas in code, **never** by an LLM; every LLM call through one context packer
   with a token budget and edge-aware ordering; **SQLite (WAL, single file) is the system
   of record** and parquet/CSV are exports only; standard tools only (LangChain,
   SQLAlchemy 2.0, Alembic, pydantic v2, tenacity, scikit-learn, pytest, hypothesis);
   measured speedups only. Phases **R0–R8**, each gated.
2. **Amendment Q — data-quality and nuance output.** No number is ever silently missing,
   excluded or non-comparable: every gap, event and exclusion is a structured,
   schema-validated JSON record with a code from a **versioned taxonomy file**, an
   explanation and evidence. The LLM reports only what the document states; the code
   reports everything else. Taxonomy codes live in `configs/quality_taxonomy.yaml`, never
   in Python.

### Standing rules added by the amendments
- **Never ask an LLM to sum, average, compare or compute any number.** Arithmetic is
  code (SQL or pandas).
- **Never replace or delete leaf facts with summaries.** Every upper-level number
  traces through `node_facts`/`node_edges` to leaf facts with their quotes.
- **Never send more tokens than `context.target_tokens`**, and never fill the full model
  window. Context length is probed from the provider, never hard coded.
- **Never hard code** a sector map, ticker, URL, concept name, taxonomy code, or model
  context length.
- **Never expose company or sector identifiers** in `outputs/json/index` or `reports`
  unless `reporting.max_detail_level` allows it — and never without the NDA owner's
  written confirmation.
- **No NaN without a reason.** Every missing metric carries a `node_metric_status` and a
  `status_reason` drawn from the taxonomy.
- **Never claim a test, benchmark or recall number not run and seen.** If a path was
  exercised only on a fixture, say so.

## Hard constraints
- **Download minimal documents.** Target ~100 real documents total (e.g. 100 8-K earnings
  releases). Do not bulk-scrape EDGAR. If 100 pass end to end, scale up only after explicit
  go-ahead.
- **Free OpenRouter models only.** Parsing and extraction must use `:free` model IDs from
  OpenRouter. No paid models, ever, for any step. A paid model ID in config or code is a
  defect. (A stronger model may be used only for human-requested code review of the source,
  never for document parsing or extraction.)
- **Secrets never in git.** `OPENROUTER_API_KEY` and `SEC_USER_AGENT` live in the project-root
  `.env` (git-ignored) and are read from the environment. Never print them, never log them.
- Outputs are index-level: no ticker or CIK may appear under `reports/` or `aggregates/`.

## Rules (Part A, verbatim intent)
1. Output every file in full. Never `...`, "rest unchanged", `TODO`, bare `pass`, or pseudo-code.
2. Create only the files listed for the current phase. No renamed/moved modules, no extra config
   keys or schema fields.
3. Python 3.10+. Type hints on every function. One-line docstring on every public function.
   Single quotes. pathlib only. No global mutable state. No `print` (use logging).
4. NO HARD CODING. Tickers, dates, URLs, model IDs, paths, thresholds, prompts, seeds and limits
   come from `configs/config.yaml` or environment variables. Allowed literals: 0, 1, None, empty
   strings, schema field names, column names.
5. Never invent library functions. If unsure an API exists, write `UNSURE: <api>` and use the
   simplest standard-library alternative.
6. Never invent data, results or test output. Never claim a test passed without seeing output.

## Gates
Each phase: `ruff check . && ruff format --check . && mypy src && pytest -q`, plus the
phase's greps. Commit only when green. If a phase fails 3 repair attempts, escalate per
Part D.

Amended gates (each must be GREEN before the next phase starts):

| Gate | Requirement |
|------|-------------|
| R0 | ruff + mypy + pytest green; Phase 0 files exist; `test_validators` + `test_review_queue` pass; 10 real documents ingested; `evidence/phase_R0.txt` |
| R1 | all green + `PRAGMA integrity_check` ok |
| R2 | unit tests green; needle sweep run per model with the recall table shown; `context.target_tokens` set from measured middle-position recall, logged in `DECISIONS.md` |
| R3 | green + 10 real documents end to end; human spot-checks 5 facts |
| R4 | green + index output contains no identifiers |
| R8 | ~10 real documents with benchmark and needle tables in the report |
| Q | all Q tests green + real output shown for `documents/<id>.json`, index JSON and the data-quality report |

## Part D verification prompts
- **D1 mechanical checks:** ruff / ruff format --check / mypy / pytest, then greps for
  `TODO|FIXME|NotImplementedError`, `https?://`, `/content|/home/|C:`, `print(`, model names in
  `src`, and `ticker|cik` in `src/nowcast/reporting`. Any match is a defect.
- **D2 self-audit:** ten YES/NO questions on file scope, type hints/docstrings, hard-coding,
  test names, placeholders, network in tests, libraries, schema/config fidelity, batch crash
  safety, identifier leakage. Fix every NO.
- **D3 repair:** state root cause in one sentence, show full corrected files only, name the
  re-run command. On the 3rd attempt, write ESCALATE.
- **D4 reviewer:** strict review at Gates 1, 3 and 5 — runtime bugs with file/line, spec drift,
  hidden hard-coding/global state/swallowed exceptions, leakage risk, trivial tests. Verdict
  PASS / PASS WITH FIXES / FAIL.

## Operating notes
- Set `DATA_DIR` so caches, raw files and extractions persist across sessions.
- Transcripts are not on EDGAR: start with 8-K earnings releases, add transcripts via the local
  manifest adapter.
- Run `python -m nowcast.cli validate-config --strict` before any real run.
