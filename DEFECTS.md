# DEFECTS.md — PROVISIONAL, NOT THE ORIGINAL

**This is not the `DEFECTS.md` the R-amendment refers to.** That file was never in this
repository and never arrived in any message. The amendment orders "fix defects B1 to B5
from `DEFECTS.md`", and I cannot fix five defects I have not been shown without inventing
them — so Gate R0 stays closed (see `DECISIONS.md` D4).

What is below is a **candidate list** built only from things I can point at in this
repository. Every item is marked `UNSURE` until the real list arrives or this one is
confirmed.

**Note on the letters.** The pre-amendment `tasks.md` used `B1`–`B5` for *Phase 0 files*
(B1 paths/manifest/logging, B2 CLI, B3 docs/CI). The amendment's `B1`–`B5` are a
*different* set — defects. Do not confuse them.

---

## Candidates

### CANDIDATE-1 `UNSURE` — EDGAR discovery returns zero disclosures (FIXED 2026-10-31)

Evidence: `edgar_index_headers_url_template` lacked the accession directory;
`/data/18230/{accession}-index-headers.html` → **403**, `/data/18230/{accession_nodash}/…`
→ **200**. Every CIK returned 0 disclosures, logged as a permissions-style error.
Fixed, with `test_headers_url_carries_the_accession_directory` and a live re-verification
(Caterpillar 16 disclosures, Coca-Cola 8). See `DECISIONS.md` D12a.

### CANDIDATE-2 `UNSURE` — 7 of 10 real extractions return empty completions (OPEN)

Evidence: `ok=3 failed=7`, 11 × `empty completion: reasoning used the whole token budget`.
A reasoning model consumes `max_tokens` on reasoning and returns no content. See D12b.

### CANDIDATE-3 `UNSURE` — the 100-row document index predates the Item 2.02 filter (OPEN)

Evidence: all 100 `downloaded_at` stamps are 13:30–13:32 UTC; the index includes
`0000021344-0001552781-24-000626`, an 8-K whose live `items` value is `5.02,9.01` — a COO
appointment, not an earnings release. The index must be rebuilt, not patched.

### CANDIDATE-4 `UNSURE` — `llm.models` is a list of strings, needs to become
`{id, context_tokens}` (KNOWN, SCHEDULED)

The R-amendment requires the mapping form so the packer can size against the real window.
Deferred to R2 by `DECISIONS.md` D5 so that R0 is not reopened for a breaking change.

### CANDIDATE-5 `UNSURE` — `requirements.lock.txt` is stale (OPEN)

`sqlalchemy`, `alembic`, `langchain-openai`, `tenacity` are required by R1 and R6 and are
not installed, so the lock file no longer describes the environment.

---

## What I need to close R0

Either the original `DEFECTS.md`, or a one-line description of each of B1–B5. With those,
this file is replaced rather than extended.
