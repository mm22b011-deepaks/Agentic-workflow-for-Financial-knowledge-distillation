# claude.md — index-earnings-nowcast build rules

## Task
Proceed with the plan (Build Pack Parts A–E) using the provided instructions. Work in small
phases. Follow the FROZEN SPEC exactly. Stop at every gate until it is green.

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
Each phase: `ruff check . && mypy src && pytest -q tests/unit`, plus the phase's greps. Commit only
when green. If a phase fails 3 repair attempts, escalate per Part D.

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
