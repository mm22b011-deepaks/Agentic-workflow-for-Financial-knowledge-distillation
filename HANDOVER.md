# Tresata handover

Prepared 2026-11-02, Asia/Kolkata, from baseline ef4e696. Changes remain uncommitted for review. The native workstation implementation is built and locally verified. **Gate R0 remains FAILED; live production acceptance is incomplete.**

Network update after the original acceptance: the explicit user request now binds Tresata to **0.0.0.0:8767**. Port 8765 belongs to the unrelated, auto-restarting taskd system service, which was preserved. Eighteen focused tests, two new mutants and static checks passed; actual HTTP checks passed over localhost/LAN/Tailscale interface addresses. The verification server was stopped, leaving 8767 free. The full-suite/coverage table below predates this patch; see the [network receipt](evidence/network-binding-verification.json) and [ADR 006](docs/adr/006-network-binding.md). There is no login: reachable clients can obtain a session and operate jobs. Off-machine/firewall access was not tested.

## Start and operate

```bash
./setup.sh bootstrap
./setup.sh check
./setup.sh demo
./setup.sh website
```

Open http://0.0.0.0:8765. The launcher resolves its checkout from another directory. Bootstrap may use network; checks and synthetic execution subsequently work offline. Python 3.12.12, Node 24.10.0 and uv 0.9.7 are pinned through mise; Python and npm dependencies are locked. No privileged install or shell-profile edit is required.

Normal CLI/API/worker commands read secrets from the launching environment. Export a rotated OPENROUTER_API_KEY and a contact-bearing SEC_USER_AGENT before live work. Only the restricted smoke process can load .env internally. Authentication was verified at that time; rotation was not performed. DATA_DIR selects the private runtime root.

Use `./setup.sh cli --help`, `validate-index`, `estimate-scope`, `ingest`, `extract` and `aggregate`. The established `python -m nowcast.cli` interface remains available. Workflow, node/port, business, provider and artifact settings are in [configuration](docs/configuration.md) and the two YAML files under configs.

## Delivered behavior

Queue effects now withdraw the affected fields; only llm_failed, truncated, document_error and empty_extraction block an entire record. Numeric checks bind signs, scales, units and percentages locally. Parsing preserves table rows, period columns and normalized-text evidence offsets; ambiguous periods cannot borrow another window's number. The similarity threshold remains 0.85.

Consolidation is read-only, with explicit derived writers and stale-result supersession. Missing hashes remain unverified. Paths resolve from the actual configuration file. Index writes use atomic checkpoints and durable download receipts. Populated-index replacement requires an explicit, validated source and retains backups. SEC pagination, filing-date membership, complete planned-pair outcomes, schema-valid caching, configured model priority and isolated ledger-backed bakeoff are implemented. Unmapped identifiers stop SEC ingestion before requests, with the plan retained as unvisited.

The local React application provides Pipeline, Quality, Optimise, inspector and shared Markdown Help. CLI and FastAPI workers share pipeline services. SQLAlchemy/Alembic persists jobs, events, stage counts, artifact fingerprints, quota reservations and cooldowns. Workers are independent processes; cancellation occurs between items/stages. Resume requires the original configuration/registry fingerprint and reruns stages with item/cache reuse. Inspector execution requires current upstream artifact hashes; parameter values are read-only bindings to server configuration.

The API binds to `0.0.0.0:8767`, checks workstation host/origin and protects mutations with a session cookie and CSRF token. Use `http://<workstation-ip>:8767` from another device. Index exports/replays use generated schemas and omit identifiers. Replay disables execution. Trace requires explicit server enablement and a session toggle; it was not enabled. Its responses are private and non-cacheable. This delivery supports one trusted workstation operator. The single-writer guard covers API-managed jobs in one DATA_DIR; direct legacy CLI writers must run serially with website jobs against that directory. Per-document progress streaming, shared hosting and distributed workers are not delivered.

The registry drives supported KPI definitions, prompts, generated Help and UI metadata. Python implements the fixed metric algorithms and field rules using configured vocabularies/thresholds. New arbitrary formulas and the absent requested tier specification are not established by metadata changes. Outputs remain equal-weight company-growth proxies with comparability/zero-base handling, observation counts and explicit suppression.

## Verified evidence

| Check | Actual result | Evidence |
|---|---|---|
| Final isolated source, offline check | 396 tests passed in 105.17s; pytest coverage 86.91%, floor 80%; Ruff/format 117 files; mypy 58 source files; secret scan passed | [Public receipt](evidence/local-acceptance.json); data/fresh-offline-check.log |
| Main checkout | Full offline check passed 394 tests before the last two safeguards; their focused suites and final static checks passed; final isolated suite includes all final code | data/offline-check.log, data/optimise-telemetry-after.log, data/unmapped-after.log, data/final-static-checks.log |
| S1, main and isolated source | Each processed 500 releases, 125 companies, four seasons, 500 fake-provider calls and zero resumes; exact independent pandas agreement | [S1 receipt](evidence/offline-verification.json); data/offline-demo.log, data/fresh-offline-demo.log |
| Controlled validator classes | 100 clean releases, zero false positives; 100 each wrong-number/sign/missing-quote/period corruptions detected; per-reason precision/recall 1.0 | S1 receipt; this measures synthetic corruptions, not real accuracy |
| Curated mutations | 61 selected, 61 killed, zero survivors/malformed, in separate 50+8+1+1+1 batches | Batch log paths in public receipt; all 61 edits still match exactly once |
| Browser | Four Playwright tests passed in 52.7s; 1440px/390px, both themes, axe zero violations; replay/privacy/schema/export/graph and actual reload/cancellation exercised | data/browser-final.log; data/screenshots/{desktop,mobile}-{light,dark}.png |
| Real API restart | Same detached worker survived API shutdown; restarted API recovered status/events and cancelled it; no provider credentials/calls | [Restart receipt](evidence/api-restart-verification.json); data/verification/restart_probe.py |
| Bootstrap | Isolated fresh source bootstrapped successfully from /tmp with secrets absent; generated artifacts match main checkout | data/fresh-bootstrap-final.log |
| Online advisory/link checks | Python/npm: zero known dependency vulnerabilities; current external documentation link: HTTP 200 | data/vulnerability-audit.log, data/npm-audit.log, data/online-links-final.log |
| Source preservation | Original documentation hashes and legacy CSV byte comparison match; restored index equals preserved backup | docs/history/original-ef4e696/sha256.json; private restoration receipt |

Bootstrap reused installed host tools/caches; the RAM-backed acceptance environment used symlinks. This is fresh-source evidence, not a clean-host/no-cache installation claim. Both checks and demos subsequently refused socket connections with secrets absent. Actual hardware/runtime: Ubuntu 24.04.5 ARM64, Python 3.12.12. Python 3.10/3.11/3.13/3.14 and native x86_64 are declared in CI but were not run. Other Linux distributions/architectures remain unverified.

The matching newer Chromium download failed because disk space was insufficient. Browser checks used existing Chromium 153.0.8010.12 with Playwright 1.64.1. The original requested viewport definitions were unavailable; 1440px and 390px were explicit local assumptions. pytest coverage excludes the separately executed demo. Dependency/link lookups are online gates, separate from deterministic checks, as recorded in ADR 005.

## Real corpus, recovery and quotas

The active index was restored from data/document_index.v2.from-live-20261101.parquet after 60/60 raw hash, parsing, Item 2.02 and window checks. It contains 60 releases, 57 companies and eight seasons. SHA-256 of both active and source index:

```text
4bce92f07d00820129bdb5333749199eff20da6ce5df80a1fa18c0e8d4e13b1c
```

The original empty target remains data/document_index.v2.empty-before-restore-20261102.parquet; every older backup remains. Do not delete backups to resolve a failed rebuild. The archive tresata.zip was already absent at entry; that local deletion was preserved, and it is now untracked/ignored. Original worklogs were archived byte-for-byte before replacement. The legacy constituents CSV is preserved under docs/history/legacy-inputs.

The historical ledger has 60 successful calls and 42 truncations. Successful completion-token median/p95/maximum were 17,876.5 / 26,990.85 / 30,973. Reply budget/ceiling is now 32,768, packing is disabled by default and repair prompts are disabled in the shipped configuration. The updated one-call budget has not been verified live. Historical missing reasoning/content breakdowns and latency remain unknown. New attempts record supplied measurements, HTTP/cache outcomes and retries; Optimise shows measurement denominators separately.

Revalidating the original provider JSON, with original confidences and current validators, flags **53/60 documents for review**. It does not overwrite original results and is not live re-extraction or human accuracy evidence. Conservative row/period matching can generate false positives, especially with unusual fiscal calendars; human labels are required. See [saved-reply receipt](evidence/saved-reply-revalidation.json).

The 102 historical attempts and four later authentication probes were conservatively backfilled into reservations: 106 known attempts on UTC 2026-11-01. The newly configured cap is 50/day and 20/minute, so that UTC day is exhausted. Actual account allowance is unverified. Quotas share a provider scope within the same DATA_DIR; separate roots/accounts or requests made outside this application are not automatically reconciled. The private import receipt is data/manifests/known-usage-backfill-20261102.json.

Current full-window scope assumes 4,011 releases, 8,022 base requests and a 24,066-request retry upper plan: 161..482 full UTC days at 50/day. This is a configured estimate before missing releases, cache reuse and prior daily usage, not a completion promise. Verify account limits before raising the cap. No XBRL saved-call claim is made.

## Open gates and human actions

| Gate | Current state and required action |
|---|---|
| R0 | FAILED. Resolve real evidence/review problems and independently label outcomes before quality acceptance. |
| S2 | Frozen panel: 150 valid companies/1,153 pairs; seven unmapped eligible intervals recorded. Live minimum 500 verified releases/100 companies/four seasons not reached. Supply SEC contact, resolve mappings and audit membership intervals. Rejected first panel remains preserved; do not silently redraw. |
| S3 | No verified real company-facts response. As-of selection, configured concept fallbacks, source-conflict queues and additive-only Q4 derivation are not implemented. The browser could not access the required response. Concept candidates are preparation only. |
| S4 | No post-change real model batch/one-call acceptance. Rotate/export the key, verify account allowance and run resumable batches. Real latency/coverage/accuracy and remaining-day estimates are unavailable until runs exist. |
| S5 | Thirty private reproducible records prepared; supplied labels absent, scored=0. Human labelling and the separate five-record spot-check remain required. Ten agent guidance inspections do not satisfy either human gate. |
| Missing specification | Supply original K2/K4/K5/K9/K11/K12/K13 findings, tier gates, original viewport widths and needle-recall margin. These were unavailable, not closed. |
| Portability | Run declared Python/architecture CI matrix and clean-host bootstrap before claiming additional targets. |
| Privacy | Confirm NDA before enabling internal trace; leave default Index view for ordinary use. |

Broader historical fact/hierarchy migration, historical amendments, nowcasting and evaluation remain planned. The completed [review](docs/history/review-20261102.md), [ADRs](docs/adr/001-native-workstation.md), [current status](docs/history/status.md), [architecture](docs/architecture.md), [verification](docs/verification.md), schemas and generated references distinguish built, partial and unverified work. The MIT licence applies to software, not third-party data rights.
