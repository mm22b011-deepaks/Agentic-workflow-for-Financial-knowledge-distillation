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
