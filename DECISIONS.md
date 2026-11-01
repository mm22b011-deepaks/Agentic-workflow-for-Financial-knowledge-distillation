# DECISIONS.md — deviations, defaults and their reasons

Every amendment-driven decision lands here, with what it replaced, why, and what would
make me revisit it. Dated entries only; no entry is edited after the fact except to add
a superseding line.

Format: `D<n>` — decision · `Provisional` / `Final` · the phase that depends on it.

---

## D1 — H1: extraction schema (Provisional, decided 2026-10-31)

**Decision.** Keep the full pre-amendment record: `reported_eps`, `prior_year_eps`,
`consensus_eps`, `eps_basis`, `revenue`, `revenue_yoy_growth`, `guidance_direction`,
`guidance_metric`, `tone`, `theme_mentions`. The LLM reports only what the text states,
with a `null_reason` and an `evidence_quote`; it never derives, compares or computes.
EPS and revenue become **authoritative from SEC XBRL** in R3; the LLM-stated figures are
kept alongside so a disagreement can be detected and queued as `source_conflict` rather
than silently resolved.

**Why.** The amendment's default is "restore B4 fields". They are already present in
`src/nowcast/extraction/schema.py` — `prior_year_eps`, `consensus_eps`, `tone` and
`guidance_metric` are all declared — so no restoration was needed. The second half of the
default (XBRL as the numeric source of truth) is a new capability and lands with R3.

**Consequence.** No schema change and no migration of already-extracted rows is required
by this decision. R3 adds a `source_kind` discriminator and `available_date` per fact,
which the R1 `facts` table already reserves.

**Revisit if.** XBRL coverage for a period turns out too thin to carry the numeric side;
then the LLM-stated figures would need to be promoted rather than cross-checked.

---

## D2 — H2: universe (Provisional, decided 2026-10-31)

**Decision.** Keep the Phase 2B builder as built: `universe.source: wikipedia_changes`,
point-in-time intervals, tickers mapped to CIK through SEC's own ticker file. Live result:
**637 intervals, 635 companies, CIK coverage 0.991**, member-count audit inside 500 ± 8
on all eight sampled quarters. Companies whose ticker could not be mapped — **74
delisted** — stay in `data/universe/unmapped.csv` and are **not** back-filled by hand or
by guess.

**Why.** The build clears its own gate (coverage ≥ 0.98, audit clean). Back-filling
delisted tickers by hand would inject unverifiable membership into a point-in-time
series, which is worse than a documented gap: the nowcast's `n_expected` denominator must
be defensible.

**Consequence.** `n_expected` is a slight undercount for quarters where an unmapped
company was a member. The build report states the count; the README's *Universe: known
limits* section documents it. Delisted names contribute no documents anyway, since EDGAR
filings for them fall outside the configured window.

**Revisit if.** A second source (the price-weighted or CRSP-derived membership list) can
supply the missing 74; then the intervals are rebuilt rather than patched.

---

## D3 — H3: reproducibility and portability (Provisional, decided 2026-10-31)

**Decision.** In order of precedence: an explicitly set environment variable
(`DATA_DIR`) beats the YAML; the YAML `paths.data_dir` beats the built-in default. Every
stored path is **relative to `DATA_DIR`**; nothing absolute is written into a row, a
manifest or a label. Each stage writes `data/manifests/<stage>.manifest.json` carrying the
config hash, git sha, Python version, versions of the packages that could change a
result, the seed, prompt hashes and input fingerprints. Any secret value that reaches a
manifest is replaced with `<redacted:VAR>`.

**Why.** The notebook has to run in Colab, where the runtime disk is ephemeral and Drive
is mounted at a different absolute path each session; and a manifest that carries
absolute paths cannot be compared across two machines. The environment-beats-YAML order
is what the specification asked for (Colab secrets must not be shadowed by a repo file).

**Consequence.** A run is reproducible only if the same `DATA_DIR` view is restored —
which is what the manifest's input fingerprints verify. Tests assert portability by
copying the SQLite file to another directory and querying it (R1
`test_db_file_copy_is_portable`).

**Revisit if.** A stage needs an absolute path for a reason that cannot be made relative
(e.g. an external mount); then the manifest records it as an input, never inside a row.

---

## D4 — `DEFECTS.md` was not supplied; R0 defect repair is blocked (Final, 2026-10-31)

**Decision.** Do **not** invent the content of `DEFECTS.md`. The amendment orders
"fix defects B1 to B5 from `DEFECTS.md`", but that file is not in the repository and was
never provided in any turn of this session. `DEFECTS.md` now exists as a **provisional
candidate list** with every item marked `UNSURE` and requiring the human's confirmation
before any code is changed. R0's gate therefore cannot be declared green.

**Why.** The pre-existing `tasks.md` used `B1`–`B5` for *Phase 0 files* (B1 paths/
manifest/logging, B2 CLI, B3 docs/CI). The amendment's `B1`–`B5` are a different set —
*defects* — from a document I have never seen. Treating them as the same would silently
convert "build the file" into "fix the bug" and produce a gate that says green while the
real defects are untouched. That is the failure mode the amendment exists to prevent.

**Consequence.** R1–R8 remain blocked at their entry gate until either the file arrives
or the human confirms the provisional list. Work that is independent of the defect list
(reading the live extraction run, recording decisions, the index-replacement decision)
continues.

**Revisit when.** `DEFECTS.md` arrives, or the provisional list is confirmed or replaced.

---

## D5 — Config additions are applied per phase, not all at once (Provisional, 2026-10-31)

**Decision.** The amendment's config keys are appended in the phase that consumes them:
`db.*` with R1, `context.*` and the `llm.models` mapping change with R2, `xbrl.*`,
`extraction.section_select_enabled` / `section_top_k` / `tasks` and `cascade.*` with R3,
`hierarchy.*` with R4, `narrative.*` with R5, `needle.*` and `benchmarks` with the
sweep/benchmark steps. Not one of them is added early.

**Why.** Two hard constraints collide if they are added at once. `validate_config`
rejects unknown keys, so a key must exist in `config.py` the moment it is in the YAML.
And changing `llm.models` from a list of strings to a list of `{id, context_tokens}`
mappings is a breaking change that touches the caller, the cache key, the scripts and
every test that names a model — while R0 is still open. Making that change before the
R0 gate is green is exactly "building on a broken base".

**Consequence.** `configs/config.yaml` gains no new keys yet; `tasks.md` carries the full
appended block as the specification of record. Nothing in R0 depends on any of them.

**Revisit if.** The human prefers the keys in the YAML up front; then the mapping change
must land together with the caller and test updates in one green step.

---

## D6 — Surprise tolerance is compared on a rounded difference (Final, 2026-10-31)

**Decision.** `beat` compares the surprise rounded to `SURPRISE_DECIMALS = 10` against
`extraction.eps_tolerance_abs`.

**Why.** A live test caught the defect: a reported 1.05 against a 1.00 consensus differs
from the 0.05 tolerance by 4.4e-17 in binary floating point, so a figure sitting exactly
on the tolerance boundary was graded a beat. Rounding before comparison makes the boundary
mean what the configuration says.

**Consequence.** `test_beat_tolerance_boundaries` pins both edges, positive and negative.
The R4 SQL implementation must apply the same rounding, or
`test_sql_matches_independent_pandas_recompute` will fail — that is the intended alarm.

---

## D7 — Aggregation stays in pandas as the independent recompute (Provisional, 2026-10-31)

**Decision.** R4 computes `node_metrics` in SQL, as the amendment requires. The existing
pandas `aggregate_index` is **kept**, not deleted, and R4 gains
`test_sql_matches_independent_pandas_recompute` comparing the two on the same inputs.

**Why.** The amendment asks for SQL aggregation *and* for a test that an independent
recompute agrees. Keeping the pandas path gives that test a real second implementation
rather than a tautology over the same queries. It also preserves index-level output for
anyone working without a database.

**Consequence.** Two implementations must be kept in step. The guardrail
`assert_index_level_only` and the review-queue exclusion apply to both, and the
cross-check test is the enforcement.

---

## Open questions that are the human's to answer

- **Q1.** `DEFECTS.md` — please supply it, or confirm/replace the provisional list.
- **Q2.** The needle sweep's acceptance margin: "middle-position recall within an agreed
  margin of edge recall". A proposal will be made from the first sweep's real numbers;
  the margin itself is not mine to set.
- **Q3.** `reporting.max_detail_level` — the amendment says identifiers may be exposed
  only at `sector`/`company` level **and** with the NDA owner's confirmation. Default
  stays `index`; nothing else is enabled until that confirmation exists in writing.
- **Q4.** Replacing `data/document_index.parquet` with the cleaned 61-row index was
  blocked by the local-destruction guard three times. Needs an approved `mv`.

---

## D8 — Amendment Q is folded into the R phases, not run as a separate track (Provisional, 2026-10-31)

**Decision.** Q's work is assigned to the phase that already owns the same file or table,
rather than built as a parallel feature: taxonomy + schemas in R0/R3, the four new tables
and the `node_metrics.status` columns ride on R1's Alembic migration, event handling
extends R4's `company_period` build, and the four JSON writers land with R7's reporting
layer. Gate Q is checked once, after R7.

**Why.** Q's tables are foreign-keyed to R1's `facts` and R4's `nodes`; building them
before those exist would mean writing a migration against tables that don't exist and
then rewriting it. Q's index JSON is literally an export of R4's `node_metrics` joined to
the `v_index_notes` view. Splitting them would double the work and guarantee drift.

**Consequence.** Amendment Q adds **no** new phase numbers and does not delay R0's gate.
`tasks.md` PART 1B carries the full Q checklist so nothing is lost.

---

## D9 — Taxonomy codes live only in `configs/quality_taxonomy.yaml` (Final, 2026-10-31)

**Decision.** No taxonomy code string appears in Python. `src/nowcast/quality/` loads the
YAML once into a frozen registry; Pydantic validators reject any `status`, `reason_code`
or `pipeline_code` not in that registry. The registry carries a `taxonomy_version`
derived from the file's content hash, which is written into every output JSON.

**Why.** The amendment forbids hard-coded taxonomy codes, and a content hash is the only
honest way to version a file that is meant to be edited: a version string typed by hand
can drift from the codes it claims to describe.

**Consequence.** `test_taxonomy_loads_and_rejects_unknown_code` is the enforcement. A
typo in a model output becomes a validation issue and a review-queue row, not a silently
accepted value.

---

## D10 — `not_stated` vs `not_applicable` vs `not_comparable` are structurally distinct (Final, 2026-10-31)

**Decision.** Three separate `field_status` values, each with a required explanation and
its own validation rule:

| Status | Means | Evidence quote |
|--------|-------|----------------|
| `not_stated` | the document is silent on the field | not required |
| `not_applicable` | the field cannot exist for this company or period (e.g. the company states it gives no guidance) | required — the statement that establishes it |
| `not_comparable` | a value exists but cannot be compared with the prior period because of an event | required — the event quote |

**Why.** The amendment is explicit that one must never stand in for another, and the three
have opposite consequences for aggregation: `not_stated` is a coverage gap,
`not_applicable` is a legitimate absence that must not depress `share_reported`, and
`not_comparable` is a reported-but-unusable input that `quality.event_policy` acts on.
Collapsing them would make `share_reported` and `eps_growth_agg` quietly wrong.

**Consequence.** `test_not_stated_vs_not_applicable_vs_not_comparable_roundtrip` pins the
distinction through the whole path, and R4's `n_expected` counts only `not_stated` and
`not_yet_reported` as missing.

---

## D11 — Event policy default is `exclude_from_growth` (Final, 2026-10-31)

**Decision.** `quality.event_policy: exclude_from_growth`. A company with a
non-`none` `comparability_impact` keeps its place in `n_reported` and `share_reported`
but contributes no growth input; the exclusion is recorded once per company as a
`node_notes` row and rolled up as a count.

**Why.** This is the amendment's default and it is also the defensible one: dropping the
company entirely would understate `share_reported` (it did report), and including it would
put a merger-driven jump into `eps_growth_agg` as if it were organic. Counting the
company but not its growth is the only choice that keeps both numbers truthful.

**Consequence.** `test_event_policy_exclude_from_growth_keeps_company_counted_as_reported`
and `test_count_conservation_with_exclusions`
(`n_inputs + excluded == n_expected - not_yet_reported`) are the guards. Switching the
policy is a config change, never a code change.

---

## D12 — Two ingestion/extraction defects found by live runs on 2026-10-31 (Final, fixed)

These are the closest thing to `DEFECTS.md` I can substantiate from this build, so they are
recorded here with the evidence. They are **not** an inferred mapping of B1–B5.

### D12a — Wrong document directory in the EDGAR index-headers URL (fixed)

**Observed.** `edgar_index_headers_url_template` was
`.../data/{cik}/{accession}-index-headers.html`, with no accession directory. Live probe:

| URL | Result |
|-----|--------|
| `/data/18230/0000018230-25-000013-index-headers.html` | **403** |
| `/data/18230/000001823001300/...` (correct directory) | 200 |

**Why it mattered.** A 403 reads as a permissions or User-Agent problem, so the failure
was logged as "index headers failed" for every accession and discovery returned **0**
disclosures for CIKs that plainly have earnings filings. The earlier 100-document index
was built before `edgar_earnings_items` existed, so nothing re-exercised this path.

**Fix.** The template now carries `{accession_nodash}/`, `_headers_url` passes it, and
`validate_config` rejects a template without it. Live re-verification: Caterpillar → 16
earnings disclosures, Coca-Cola → 8, and the 5.02 (COO appointment) filing that had
wrongly entered the 100-doc index is correctly excluded.
Test: `test_headers_url_carries_the_accession_directory`.

### D12b — 7 of 10 real extractions returned an empty completion (open)

**Observed.** `scripts/extract_sample.py 10` on `nvidia/nemotron-3.5-lightning:free`:
`ok=3 failed=7`, with 11 log lines of `empty completion: reasoning used the whole token
budget`, and the failures surfacing as LangChain `OUTPUT_PARSING_FAILURE`.

**Cause.** A reasoning model spent the entire `max_tokens` budget on internal reasoning,
leaving no content. Not a parsing defect: the model returned nothing to parse.

**Status.** Open — this is the first genuine R0 defect. Candidate fixes, in order of
preference: exclude reasoning models from the extraction model list and use a
non-reasoning `:free` model for the narrow schemas; cap reasoning via
`max_reasoning_tokens`; raise `max_tokens` only if the provider allows it on the free
tier. Not yet decided, because it needs a measured comparison, not a guess.

---

## D13 — H2: how test strength is measured (Final, decided 2026-10-31)

A behaviour that no test would notice if it changed is not tested. The audit signal is a
small, hand-written mutation check (`scripts/mutation_check.py`) over the four modules
where a silent bug would corrupt output: `validators.py`, `edgar.py`, `runner.py`,
`aggregate.py`. Twenty mutants, each an exact edit a person would actually make, each
paired with the test file that should catch it.

**Why not a full mutation-testing framework.** `mutmut`/`cosmic-ray` rewrite whole
modules and take tens of minutes on this suite; the value here comes from *which* edits
are made, not from the count. Every mutant is listed in the script with the test file
expected to kill it, so a new survivor is a specific, readable gap.

**Measured.** First run: 20 mutants, 15 killed, **5 survived**. The five were pinned with
five tests (see `DEFECTS.md` H2), after which: **20 killed, 0 survived**, re-confirmed
after the H3 import refactor. The script restores each file's bytes in a `finally` and
verifies the sha256, so a crash cannot leave a mutant in the tree.

**Standing rule.** When behaviour in one of these four modules changes, add or update a
mutant before trusting the suite's green.

## D14 — H3: one dotenv path, one reporting channel, locks split by use (Final)

- **Dotenv.** `nowcast.envfile.load_dotenv_without_overriding` is the only loader;
  `override=False` is the only mode. The CLI and `scripts/_bootstrap.py` both call it, so
  a checked-out `.env` can never clobber a Colab secret or shell export.
  `test_scripts_and_cli_share_one_dotenv_rule` fails if a second implementation appears.
- **Reporting.** Scripts report through `nowcast.logging_setup.setup_logging`, the same
  formatter and stdout/stderr split the CLI uses. `print()` is gone from every script
  that is part of the pipeline; `mutation_check.py` keeps `print` because its output is
  a report read by a person, not a pipeline stage.
- **Inputs.** Ticker lists and model candidate lists are inputs: `--tickers`
  (default `inputs/tickers.txt` under the data root) and `--models` / `--models-file`
  (default: the configured models). No ticker, CIK, URL or model id is baked into a
  script.
- **Locks.** Two files rather than one: `requirements.lock.txt` is the runtime set
  (`uv export --no-dev`, 58 pins) and `requirements-dev.lock.txt` adds test and lint
  tooling (`--extra dev`, 76 pins). Both are regenerated from `pyproject.toml` by uv and
  neither carries the editable local path the old file did.

## D15 — N4: how a capped ingest decides what to read (Final, decided 2026-10-31)

A document cap plus CIK-sorted walking is a sampling decision made by accident. The
ingest stops at `data.edgar_max_documents`, so whatever order the companies are visited
in decides the sample. Two rules now apply, in `ingestion/sampling.py`:

1. **Walk order.** `season_sample` takes the members active at the start of each calendar
   quarter in the window, draws `universe.subset_n` of them with `random.Random(
   universe.subset_seed)` (all of them when it is 0), shuffles, and concatenates the
   quarters. The result is a seeded permutation of the union, so a capped run is a spread
   sample of the index. Membership is tested at the season's first day, so a mid-quarter
   joiner is not credited to a quarter it was not a member of. Every member appears once.
2. **One document per filing, one per season.** `select_filings` keeps the
   highest-priority exhibit of each accession (`EX-99.1`, then `EX-99`, then `EX-99.2`),
   then one filing per calendar quarter, newest season first. Without this the per-company
   cap of 3 documents was spent on one quarter's release plus its supplement, and the
   other quarters were never seen.

**Why the seed is in the manifest.** `Manifest.sample` records companies, seed, seasons
and skip counts, and `ingest_summary.json` records the same. A capped run that cannot say
how it chose is not reproducible, only repeatable.

**Deviation from the register.** The register asks for exhibit priority "from config";
it is a module constant (`EXHIBIT_PRIORITY`) instead. It encodes EDGAR's own filing
convention rather than a deployment choice, and no other code reads it. If the human
wants it configurable, the change is one key plus a `_tuple` in `load_config`.

**Not measured.** This is offline behaviour only. How many of the 519 members actually
have a 2.02 filing in each quarter is a live question and stays blocked with the rest of
the live work.

## D16 — H5 and prompt hardening: measured truncation, printed percent, canonical units (2026-10-31)

### What was measured, and why it decided the fix

At `max_doc_chars = 24000`, over the 61 parseable text documents in the current index:

| Measure | Result |
|---------|--------|
| Documents over the cut | **14 of 61 (23.0%)** |
| Characters never sent | **515,868 of 1,232,947 (41.8%)** |
| First occurrence after the cut: guidance / growth | **4 / 1 of 14** |
| First occurrence after the cut: EPS / revenue | 0 of 14 |
| Any occurrence after the cut: revenue / EPS / guidance / growth | 6 / 5 / 4 / 1 of 14 |

Search terms, applied case-insensitively to the same converted text the runner prepares:
EPS = `earnings per share|EPS`, revenue = `revenue|net sales`, guidance =
`guidance|outlook`, growth = `growth|grew`. Reproduce with
`python scripts/measure_truncation.py --index document_index.parquet`, which applies the
runner's own conversion and cut so the terms and the text cannot drift apart. The four
documents whose only guidance text sits past the cut are JPMorgan supplements
(77k–90k chars). The consequence is specific: the cut is not neutral for guidance. R2's
context packer is where selection changes; until then the honest response is to record
what was sent and how much was dropped, never to let a cut extraction look like a whole
one. That is why diagnostics ships before the packer.

### Conventions, now enforced in code and in the prompt

- **`revenue_yoy_growth` is percent as printed.** `4%` is `4.0`, never `0.04`. A model
  that returns a fraction is corrected only when the evidence quote carries a percent
  marker and the corrected digits appear in that quote. A printed `0.5%` stays `0.5`:
  scaling it to 50 would misread the quote. Spelled-out numbers ("eight percent") are
  not parsed; validation reports the mismatch instead of guessing.
- **`units` is canonical** `<CCY>` or `<CCY> <scale>` ("dollars" → `USD`,
  "USD billions" → `USD billion`, "£m" → `GBP million`). A scale-only label takes the
  record's currency. A label with neither part is preserved verbatim: dropping what the
  model said is a silent loss, and an unrecognised label is exactly what a human should
  see.
- **Normalise before validating.** Validation first would penalise a fraction the code
  can simply read correctly, and would put a correctable record into the review queue.
- **The consolidated column is `revenue_yoy_growth_pct`.** The unit belongs in the name,
  not in a reader's assumption.
- **The fixture keeps `0.08` for "up 8%" deliberately.** It is a *model reply*, not a
  golden output, and the integration/end-to-end tests assert the stored and consolidated
  value is `8.0`. Pre-correcting the fixture would remove the end-to-end proof that the
  correction runs. This deviates from the earlier plan to change it to `8.0`; the
  reason is test strength, not convenience.

### Diagnostics

`prepare_text` returns `DocumentText(text, chars_total, chars_sent)` with
`truncated = chars_sent < chars_total`. The result payload stores
`diagnostics: {chars_total, chars_sent, truncated}`, the outcome carries `truncated`,
and `consolidate` writes the three columns. Results written before H5 have no
diagnostics; they consolidate as `None`, not `False`, because "not measured" and "not
truncated" are different claims.

Naming deviation: the register says `doc_truncated`; the payload key is `truncated` to
match Q-PART 3 and the outcome flag. The `doc_truncated` *reason code* remains a Q-PART 3
task.

### Few-shot examples are part of the prompt

Found while writing the prompt rules: `prompt_hash` hashed the system and user templates
only, while `few_shot.yaml` is sent to the model as user/assistant messages. Editing an
example changed the prompt without invalidating stored results. `prompt_hash` now hashes
the canonical JSON of the few-shot tuple as well; `test_prompt_hash_changes_with_few_shots`
pins it. Consequence: every fingerprint changes with this release, so existing results
are stale by design and will be re-extracted on the next live run.

### Prompt hardening for weak models

The v1 system prompt is now a field-level data-entry contract rather than a short rule
list: every field is defined, `eps_basis` / `guidance_direction` / `tone` have explicit
vocabularies, GAAP is preferred when both bases are printed, segment revenue is excluded
from `revenue`, growth is the printed percent, `units` is `<CCY> <scale>`, each null
reason has its own rule, evidence quotes must contain the digits and the unit, arithmetic
is forbidden, and the reply is one bare JSON object. The user message restates all
sixteen top-level keys immediately before the document. The three synthetic few-shots
cover GAAP + growth, revenue only with missing EPS and explicitly unavailable guidance,
and adjusted EPS with a "flat" quarter whose growth stays null rather than being inferred
as 0.0; their units are canonical and their themes use the configured vocabulary.

**Not measured live.** Whether this helps the weakest free model is an empirical
question. The 401 blocks it; the measurement is queued as task P0 in `tasks.md`, with
per-field coverage, empty-completion rate, review-queue rate and 429 count required
before any improvement is claimed.

## D17 — Reviewer pass 2: what each fix decided, and why (2026-11-01)

### F2 — the 401 is a shadowed key

`scripts/smoke_llm.py` now reports the key's *source* (environment, `.env`, or missing),
its length and a sha256 prefix, and warns when an exported variable differs from the one
in `.env`. It never prints the key. Run on 2026-11-01: the warning fired — an exported
variable shadows the file, and the exported value is far shorter than an
OpenRouter key. So the key in `.env` has never actually been tried, and whether it works
is **unverified**. Details are in the `evidence/` output, not in this file. H-A stands:
`unset OPENROUTER_API_KEY`, rerun the smoke test, rotate if it still fails.

### F12 — status codes decide the exception, not one catch-all

`AuthError` (401/403) and `ModelNotFound` (400/404) are raised by the caller and never
retried; only 429, 5xx, timeouts and network errors are. In `run_extraction` an auth error
stops the run: the in-flight documents report `auth_failed`, the rest are never called,
and the error is re-raised rather than queueing N identical `llm_failed` rows. Deviation
from the prompt, which says "aborts like BudgetExceeded": a spend cap is an expected
outcome, a rejected credential is a broken deployment, so the latter raises.

### N2 — one budget per call, and every attempt ledgered

`with_max_tokens` and the shared ratchet are gone. `complete(model, messages,
max_tokens=None)` takes the budget per call; `RetryingCaller` doubles it for the retry
only. Any empty or whitespace-only content raises `EmptyCompletion`, subclassed as
`TruncatedCompletion` when `finish_reason == 'length'`. `message.reasoning` and
`reasoning_content` are read only to log their length. The ledger gains `finish_reason`
and `outcome` (`ok` / `truncated` / `empty`) and records **before** the raise, so the
calls that failed are visible.

One reasoning control: `llm.reasoning_control` ∈ `effort | max_tokens | none`, and
`validate_config` rejects setting both an effort and a token cap. The `reasoning`
parameter is sent only when the provider's models list says the model supports it, read
from `llm.models_url`; when the list cannot be read the parameter is sent, because a 400
is a clear failure while silently dropping it hides why a model reasons.

`model-bakeoff` is implemented and tested offline with a fake transport. **Not run live.**

### N1 — one cache

The write-only cache in `extract_structured` is deleted, with its parameter. The
`RetryingCaller` cache is the only one. The cache key includes the reasoning parameters,
because a reply sampled under a different reasoning budget is a different reply.

### F9 — a sample, not the head of the index

`extract --sample N --seed S` and `extract_sample --sample N` take one document per
company first (round-robin over a seeded company order), then a second per company, and
so on. `--limit` remains for debugging and now logs that it is not representative.

### F10 — one vocabulary, read from config

`extraction.eps_basis_vocab`, `guidance_direction_vocab`, `tone_vocab` and
`extraction.tone_scores` are the only source. The prompt templates receive them as
variables, the validator rejects an out-of-vocabulary value with `vocab_invalid`, and the
aggregator maps tone through `tone_scores`. Decisions:

- **`mixed`** is a real answer, scored **0.0** like neutral: a document saying both things
  must not pull the tone score either way. The prompt always offered it; the old validator
  rejected it and the old aggregator left it as a silent NaN. Both are fixed.
- **`withdrawn`** guidance is in the vocabulary and counts in **neither** the raise nor the
  lower share. A `guidance_withdrawn_share` column is **not** added: it is not in the
  output schema and that is an R4 decision, not a defect fix. Recorded so it is a
  decision, not an omission.
- **Unknown tone** is scored NaN and counted in a warning; never silently dropped.

### F7 — the number must be in the matched source window

`verify_quote` scores a quote against the whole document, so a 40-character quote with one
changed digit scores about 0.97 and passes. After the quote matches, the best-matching
window (`fuzz.partial_ratio_alignment`) is located in the source and the value's number
must appear **in that window**; otherwise `number_not_in_source` plus the confidence
penalty. The model's own quote is no longer the proof that the model is right.

### F11 — every field with a value is checked

`needs_review` loops numeric **and** text fields, and theme mentions with
`mentioned=True`. A truncated document adds `doc_truncated` whether or not the record
itself looks fine.

### N3 — `eps_missing` is its own reason

`empty_extraction` stays "no reported EPS **and** no revenue". Revenue without EPS is a
partial release and gets `eps_missing`.

### F6 — the queue is a verdict, not a log

`review_queue.replace_rows(document_id, model, rows)` replaces that pair's rows (an empty
list clears them) and archives the replaced rows under `<queue dir>/superseded/`.
Aggregation excludes per (document, model), so one model's flag no longer removes another
model's good record. `n_review_excluded` counts distinct companies excluded at that date,
not rows.

### F5 — dedupe uses a confidence that exists

`consolidate` writes `record_confidence` (mean confidence of the non-null core fields:
reported_eps, revenue, guidance_direction, tone). `per_document_metrics` reads it and
raises `DataError` when `dedupe_rule = max_confidence` and the column is absent: the old
code defaulted every confidence to 0.0 and resolved every duplicate by document id while
the config said "highest confidence".

### F1 — the denominator is the cohort

`ingest` writes `manifests/cohort.csv` (cik, season only). `aggregate_index` reports
`share_of_cohort` and `share_of_index`, and `share_reported` is the cohort share. Without
a cohort file the index itself is the cohort, so older runs keep working. A season whose
cohort is smaller than `min_constituents` is logged as `cohort_too_small:<season>`;
`min_constituents` is not lowered. The ingest log now says how many sampled companies the
cap can actually visit.

### F3 — per-metric observation minimums

`n_obs_beat`, `n_obs_growth`, `n_obs_guidance`, `n_obs_tone` and
`n_obs_theme_<name>` are output columns. A metric below `aggregation.min_observations` is
NaN with `metric_status_<name> = 'insufficient_observations'`. `guidance_ratio`'s
denominator counts companies that stated a raise **or** a lower.

### F4 — winsorising inside the as-of snapshot

The clip is computed per as-of date from the documents public by then.
`test_asof_value_unchanged_by_later_documents` pins that a later outlier changes nothing
earlier.

### F15 — the season is the filing quarter

Already the behaviour, and it stays: the filing date is knowable at as-of time, the
extracted fiscal pair is not. The `fiscal_period_consistency` diagnostic the prompt asks
for is **not implemented** — it is a new output column and belongs with R4.

### F8 — Content-Length is the encoded size

With `Accept-Encoding: gzip`, `Content-Length` is the compressed size and the body is
decoded, so the old check flagged every compressed page as truncated. The check now
compares the bytes actually downloaded and skips itself when a `Content-Encoding` is
present. **Not verified live**; the skip is what makes it safe.

### F14 — a bad window is not every company's zero

A `DataError` about the window is re-raised, not caught per company. A missing
`data.end_date` is a `ConfigError` (no more `date.today()`). A non-404 submissions failure
records `cik_failed:<status>`. Following `filings.files` is **not implemented**: it needs
a live high-volume CIK to verify the pagination shape; `data.edgar_filing_files_url_template`
is in place for it.

### F16 — the pipeline reaches the aggregate

`nowcast aggregate` reads `extractions.parquet`, calls `aggregate_index`, calls
`assert_index_level_only` **before** writing, and writes parquet and CSV. `run-all` runs
validate-config → build-constituents → ingest → extract → aggregate and stops at the first
non-zero code. `nowcast`, `evaluate` and `report` are not added.

### Hygiene (M1, M4, H3, F17–F19)

- `HTTP-Referer` comes from `llm.referer_url`; the header is omitted when empty.
  `X-Title` keeps the app name.
- One `:free` constant (`config.FREE_MODEL_SUFFIX`), imported by the caller.
- `EXHIBIT_FORMS_PREFIX`, `EARNINGS_EXHIBIT_TYPE`, `EXHIBIT_99_RE` and the duplicate
  `EXHIBIT_TYPE_PREFIX` are deleted; one used constant remains.
- `cache.dir` removed; `paths.cache_dir` is the only answer.
- `data.sec_timeout_seconds` replaces borrowing `llm.timeout_seconds`.
- `.gitignore` covers `*.zip` and `*.part`. `tresata.zip` is still tracked — **H-B**.
- `tenacity` removed from `pyproject.toml` and both locks (it was pinned and unused;
  `RetryingCaller` is the retry implementation). Locks regenerated with uv: 58 runtime
  pins, 76 dev pins, no local path.
- `smoke_llm.py` and `measure_truncation.py` log rather than print; `mutation_check.py`
  keeps `print` because its output is a report read by a person.
- **F17 deviations from the Build Pack**, recorded and not changed: argparse rather than
  Typer; a hand-written dataclass config loader rather than OmegaConf; a filesystem cache
  rather than diskcache; raw httpx rather than `langchain-openai`; six themes where B3
  names a different list; `max_doc_chars` 24000 where B3 says 60000; `extract_structured`
  returns `(parsed, raw_text, error)` rather than an `LLMResult`; `aggregate_index`'s
  signature differs from B3. Each needs the human to accept or reject.
- **F18**: the prompt's `"v1"` literal is gone; `schema_version` is a template variable
  from config.

### N7 — the rebuild was run offline, and kept nothing

`nowcast rebuild-index` on `data/document_index.parquet` (100 rows, no `items` column):
0 kept, `{no_earnings_item: 61, non_text: 39}`, report at
`data/manifests/rebuild_index.json`. On `document_index.text_only.parquet` (61 rows):
0 kept, `{no_earnings_item: 61}`. That is the guard working: an index written before the
`items` column cannot prove Item 2.02, so guessing would be the defect. The store was not
destroyed — results and review rows for dropped documents were moved to `superseded/`.
A rebuild that keeps rows requires a fresh ingest, which is blocked on H-A. Recorded
because a zero-kept rebuild is exactly the kind of result a report could quietly omit.

### Not done, and said plainly

F15's `fiscal_period_consistency`; F14's `filings.files` pagination; N7's live rebuild and
the truncation re-measurement on the rebuilt index; every live gate item, blocked on H-A.

## D18 — Pass 3: what changed, and what the live SEC run measured (2026-11-01)

### B2 — a number matches the scale the quote actually prints

`number_in_quote` used to add a candidate for *every* scale word in the quote and always
accepted the raw magnitude, so 1000 against "$1.2 billion" passed: the digits 1000 are not
there, but 1.2 (billion) was, and the check never asked whether 1000 was a reading of the
printed figure. It now reads one scale from the quote (the first scale word present) and
accepts exactly two readings: the printed figure (1.2) and its expansion (1.2e9). A 1000x
or 1e6x error is flagged. `test_scale_mismatch_1000x_flagged`,
`test_missing_scale_word_flagged`, `test_exact_billion_and_million_pass`,
`test_percent_forms`.

### B5 — the packer allocates by priority, and never over the limit

Regions are collected head-first, then by phrase priority (guidance/outlook, per-share,
revenue by default), merged when they overlap, and the budget is then spent in **priority
order**: the survivors are finally written back in document order, so the model still
reads a release. Choosing in document order was the real defect the mutation check found
— it spends the budget on whatever came earliest, which is exactly how tail guidance was
lost. A region that does not fit is trimmed to the room left, and the output is clipped to
the limit as a final guard. A phrase that
appears everywhere ("revenue") cannot starve guidance at the end of the document.
`test_tail_guidance_kept_when_revenue_is_frequent`, `test_never_exceeds_limit_sweep`,
`test_document_order_preserved`, `test_priority_decides_which_window_survives_a_tight_budget`
(which sets priority both ways, so it fails if either the priority ordering or the
document-order fill is wrong). One candidate mutant was dropped rather than faked: with the
output clipped to `limit` at the end, no change to the packing loop's early exit can breach
the limit, so that mutant would have been equivalent — an honest gap in mutation coverage,
not a killed one.

### B6 — a populated index is backed up, then refused

`rebuild-index` now refuses to replace a target that already holds rows unless `--force`,
and with `--force` copies the old file to `<name>.<timestamp>.parquet` beside it first.
The timestamped file is kept, never deleted. `test_rebuild_does_not_wipe_populated_v2`,
`test_rebuild_backs_up_target`.
**Observed live:** `rebuild-index` refused the ingested index; `--force` backed it up
(`document_index.v2.20261101T072228Z.parquet`, 60 rows) and then wrote 0 rows because its
default source is the pre-`items` legacy index. That is the refusal doing its job and the
source default being wrong for this situation — the pre-v2 default should not be used when
the configured index is populated. The backup's contents are preserved in
`data/document_index.v2.from-live-20261101.parquet`; the populated `document_index.v2.parquet`
was replaced by an empty write and **has not been restored in place** (the restore was
blocked by the local-destruction guard). Restoring it is a `cp` of that file, and needs the
human.

### B7 — ingest writes as it goes

Every downloaded row is merged into the index immediately (`on_row`), the cohort is
written before the walk and again in `finally`, and the report and summary are written on
the abort path too. An abort twenty companies in keeps the documents already fetched.
`test_abort_keeps_rows_downloaded_so_far`, `test_cohort_written_on_abort`
(`test_ingest_reports_season_cohort_in_summary`).

### B1 — the cohort is the (company, season) pairs the run targets

`Sample` now carries `pairs`; `season_sample` records which seasons each company was
drawn for. Ingest passes those pairs to `select_filings`, which skips a filing whose season
was not sampled (`season_not_sampled`), so a company's newest three quarters no longer
stand in for the season it was sampled for. `manifests/cohort.csv` is one row per pair, and
aggregation reads the cohort **per season**: a company sampled for 2025Q2 is not counted
as expected in 2025Q3.
**Measured live** (`ingest` against SEC, `subset_n=8`, cap 60):
`new_rows 60, index_rows 60, companies 61, cohort_pairs 64`, skip reasons
`{season_not_sampled: 433, duplicate_season: 3, duplicate_exhibit: 105}`, and all 60
downloaded (cik, season) pairs are in the cohort. Eight seasons covered, 57 distinct CIKs.
`test_cli_ingest_cohort_is_per_season_and_matches_downloads`,
`test_share_reported_uses_sampled_cohort`, `test_no_crash_when_cohorts_differ_per_season`,
`test_cohort_is_per_season`.

### B4 — a field flag withdraws a field, not a company

Queue rows name a field. A blocking reason (`llm_failed`, `truncated`, `document_error`,
`empty_extraction`) on `field='record'` drops the whole (document, model); any other flag
withdraws only that field's contribution to its own metric. The company still counts as
reported, and its other fields still count.
`test_truncated_doc_still_contributes_unflagged_fields`,
`test_flagged_field_excluded_only_from_its_metric`.

### B3 — metrics the documents actually support

`beat_rate` is optional: with no consensus figure anywhere in the season it is NaN with
`metric_status_beat_rate = 'no_consensus'`, not an absent column. `revenue_growth_agg`
(revenue yoy as printed, from the release itself) joins the metric set with its own
observation count. Equity metrics still come from the release; the XBRL history path
(EPS and revenue across periods, with `available_date` = filing date) remains R3 and is
**not** built here. Ingest now targets (company, season) pairs across the whole window
rather than each company's newest filings — the live run above spans eight seasons.

### H-a — request budget, not a dollar budget

`RequestLimiter` enforces requests/minute and requests/day across all threads, and a
provider `Retry-After` sets a cooldown every caller waits out. A per-thread limiter would
multiply a free tier's cap by the number of workers. The runner builds one limiter per run
and passes it to every composed caller. The daily cap raises `BudgetExceeded`, which the
runner already treats as a graceful stop. Cascade: models are tried in order, moving to
the next only on failure or when every non-null core field's confidence is below
`llm.cascade_min_confidence`.
`test_limiter_caps_rpm_across_threads`, `test_global_cooldown_on_retry_after`,
`test_cascade_calls_second_model_only_on_failure`, `test_cascade_escalates_on_failure`.
**Not measured live**: the OpenRouter key is still rejected (H-A of pass 2), so the
cascade's real rate behaviour is UNSURE.

### H-b — a length-cut reply with content is a truncation

`finish_reason == 'length'` now raises `TruncatedCompletion` whether or not content came
back: a JSON object cut mid-key parses as garbage, and a larger budget is the fix. A
provider `finish_reason=stop` with no content is retried once before it is fatal.
`test_partial_json_length_is_truncated`, `test_transient_empty_retried_once`.

### H-c — only current results are consolidated or aggregated

The fingerprint now includes temperature, max_tokens, reasoning and a units-rule version.
Each stored result records its `sha256` and `prompt_digest`, so consolidate recomputes the
fingerprint and moves a mismatch to `superseded/` instead of mixing it in. Results written
before the sha was stored cannot be re-checked and are kept rather than discarded on a
guess. Consolidated rows carry `stale=False`, and aggregation drops any row marked stale.
`test_llm_settings_change_invalidates`, `test_stale_fingerprint_not_consolidated`,
`test_stale_fingerprint_excluded_from_aggregate`.

### H-h — paths follow the config, getters do not create

`Config.config_dir` is the directory of the config file; `Paths.from_config` resolves data
and prompts against it, so a run started elsewhere still finds its prompts.
`Paths.sub` no longer calls `mkdir`; the writers do. The module-level `SKIPPED_RESULTS`
list is gone: `consolidate` and `_load_result` take an optional list and report through it,
so two runs cannot inherit each other's counts. `RetryingCaller.close()` exposes the public
accessor that replaces `_caller.close()` in the CLI and the sample script.
`test_run_from_other_cwd`, `test_getters_do_not_mkdir`, `test_no_module_level_mutable_state`.

### M-a — the SGML envelope is stripped only when it wraps the file

The regex is anchored to the start of the document and matches to the **final** `</TEXT>`,
so an ordinary page containing an inline SVG `<text>` is not truncated at that point.
`test_sgml_strip_only_when_wrapped_at_start`,
`test_sgml_strip_keeps_everything_up_to_the_final_text_close`.

### Not done in this pass, and said plainly

- H-d (`filings.files` pagination), H-e (bakeoff ledger/p50/p95/429/accuracy mode),
  H-f (dedupe priority from the bakeoff), H-g (cache-after-validate, fiscal_year check,
  theme direction vocabulary, prior-year basis): **not implemented**. They are listed in
  `tasks.md` with their order, and none is claimed as done.
- M-b, M-c, M-d, M-e: M-d (docs to measured counts) and M-e (dead code, `_caller`) are
  done; M-b/M-c need the human's decision on tracked files (H-B) and are not done.
- Live extraction, per-field coverage, empty rate, review rate, 429 count: **blocked** on
  the OpenRouter key.


## D19 — 2026-11-02: whole-document extraction, one call per document (human instruction)

Two instructions from the human, and what each needed in code rather than in flags:

1. **"Don't split the text and send."** `extraction.pack_phrases` now decides: with an
   empty list the runner sends the converted document whole; with phrases listed it packs.
   Simply setting `max_doc_chars` high would not have done it — the old path always cut at
   the limit, so "packing off" still silently split.
2. **"One doc needs only one extraction/llm call if it passes without errors."**
   `extraction.max_repairs` is now 0: a parse failure escalates in the cascade instead of
   re-prompting the same model. Results are keyed `<document_id>.<season>.json` and carry
   `season_sampled`, so a run with a different cohort cannot resume another run's records
   and count that as done.

**`pack_phrases` had to enter the fingerprint.** Without it, turning packing off would
have resumed the old packed records — a run that looked successful while the model had
never seen the full text. This is the same class of bug as the missing few-shot hash in
D16.

### What the live run then measured, and the correction to my own first report

60 documents, 57 companies, 8 seasons: 60 ok, 0 failed, 0 × 429, 1 empty extraction,
0 truncated, 38/60 flagged for review.

**I first reported the 102 model calls as "60 + 42 escalations". That was wrong.** The log
contains zero `cascade:` lines and every consolidated record is from the first model; the
other 42 calls were truncation retries — the reply was cut at `max_tokens=16384` and
retried once at double. So the one-call rule is **not yet demonstrated**: 42 of 60
documents needed a second call because the answer was too long for the budget, which is a
real finding for the bakeoff (a bigger reply budget is cheaper than a retry).

### The run is not a clean pass

31 of 60 documents carry a number absent from the text their quote matched, and 31 have a
quote not found in the source. No threshold was changed. The next step is reading several
flagged records against their source to decide whether the model paraphrases or the fuzzy
match lands on the wrong window in a long uncut document — with the text now sent whole,
both are plausible and neither is proven.

### Corrected doc lag

The docs were last written at 13:31 on 2026-11-01, before the live runs and the final code
edits. They now carry the measured numbers above, the 338-test gate, 104 formatted files
and the corrected call-count interpretation.
