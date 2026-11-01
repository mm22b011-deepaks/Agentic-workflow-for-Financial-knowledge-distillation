# tasks.md — index-earnings-nowcast task board

Status legend: `[x]` done · `[~]` in progress · `[ ]` todo · `[!]` blocked on a decision

Last gate run: `ruff check . && ruff format --check . && mypy src && pytest -q` →
`ruff` clean, **100 files formatted**, `mypy` clean on **46 source files**,
**336 tests passing** (2026-11-01, after pass 3: B1–B7, H-a/H-b/H-c/H-h, M-a).
`evidence/phase_R0.txt` maps each item to its test.

## Pass 3 (2026-11-01) — item status

| Item | Status | Evidence |
|------|--------|----------|
| B1 cohort | FIXED | per-(company, season) pairs; live ingest: 64 pairs, 60 downloads all in cohort, 8 seasons |
| B2 number_in_quote | FIXED | one scale reading; 1000x and 1e6x flagged |
| B3 redesign | PARTIAL | beat_rate optional (`no_consensus`), revenue growth added; XBRL path stays R3 |
| B4 aggregate exclusion | FIXED | blocking reasons drop the row, field flags drop one metric |
| B5 packer | FIXED | priority budget, document order, limit never exceeded |
| B6 rebuild | FIXED | refuses populated target, backs up with timestamp; live refusal observed |
| B7 incremental ingest | FIXED | rows persisted per document, cohort/report in `finally` |
| H-a limiter/cascade | FIXED offline, UNSURE live | shared rpm/day limit + cooldown + cascade; no live call yet |
| H-b length truncation | FIXED | content + `finish_reason=length` is truncated; transient empty retried once |
| H-c stale results | FIXED | settings in fingerprint; stale moved to `superseded/`, excluded from aggregates |
| H-d pagination | NOT DONE | needs a live high-volume CIK; template is in config |
| H-e bakeoff rework | NOT DONE | ledger/p50/p95/429/accuracy mode |
| H-f dedupe priority | NOT DONE | still self-confidence; needs the bakeoff ranking |
| H-g validation extras | NOT DONE | cache-after-validate, fiscal_year check, theme directions, prior-year basis |
| H-h paths | FIXED | config-dir anchoring, no mkdir in getters, no module globals, public `close()` |
| M-a SGML strip | FIXED | anchored to file start, final `</TEXT>` |
| M-b/M-c | BLOCKED on your decision | tracked `inputs/constituents.csv` and `tresata.zip` |
| M-d/M-e | FIXED | docs to measured counts; dead code and `_caller` removed |

Step 4 of the order was run: a live SEC ingest (order item 4) and the rebuild refusal.
Steps 5–6's live items remain blocked on the OpenRouter key. H-d, H-e, H-f, H-g were not
reached; they are next, in that order, and are not claimed as done.

## Reviewer pass 2 (2026-11-01) — item status

| Item | Status | What was measured / why it stays open |
|------|--------|----------------------------------------|
| F2 key provenance | `[x]` | smoke test reports source, length, sha256 prefix and warns on shadowing. Live: an exported 31-char value shadows `.env`. |
| F12 auth fail-fast | `[x]` | 401/403 → `AuthError`, 400/404 → `ModelNotFound`, never retried; run aborts. |
| N1 one cache | `[x]` | side cache deleted; cache key includes reasoning params. |
| N2 budget/ledger/reasoning | `[x]` offline, `[!]` live | per-call budget, `EmptyCompletion`, ledgered failures, capability probe, `model-bakeoff` implemented + tested offline. Live probe blocked (H-A). |
| F9 stratified sample | `[x]` | `--sample N --seed S`; deterministic, one per company first. |
| N3 `eps_missing` | `[x]` | separate reason from `empty_extraction`. Live coverage rerun `[!]` H-A. |
| F7 number in source | `[x]` | matched-window check; mutated digit flagged. |
| F10 vocabularies | `[x]` | config-driven prompt + validator + aggregator; `mixed` scored 0.0. |
| F11 confidence coverage | `[x]` | text fields and themes queued; `doc_truncated` queued. |
| H5 interim packer | `[x]` offline | head + phrase windows, omission markers; live re-measure `[!]` H-A. |
| F6 queue semantics | `[x]` | replace per (document, model), superseded archive, per-pair exclusion, company counts. |
| F5 dedupe confidence | `[x]` | `record_confidence` written by consolidate; missing column raises. |
| F1 cohort share | `[x]` | `share_of_cohort`/`share_of_index`, cohort.csv, `cohort_too_small` log. |
| F3 per-metric minimums | `[x]` | `n_obs_*` and `metric_status_*` columns. |
| F4 as-of winsorise | `[x]` | clip inside each snapshot; later documents cannot change earlier rows. |
| F15 season decision | `[x]` decision, `[ ]` diagnostic | filing-quarter season kept (D17); `fiscal_period_consistency` deferred to R4. |
| F8 gzip length | `[x]` | byte count + encoding-aware skip; live gzip unverified. |
| F14 ingest correctness | `[~]` | window errors abort, `cik_failed:<status>` counted, no `date.today()`; `filings.files` pagination **not implemented** (needs live CIK). |
| H1 crash safety | `[x]` | corrupt/short result files skipped and counted. |
| F16 pipeline wiring | `[x]` | `aggregate` command with guardrail before write; `run-all` stops at first failure. |
| M1/M4/H3/F17–F19 | `[x]` | referer URL, one `:free` constant, dead constants removed, `cache.dir` removed, SEC timeout, `.gitignore` zips/parts, tenacity removed, locks regenerated, deviations recorded in D17. `tresata.zip` still tracked → **H-B**. |

Live gate items stay `[!]` on **H-A**: 10+ real releases with `--sample`, per-field
coverage, bakeoff table, rebuilt index counts, `measure_truncation` on the rebuilt index,
5 human-read records.

---

# PART 1 — The R-amendment (governing spec from 2026-10-31 onward)

The **Course Correction + Optimization Amendment** supersedes the earlier E1–E5 phase
plan. It amends the frozen Build Pack. Every deviation from it is logged in
`DECISIONS.md` and flagged in chat. Phases run in order; a phase does not start until
the previous gate is GREEN.

## Amendment goals (verbatim intent, tracked as G1–G6)

| ID | Goal | Status |
|----|------|--------|
| G1 | Lossless hierarchy: document → company_period → sector_period → index_period. No summary overwrites a leaf; every upper number traces to leaf facts. | `[ ]` R4 |
| G2 | Numbers aggregated by SQL/pandas in code, **never** by an LLM. LLMs only read one document, and write cited narrative from stored evidence. | `[~]` holds so far |
| G3 | Every LLM call through one context packer: token budget, edge-aware ordering, empirically measured. | `[ ]` R2 |
| G4 | SQLite (single file, WAL) is the system of record. Parquet/CSV are exports only. | `[ ]` R1 |
| G5 | Standard tools only: LangChain, SQLAlchemy 2.0, Alembic, pydantic v2, tenacity, scikit-learn, pytest, hypothesis. Do not reinvent. | `[~]` deps partly installed |
| G6 | Faster and cheaper, and **measured**. Never claim a speedup not benchmarked. | `[ ]` R6 |

## Amendment config additions

Appended to `configs/config.yaml`; `config.py` mirrors and validates each. **No other
new keys.** Existing keys keep their meaning.

```yaml
db:          {path: db/nowcast.sqlite, busy_timeout_ms: 10000, synchronous: NORMAL, batch_size: 200, backup_dir: ''}
hierarchy:   {sector_map_csv: '', sector_key_source: sic, min_constituents: 10}
reporting:   {max_detail_level: index}          # index | sector | company; default index
context:     {target_tokens: 32000, hard_max_tokens: 128000, reserve_output_tokens: 2000,
              chars_per_token: 4.0, repeat_instructions_at_end: true, calibrate_from_usage: true}
extraction:  {section_select_enabled: true, section_top_k: 6, tasks: [guidance, tone_themes]}
xbrl:        {companyfacts_url_template: '', concepts_csv: ''}   # concept names in CSV only
cascade:     {escalate_below_confidence: 0.5}
narrative:   {enabled: false, max_quotes_per_node: 40, max_clusters: 8, require_citations: true}
needle:      {context_lengths: [8000, 32000, 128000], positions: [0.0, 0.25, 0.5, 0.75, 1.0], trials_per_cell: 5}
```

Two structural changes to existing keys:

- `llm.models` entries become mappings `{id, context_tokens}`. The packer uses
  `min(configured context_tokens, context.hard_max_tokens)`.
- New CLI command **`probe-models`** reads each model's `context_length` from the
  provider's models list and writes it to config. Context length is **never hard coded**.

## Amendment absolute don'ts (enforced by grep/test where possible)

- Never ask an LLM to sum, average, compare or compute any number.
- Never replace or delete leaf facts with summaries.
- Never send more than `context.target_tokens`; never fill the 1M window.
- Never hard code a sector map, ticker, URL, concept name, or model context length.
- Never expose company/sector identifiers unless `reporting.max_detail_level` allows
  it, and never without the NDA owner's confirmation.
- Never claim a test, benchmark or recall number that was not run and seen.
- Free OpenRouter models only (`:free`); a paid model ID anywhere is a defect.

---

## R0 — Triage (nothing new on a broken base) `[~]`

- [x] **Defect register supplied.** On 2026-10-31 the human supplied the R0 register
      (N1–N7, H1–H5, M1–M4); Q1 confirmed that register **is** `DEFECTS.md`, replacing
      the provisional stub. Item-by-item status and measurements live there; this file
      tracks the remaining live gates rather than duplicating the register.
- [!] **H1 schema decision** — needs a `DECISIONS.md` entry.
      Default recorded: restore `prior_year_eps`, `consensus_eps`, `tone`,
      `guidance_metric`; the LLM reads only what the text states; EPS and revenue come
      from XBRL in R3.
      *Current state:* all four fields are already present in
      `extraction/schema.py`, so this part of H1 is satisfied; the XBRL half lands in R3.
- [ ] **H2 universe decision** — default to record in `DECISIONS.md`: keep the Phase 2B
      Wikipedia-changes builder (637 intervals, 635 companies, CIK coverage 0.991); the
      74 unmapped delisted tickers stay unmapped and are reported, not back-filled.
- [ ] **H3 reproducibility/portability decision** — default to record: `DATA_DIR` wins
      over YAML; all stored paths relative to `DATA_DIR`; manifest carries config hash,
      git sha, package versions, prompt hashes, seed.
- [x] Gate R0 offline half: ruff + mypy + pytest green (303 tests); mutation check
      33/33 killed, 0 survived; Phase 0 files exist;
      `test_validators` + `test_review_queue` pass (18 + 7 tests, measured 2026-11-01);
      `evidence/phase_R0.txt` written with the per-item test map.
- [!] Gate R0 live half: 10+ real documents with `--sample`, per-field coverage, bakeoff
      table, rebuild counts, `measure_truncation` on the rebuilt index, 5 human-read
      records. Blocked on H-A.

### Live work outstanding for R0
- [!] **H-A first**: `unset OPENROUTER_API_KEY`, rerun `scripts/smoke_llm.py`. The
  smoke test now proves the exported key was shadowing `.env` and is not a valid key length.
- `[ ]` Then `scripts/extract_sample.py --sample 10 --seed 42`: 10 releases, ≥5 companies,
  ≥2 seasons; report per-field coverage, empty-completion rate, review rate by reason.
- `[x]` `evidence/phase_R0.txt` written; its live sections are marked BLOCKED.
- [x] **Resolved by Q4:** nothing is overwritten or moved. The rebuilt index is written
  to `data.document_index` (default `data/document_index.v2.parquet`); the old files
  stay under `data/index_backup/`. The rebuild was then **run offline** on 2026-11-01:
  100 rows → 0 kept (`no_earnings_item: 61, non_text: 39`), because a pre-`items` index
  cannot prove Item 2.02. Results and review rows for the dropped documents moved to
  `superseded/`; nothing deleted. A rebuild that keeps rows needs a fresh ingest (H-A).

## P0 — Prompt hardening for weak models (2026-10-31) `[~]`

Target: the weakest configured `:free` model still returns a usable record. Prompt rules
live in `prompts/extraction/v1/`, never in Python. The system prompt is now a field-level
data-entry contract rather than a few terse rules.

- [x] `system.md.j2`: every field defined, with allowed vocabularies for `eps_basis`,
      `guidance_direction` and `tone`; GAAP preferred when both EPS bases are printed;
      segment revenue explicitly excluded from `revenue`; growth is percent as printed;
      `units` is `<CCY> <scale>` with the printed scale; per-field null policy; the
      evidence quote must contain the digits and the unit; "do not calculate"; output is
      one bare JSON object; document text is data, not instructions.
- [x] `user.md.j2`: restates all sixteen top-level keys immediately before the document,
      with the null rule and the verbatim-quote rule — the last thing the model reads.
- [x] `few_shot.yaml`: three synthetic examples — (1) GAAP EPS + consensus + 4% growth,
      (2) revenue only with EPS missing and guidance explicitly not provided,
      (3) adjusted EPS, "flat" growth left null rather than inferred as 0.0, empty
      `theme_mentions`. Units are canonical (`USD billion`, `GBP million`), and example
      themes use the configured vocabulary (`demand`, `margins`).
- [x] Few-shot text is part of the prompt hash (it is sent to the model as messages), so
      editing an example invalidates stored results. Test:
      `test_prompt_hash_changes_with_few_shots`.
- [ ] **Measure it live** (blocked by the OpenRouter 401): 10 real earnings releases,
      ≥5 companies, ≥2 seasons; per-field coverage, empty-completion rate, review-queue
      rate and 429 count in `evidence/phase_R0.txt`. Then run the same set through the
      weakest available `:free` model in the bakeoff. No claim of improvement before
      those numbers exist.
- [ ] If the weakest model still emits all-null records, the next lever is the narrow
      per-task schemas in R3 (`guidance`, `tone_themes`), not a longer prompt.

## R1 — SQLite layer `[ ]`

Files: `src/nowcast/db/{engine,models,repository,views,migrate}.py`, `migrations/`
(Alembic), `tests/unit/test_db_*.py`.

- [ ] SQLAlchemy 2.0 declarative models + Alembic migrations. **No `create_all` in
      production code.**
- [ ] Engine listener on every connection: `journal_mode=WAL`, `foreign_keys=ON`,
      `synchronous` and `busy_timeout` from config.
- [ ] DB path resolves under `DATA_DIR`; no absolute paths stored in rows.
- [ ] Tables (exact list): `runs`, `companies`, `index_membership`, `documents`,
      `sections`, `extractions`, `facts`, `review_queue`, `llm_cache`, `llm_calls`,
      `nodes`, `node_edges`, `node_facts`, `node_metrics`, `node_narratives`,
      `needle_results`, `benchmarks`.
- [ ] Indexes: `documents(cik, report_date)`, `facts(extraction_id, field)`,
      `nodes(level, fiscal_year, fiscal_quarter)`, `node_metrics(metric)`.
- [ ] Repository pattern: all writes through one `Repository`, batched transactions,
      **never** a transaction held open across an LLM call, idempotent UPSERT on natural
      keys and fingerprints.
- [ ] Views: `v_index_period_metrics` exposes no cik, ticker, company name or sector;
      `v_sector_period_metrics` exists but only used when `reporting.max_detail_level`
      allows it.
- [ ] Importer: existing extraction JSON/parquet → DB, idempotently.
- [ ] `db-backup` command via the sqlite3 backup API. Colab: live DB on local runtime
      disk, backups copied to Drive (SQLite on Drive can corrupt or lock) — document in
      the README.
- [ ] Tests: `test_pragmas_applied`, `test_migration_from_empty_to_head`,
      `test_upsert_is_idempotent`, `test_fk_enforced`,
      `test_view_has_no_identifier_columns`, `test_two_writers_no_lost_updates`,
      `test_db_file_copy_is_portable`, `test_no_absolute_paths_in_rows`,
      `test_importer_idempotent`.
- [ ] **Gate R1:** all green plus `PRAGMA integrity_check` ok.

## R2 — Context packer + lost-in-the-middle measurement `[ ]`

Files: `src/nowcast/context/{budget,packer,needle}.py`, `scripts/needle_sweep.py`, tests.

- [ ] `budget.py`: estimate = `chars / context.chars_per_token`, calibrated from
      provider-reported usage in `llm_calls` (median ratio) when
      `calibrate_from_usage`. Always conservative.
- [ ] `packer.py`: `pack(instructions, evidence_items[Evidence(id, text, score)], question,
      budget) -> PackedPrompt(messages, token_estimate, included_ids, dropped_ids)`.
      Rules: (1) `available = min(target_tokens, model window) - reserve_output - instr -
      question`, instructions counted twice when `repeat_instructions_at_end`;
      (2) take by score until `available` is used, log dropped ids; (3) **edge ordering**
      for independent evidence — best first, second best last, alternate inward;
      (4) **one contiguous document** — never reorder, select top sections, mark gaps
      `[... omitted ...]`; (5) layout: system+schema → numbered `[E1]..` evidence →
      restated task+schema reminder → question last; (6) every output cites evidence
      ids, validated in code.
- [ ] `needle.py` + `scripts/needle_sweep.py`: locally generated finance-style filler
      (no real or copyrighted text), known random fact planted at each configured
      length × position, retrieval scored into `needle_results`. **Live test, not CI.**
- [ ] Tests: `test_pack_never_exceeds_budget` (hypothesis),
      `test_edge_ordering_best_first_second_best_last`,
      `test_instructions_at_both_edges`, `test_dropped_ids_reported`,
      `test_contiguous_doc_keeps_order_and_marks_omissions`,
      `test_token_calibration_uses_provider_usage`,
      `test_needle_builder_places_fact_at_requested_fraction`.
- [ ] **Gate R2:** unit tests green; needle sweep run on each configured model; recall
      table shown; `context.target_tokens` set to the largest length whose
      **middle-position** recall is within an agreed margin of edge recall; numbers and
      choice logged in `DECISIONS.md`. Do not guess it.

## R3 — Structure-first extraction `[ ]`

- [ ] EPS and revenue from SEC XBRL company facts (URL template + concept names from
      config). `source_kind=xbrl`, `available_date = filing date` — this is the leakage
      control.
- [ ] Q4 is in no 10-Q: skip, or derive with an explicit derived flag — **never
      silently**.
- [ ] Narrow LLM tasks, one schema per call: `guidance` (direction, metric, quote),
      `tone_themes` (tone, theme mentions with quotes), plus `consensus_eps` /
      `prior_year_eps` only when the text states them.
- [ ] Section selection (`section_top_k`) around outlook/guidance/commentary terms, then
      the R2 packer.
- [ ] Cascade: first free model → if confidence `< cascade.escalate_below_confidence` or
      validation fails, next configured free model → else review queue. Every attempt in
      `llm_calls`.
- [ ] Verify every quote in code (fuzzy); scale-aware number match; cross-check LLM
      numbers against XBRL, mismatch → `source_conflict` in review queue.
- [ ] Tests: `test_xbrl_available_date_is_filing_date`, `test_q4_not_silently_derived`,
      `test_narrow_schema_roundtrip`, `test_cascade_escalates_then_queues`,
      `test_scale_aware_number_match`, `test_llm_vs_xbrl_conflict_queued`,
      `test_no_llm_call_when_xbrl_covers_numbers`.
- [ ] **Gate R3:** green, then 10 real documents end to end; human spot-checks 5 facts.
- [ ] If any XBRL endpoint or field name is uncertain: write `UNSURE` and ask; verify
      against one live response first.

## R4 — Hierarchy build (SQL, deterministic) `[ ]`

- [ ] Nodes + `node_edges` for document → company_period → sector_period → index_period.
- [ ] Sector key from `hierarchy.sector_map_csv` (SIC → sector). Never hard code a map.
      No-sector companies → key `unmapped`, reported in the build report.
- [ ] `company_period`: reconcile 8-K release, 10-Q and XBRL for the same cik+period by
      a source-priority list from config. Disagreement beyond `eps_tolerance_abs` sets
      both facts aside, queues `source_conflict`, flags the node. **Never average
      conflicting sources.**
- [ ] `sector_period`, `index_period` via SQL `INSERT ... SELECT` into `node_metrics`:
      n_inputs, n_expected (point-in-time), share_reported, beat_rate, eps_growth_agg
      (winsorized), guidance shares and ratio, tone_score_mean, theme shares.
      `as_of_date` snapshots use only facts with `available_date <= as_of_date`.
      Suppress when `n_inputs < hierarchy.min_constituents`.
- [ ] Lineage intact: any metric traces through `node_facts`/`node_edges` to leaf facts.
- [ ] Tests: `test_count_conservation`, `test_no_orphan_nodes`,
      `test_every_metric_traces_to_leaf_facts`, `test_asof_excludes_future_facts`,
      `test_sql_matches_independent_pandas_recompute`, `test_rebuild_is_idempotent`,
      `test_suppression_below_min`, `test_conflicting_sources_not_averaged`, hypothesis
      `test_order_invariance`.
- [ ] **Gate R4:** green, and index-level output contains no identifiers.

## R5 — Narrative rollups (optional, RAPTOR-style) `[ ]`

Behind `narrative.enabled` (default false). Qualitative text only.

- [ ] Gather ≤ `max_quotes_per_node` verified quotes → TF-IDF + agglomerative clustering
      (scikit-learn, ≤ `max_clusters`) → summarize each cluster via the packer →
      summarize summaries upward.
- [ ] Every sentence cites fact ids; verified in code (cited ids exist; every number in
      the summary appears in a cited quote). Unverified → `verified=false`, never shown.
- [ ] Narratives never feed `node_metrics`, never replace facts.
- [ ] Tests: `test_every_sentence_has_citation`, `test_unverified_narrative_hidden`,
      `test_narrative_never_changes_metrics`, `test_cluster_count_capped`.

## R6 — Optimize and benchmark `[ ]`

- [ ] LLM calls through LangChain `ChatOpenAI` (base_url from config) with rate limiter,
      `.with_retry` (exponential backoff + jitter, honour `Retry-After`),
      `.with_fallbacks`, `abatch(max_concurrency)`. Usage callbacks write `llm_calls`.
      If the custom httpx caller is kept behind `CallerLike` it must meet the same
      behaviour, and the decision is logged.
- [ ] Cache in `llm_cache`, keyed by (model, prompt_hash, input_hash, params_hash with
      temperature, max_tokens, schema_version). Never cache unparseable output.
      Strip ` thinking` blocks before parsing; loose JSON parser as fallback.
- [ ] Stable prefix first (system, schema, few-shot), document text last, so provider
      prompt caching can help where supported — do not assume free models do.
- [ ] Skip the LLM when XBRL covers the field. One HTTP client per run, closed in
      `finally`.
- [ ] `benchmark` command writes `benchmarks`: tokens in/out p50/p95 per task, latency,
      cache-hit rate, 429 rate, cost per document, documents per minute.
      **BASELINE before optimizations, second run after, report real deltas only.**
- [ ] Tests: `test_retry_honors_retry_after`, `test_cache_key_includes_params`,
      `test_unparseable_not_cached`, `test_think_block_stripped`,
      `test_one_client_per_run_closed`,
      `test_budget_exceeded_stops_gracefully_and_keeps_results`.

## R7 — Trace and reporting from views `[ ]`

- [ ] CLI `trace <node|metric>` prints lineage down to evidence quotes;
      `explain-metric` shows inputs, exclusions and conflicts.
- [ ] Report layer reads **only** the views allowed by `reporting.max_detail_level`
      (default `index`). No `companies` table access below that level.
- [ ] Tests: `test_trace_reaches_quotes`, `test_report_reads_only_allowed_views`,
      `test_default_report_has_no_cik_ticker_sector`.

## R8 — Hardening `[ ]`

- [ ] Tests: `test_resume_after_kill_mid_run`, `test_reproducible_run_same_metrics`,
      `test_concurrent_extract_workers_safe`, `test_migration_upgrade_path`,
      `test_db_integrity_check`.
- [ ] **Gate R8:** real run on ~10 documents with the benchmark and needle tables in the
      report.

---

# PART 1B — Amendment Q: data quality and nuance output (2026-10-31)

Amends the FROZEN SPEC **and** the R-phases. Deviations are logged in `DECISIONS.md`
(see D8–D11) and flagged in chat. Free models only. Runs alongside the R-phases: Q's
taxonomy and schemas are built in R0/R1/R3, its storage lands with the R1 tables, its
hierarchy handling extends R4, and its JSON writers land with R7.

## Q principle (verbatim intent)

**No number is ever silently missing, silently excluded, or silently non-comparable.**
Every gap, event and exclusion is a structured, schema-validated JSON record with a code
from a versioned taxonomy, an explanation, and evidence. **The LLM reports only what the
document states; the code reports everything else.**

## Q config additions — no other new keys

```yaml
quality: {taxonomy_path: configs/quality_taxonomy.yaml, event_policy: exclude_from_growth,
          max_notes_per_doc: 25, max_note_chars: 300}
outputs: {json_dir: outputs/json, schema_dir: schemas, write_internal_company_notes: true}
extraction.tasks gains a third task: data_quality   # its OWN narrow call, own small schema
```

`quality.event_policy` ∈ `exclude_from_growth` (default) | `include_flagged` |
`exclude_entirely`.

## Q-PART 1 — Taxonomy file `[ ]`

`configs/quality_taxonomy.yaml`. **Codes live here, never in Python**; unknown codes are
rejected at validation. Each entry carries a code, a one-line definition and a severity.

- [ ] `field_status`: `present, not_stated, ambiguous, not_applicable, not_comparable,
      restated, derived`
- [ ] `reason_codes`: `merger_or_acquisition, divestiture, spin_off,
      split_into_multiple_entities, discontinued_operations, restatement,
      fiscal_year_change, extra_or_short_period, reporting_currency_change,
      accounting_standard_change, share_split_or_consolidation, segment_reclassification,
      non_gaap_definition_change, one_time_item, guidance_withdrawn,
      guidance_not_numeric, metric_not_reported, partial_period, pro_forma_only, other`
- [ ] `pipeline_codes`: `llm_failed, parse_failed, quote_not_found,
      number_not_in_quote, source_conflict, xbrl_missing, period_mismatch, doc_truncated,
      section_not_found, below_min_constituents, partial_coverage, perimeter_changed,
      missing_prior_year, missing_consensus, excluded_by_event_policy, low_confidence`
- [ ] `node_metric_status`: `ok, partial, suppressed, not_comparable, unavailable`

## Q-PART 2 — Extraction schema addition `[ ]`

New narrow task `data_quality`; Pydantic v2; `schema_version` bumped and recorded.

- [ ] `FieldNote(field, status, reason_code, explanation, evidence_quote, confidence)` —
      `field` must be a known schema field; `explanation` ≤ `quality.max_note_chars`;
      `evidence_quote` required unless status is `not_stated`.
- [ ] `CorporateEvent(type, description, effective_date, period_affected,
      affected_fields, comparability_impact, evidence_quote, confidence)` — quote
      **REQUIRED**; `comparability_impact` ∈ `none | prior_period_restated |
      perimeter_changed | not_comparable`.
- [ ] `DataQuality(events, field_notes, document_notes, extraction_warnings)`.
- [ ] Prompt rules live in `prompts/`, never in Python:
      1. report an event **only** if the document explicitly describes it — never infer a
         merger, spin-off, split or restatement;
      2. `not_stated` ≠ `not_applicable` ≠ `not_comparable`, each strictly its own case;
      3. every event needs a verbatim quote, verified in code; a not-found quote is kept,
         marked unverified and queued;
      4. cap notes at `max_notes_per_doc`, else add warning `notes_truncated`;
      5. output only the JSON object.
- [ ] Synthetic few-shot examples (invented company and figures): one with a spin-off and
      a restated prior-year figure; one where the document is silent.

## Q-PART 3 — Code-generated diagnostics `[ ]` (no LLM, deterministic)

- [ ] Per document, stored with the extraction: `document_id, chars_total, chars_sent,
      tokens_est_sent, truncated, sections_included, sections_missing, models_tried,
      repair_attempts, cache_hit, validation_issues[{field, pipeline_code, detail}],
      xbrl_checked, xbrl_conflicts, field_coverage{field: status}, review_reasons`.
- [ ] Rule: whenever `chars_sent < chars_total`, set `truncated` **and** add
      `doc_truncated` to every field that could have lived in the cut part.

## Q-PART 4 — Storage (Alembic migration on top of R1) `[ ]`

- [ ] New tables: `field_notes`, `corporate_events`, `doc_diagnostics`, `node_notes`.
- [ ] New columns: `node_metrics.status` (`node_metric_status`),
      `node_metrics.status_reason`.
- [ ] View `v_index_notes`: code, severity, message TEMPLATE, affected_metric, counts
      only — no cik, ticker, company name or sector.

## Q-PART 5 — Hierarchy handling of events (extends R4) `[ ]`

- [ ] `company_period` joins `corporate_events` and applies `quality.event_policy`:
      `exclude_from_growth` drops growth inputs when `comparability_impact != none` but
      **still counts the company as reported**; `exclude_entirely` drops it;
      `include_flagged` keeps and flags it. Every action becomes a `node_notes` row with
      `excluded_by_event_policy` or `perimeter_changed` plus the count affected.
- [ ] Roll counts up to sector and index. Index note is counts only, e.g.
      "3 of 48 companies excluded from eps_growth_agg: perimeter_changed (2),
      restatement (1)" — **no names**.
- [ ] Every metric gets a status: `ok | partial | suppressed | not_comparable |
      unavailable`. **A metric is never NaN without a `status_reason`.**
- [ ] Conservation test: `n_inputs + excluded == n_expected - not_yet_reported`.

## Q-PART 6 — Output files (JSON, schema-validated before writing) `[ ]`

JSON Schemas generated from the Pydantic models into `schemas/` (versioned, committed).
A schema failure is a defect.

1. [ ] `outputs/json/documents/<document_id>.json` — **INTERNAL**: record,
       data_quality, diagnostics, source_hashes, models_used, prompt_hashes,
       schema_version, taxonomy_version.
2. [ ] `outputs/json/index/<index>_<fy>Q<q>_asof_<date>.json` — **SAFE TO SHARE**:
       schema_version, taxonomy_version, as_of_date, fiscal_period, metrics[{name, value,
       status, status_reason, n_inputs, n_expected, share_reported, method}], coverage,
       notes, exclusions_summary, `lineage_ref` (a node_id only), run_id, config_hash.
       **No cik, ticker, company or sector fields anywhere**; `assert_index_level_only`
       runs in this writer.
3. [ ] `outputs/json/run/<run_id>_data_quality_report.json` — counts by field_status, by
       reason_code, by pipeline_code; field × document coverage matrix as counts; top
       recurring problems; truncated count; models tried; suppressed metrics and why.
4. [ ] `outputs/json/internal/company_notes_<run_id>.json` — **INTERNAL**, only when
       `outputs.write_internal_company_notes`; corporate events and field notes per
       company for human review.
- [ ] The reporting layer reads **file 2 and the views only**. Files 1 and 4 never enter
      a report.

## Q-PART 7 — Tests (exact names; network mocked; FakeCaller only) `[ ]`

- [ ] `test_taxonomy_loads_and_rejects_unknown_code`
- [ ] `test_not_stated_vs_not_applicable_vs_not_comparable_roundtrip`
- [ ] `test_event_requires_evidence_quote`
- [ ] `test_event_quote_not_found_marks_unverified_and_queues`
- [ ] `test_event_not_invented`
- [ ] `test_notes_capped_adds_warning`
- [ ] `test_truncation_sets_doc_truncated_on_affected_fields`
- [ ] `test_event_policy_exclude_from_growth_keeps_company_counted_as_reported`
- [ ] `test_metric_never_nan_without_status_reason`
- [ ] `test_count_conservation_with_exclusions`
- [ ] `test_index_json_has_no_identifiers`
- [ ] `test_every_output_json_validates_against_schema`
- [ ] `test_schema_files_match_models`
- [ ] `test_internal_notes_not_read_by_report_layer`
- [ ] `test_data_quality_report_counts_match_db`
- [ ] `test_migration_adds_tables_and_columns`

## Gate Q `[ ]`

All tests green. Then **10 real documents**, showing real output: one
`documents/<id>.json`, the index JSON, and the data-quality report; include a document
where a value is `not_stated` and explain what the file says. If none of the 10 contains
a merger, spin-off or restatement, **say so** and build the event path from a fixture —
never claim it works on real data not seen.

## Q "DO NOT" list

- Never let the LLM invent an event, or fill an explanation without an evidence quote
  (except status `not_stated`).
- Never leave a missing, null or NaN value without a status and reason code.
- Never put company, ticker, CIK or sector identifiers into `outputs/json/index` or
  `reports`.
- Never hard code taxonomy codes in Python; read them from the taxonomy file.

---

# PART 2 — Completed work (historical record, before the amendment)

## A. Repair queue A1–A15 `[x]`
All fifteen closed, each with a regression test where the fix is behavioural:
EDGAR Item 2.02 + EX-99 by `<TYPE>`; `cache_dir(config)` crash; `BudgetExceeded`
re-raised; scale-aware `number_in_quote`; B4 schema fields; Phase 2B universe builder;
configured ingest window; relative `raw_path`; cache key with temperature/max_tokens;
`Retry-After`; lock-guarded ledger; `consolidate` writes `extractions.parquet`;
`think`/`thinking`/`reasoning` stripping incl. unclosed; unknown key → `ConfigError`
(exit 2); `.gitignore`/`.env.example`/`.env` mode 600.

## B. Phase 0 files `[x]`
`paths.py` (single implementation, `config.py` re-exports), `manifest.py`
(config hash, git sha, package versions, prompt hashes, input fingerprints, secret
redaction), `logging_setup.py` (named handlers, no double logging), full CLI with
`--config` / repeated `--set` / `--strict`, README, CHANGELOG, pre-commit, CI workflow,
`requirements.lock.txt`, `notebooks/00_colab_bootstrap.ipynb` (21 cells, no outputs).

## C. Extraction pipeline `[x]`
Schema, validators, review queue, resumable runner, and the **C2 integration test**
(3 fixture docs through parse → extract → consolidate, including resume-makes-no-calls
and unparseable-reply-queues). Two real defects found and fixed: non-text EX-99 scans
downloaded as HTML, and non-text files loaded from an existing index.

## D. Phase 2B universe `[x]` mechanically, `[~]` gate
Live build: **637 intervals, 635 companies, CIK coverage 0.991, 292 anomalies, 74
unmapped**. Member-count audit (8 quarters): 493, 493, 493, 495, 498, 498, 501, 504 —
none flagged.
- [~] Gate 2B items 4–5 are human judgement: review `data/universe/unmapped.csv`
      (74 delisted tickers) and spot-check 10 intervals against a second source.

## E. Aggregation (pre-amendment Phase 4) `[~]`
`src/nowcast/aggregation/aggregate.py` + 19 tests. Superseded by R4, which moves the
same metrics into SQL over `node_metrics`; the pandas implementation stays as the
independent recompute that `test_sql_matches_independent_pandas_recompute` compares
against.
Found and fixed: a surprise exactly at `eps_tolerance_abs` was graded a beat because
`1.0 + 0.05 - 1.0` is `0.050000000000000044`; the comparison now rounds to
`SURPRISE_DECIMALS = 10` first.

---

# Open decisions and blockers

1. **OpenRouter returns 401 `User not found`** for the configured key, re-confirmed by
   `scripts/smoke_llm.py` on both configured models. Every live gate (N2 probe/bakeoff,
   N3 rerun, N6 CIK check, N7 rebuild, Gate R0, P0 measurement) is blocked on a valid
   key. Credential inspection is off-limits, so the fix is a rotated/key supplied by the
   human, not a code change.
2. **Index rebuild** — resolved design (Q4): write `data/document_index.v2.parquet`, keep
   old files in `data/index_backup/`, delete nothing. Execution is blocked by item 1.
3. **Gate 2B items 4–5** — human judgement, not code.
4. **Colab notebook never actually run in Colab** — the Gate 7 requirement stands.
5. **`requirements.lock.txt` stale** — regenerate after the R1/R6 dependency installs
   (`sqlalchemy`, `alembic`, `langchain-openai`, `tenacity` are not installed yet).
6. **Needle-recall margin** — the agreement on "within an agreed margin of edge recall"
   is a human decision; propose it after the first sweep, do not assume it.
