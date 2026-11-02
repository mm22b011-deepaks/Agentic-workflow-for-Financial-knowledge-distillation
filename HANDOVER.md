# Tresata handover

2026-11-02, Ubuntu ARM64, Asia/Kolkata. CLI repairs/review and website verification completed in the requested order. **The approved free-model extraction is running independently under the user service. Final KPI coverage and human accuracy are pending; Gate R0 remains FAILED.** Nothing was pushed or rewritten. The original v0.1.0-pre tag remains on the earlier snapshot.

## Operate

```bash
./setup.sh bootstrap
./setup.sh init
./setup.sh check
./setup.sh demo
./setup.sh website
./setup.sh cli schedule status
./setup.sh cli schedule plan
```

The website is already running on **0.0.0.0:8767**. Open http://localhost:8767 locally or http://<workstation-ip>:8767 on the trusted network. Port 8765 belongs to the unrelated taskd system service and was preserved. A second website process will conflict; check the existing process before starting one. The current detached website PID is in data/website-process.json.

Python 3.12.12, Node 24.10.0 and uv 0.9.7 are pinned through mise. Use the launcher or Make targets; system Node 18 cannot build this Vite version. `make web-build` uses pinned mise. Generated web/node_modules and web/test-results were removed after checks; bootstrap restores dependencies. Compiled web/dist remains local for the running site. No shell-profile edits or root installation are needed.

The approved timer **tresata-77979336.timer** is enabled/active at **00:10 UTC / 05:40 IST**, Persistent=true. Its existing service owns the long batch, with unlimited startup timeout. Type=oneshot displays activating/start while work runs; that is expected. Check it with `systemctl --user status tresata-77979336.service`. The independent worker and request receipts survive API/controller restart. The controller transfer preserved the same job/worker and unchanged reservations. The temporary acceptance hold is now released.

`schedule pause` requests cancellation between items; `schedule resume` resumes within the existing approval and quota. Avoid running direct legacy CLI writers concurrently against this DATA_DIR. API workers and scheduler share a writer guard; arbitrary direct CLI processes are not automatically serialized. Do not start duplicate extraction jobs to accelerate this run.

## Credentials, scope and live work

The dedicated child launcher reads ignored .env without overriding exports. Direct application/library calls remain environment-only. The key is never an argument or UI value. The stored file is mode 600. A stale exported OPENROUTER_API_KEY previously shadowed the valid stored key; use `unset OPENROUTER_API_KEY` in the launching shell, or prefix a launcher command with `env -u OPENROUTER_API_KEY`. Do not copy the key into commands, logs or this document. The human declined rotation; no rotation is required to continue this authorized run.

The authenticated account endpoint verified **1,000 free-model requests/day** and zero model pricing. The human selected 1,000/day in ignored configs/local.yaml; tracked defaults stay 50/day. The unchanged per-minute setting is 20. Scheduler capacity is **895/day** after 10% margin and five withheld requests. Account allowance is requests, not a guarantee of 1,000 successful extractions. Retries/bakeoff consume requests; cache hits may avoid them. External usage outside this DATA_DIR is not automatically reconciled. See evidence/account-quota.json.

The fixed panel remains **40 companies × four completed filing seasons**, seed 42. Changed size/seed/universe cannot silently redraw it. Day 0 completed **156 releases**, four missing-release outcomes and 361 SEC attempts, all HTTP 200. The retained active index has 211 rows including historical data. No raw files, indexes or backups were deleted.

The bakeoff completed **20 actual model requests**, ten documents for each configured :free model. Both parsed all responses and produced nine usable core records. Lightning ranked first on aggregate field coverage. Its median latency was **246.68s**, versus Nano Omni **45.99s**; both emitted reasoning tokens. This is a measured ranking, not human accuracy. Primary extraction uses Lightning, one model per release, shared quota reservations and durable receipts. The slow model can take several hours for the remaining panel; no completion-time guarantee is made.

At 15:27 UTC the task was running with **31 reservations today**, including bakeoff, and 12 existing selected-model result files in scope. File presence is not a count of new calls or validated observations. Read current state from the website Schedule strip, `schedule status` or data/manifests/schedule.json. The timestamped receipt is evidence/live-batch-start.json. Aggregate, export, quality/report and private 30-record label preparation follow automatically. Human label/spot-check/NDA tasks do not block unrelated automation.

## Delivered behavior and boundaries

The React Flow canvas mirrors the canonical argparse command/flag catalogue through generated registry, schemas and types. It provides 54 nodes across production, ingest, extraction, maintenance and demo groups, three lenses, measured/unavailable charts, a schedule strip, contextual Help and a three-pane inspector. Live jobs share CLI services, persistent FastAPI jobs, CSRF, cancel/resume and upstream fingerprints. Replay never executes.

Index view and exports omit company/document identifiers. The final KPI knowledge base is **index proxies only**, with equal-weight company-growth semantics, eligible denominators, observation counts, coverage, suppression and provenance hashes. Missing measurements are unavailable, never invented zeros. Pytest coverage is statement coverage; KPI coverage is usable observations divided by eligible observations; neither measures extraction accuracy.

Internal trace requires both server enablement and a session toggle; the running server leaves it disabled. Evidence/verdicts are private, non-cacheable and excluded from replay/exports. The inspector shows a bounded source-row excerpt; the private API exposes complete source. Tables and controls page their visible content to respect the word budget. Graph imports preserve layout/edited edges within one known command group; Run all retains canonical CLI order. Uploaded graphs do not introduce executable code. Per-document progress streaming and distributed/shared-hosting operation are not delivered.

There is no login. Same-origin/Host/CSRF protections do not authenticate reachable network users; this is the requested trusted-workstation deployment. On-machine localhost/LAN/Tailscale address checks passed historically; no off-machine/firewall test was run. RAPTOR, XBRL, Nowcast, evaluation and the broader historical fact/hierarchy migration remain explicitly planned. No RAPTOR hierarchy or XBRL saved-call claim is made.

## Verification

| Check | Actual result |
|---|---|
| Final offline Python gate | **454 passed, 4 warnings, 175.17s; 84.95% statement coverage**, unchanged 80% floor; Ruff clean, 136 formatted files, mypy 71 source files |
| Fresh no-key source | Bootstrap, noninteractive init, dated plan and socket-disabled check passed: **452 tests / 84.88%**, before the final two regressions; reused host tools/caches |
| Fresh offline demo | **500 releases, 125 companies, four seasons, 500 fake calls**; exact independent pandas agreement |
| Controlled validators | 100 clean/zero false positives; 100 each missing quote, wrong number, period and sign detected; precision/recall 1.0 where defined, synthetic only |
| Frontend | Pinned typecheck, lint and build passed; registry regenerated without drift |
| Browser | Incremental passing batches: **40 canvas + 12 provenance/live + 8 graph/canvas + 4 Help** cases, including overlaps, covering 52 unique project cases at 1280/1440 widths and both themes; not one final whole-suite invocation |
| Accessibility/privacy | Axe zero violations in exercised views; every node panel/text budget; replay/schema/export checks; ten real-artifact API responses schema/privacy validated |
| Mutation checks | **Eight selected new mutants killed**, zero survived/malformed, in separate 6+1+1 batches; historical 61 not rerun |
| Online checks | Python/npm audits: zero known vulnerabilities; two provider documentation links HTTP 200 |
| Secrets/hygiene | Candidate tree/session history and 1,404 private log/artifact/built-JS files scanned clean; no tracked dotenv/data/dependencies/archives/caches |

Exact safe receipts: evidence/canvas-acceptance.json, evidence/live-batch-start.json and docs/verification.md. Private logs include data/final-delivery-check.log, fresh-delivery-check.log, fresh-delivery-demo.log, playwright-canvas-final.log, provenance-browser-final.log, graph-canvas-final.log, context-help-final.log and duration-mutation-final.log. Screenshots are in data/screenshots; production dark and evidence light views were visually reviewed. Test artifacts are not source-package contents.

Python 3.10/3.11/3.13/3.14, x86_64, other distributions and clean-host/no-cache bootstrap were not exercised. The tested host is Ubuntu 24.04 ARM64/Python 3.12.12. Four multiprocessing/fork warnings remain. Online dependency/link checks are intentionally separate from offline acceptance.

## Preservation, packaging and remaining gates

The original 60-row backup data/document_index.v2.from-live-20261101.parquet still hashes to **4bce92f07d00820129bdb5333749199eff20da6ce5df80a1fa18c0e8d4e13b1c**. The active pre-batch index still hashes to **b7b3355a392174d78ca9140c4fb6c6ddb4027d6f4474df33136b2e0d6099ee57**. The empty-before-restore file and every earlier backup remain. Original worklogs remain archived; pre-canvas README/HANDOVER/status were preserved before replacement, with hashes under docs/history/pre-canvas-20261102.

Use only `scripts/package.sh data/tresata-source-delivery-20261102.zip` for source archives. It exports committed source and rejects dotenv, git/data/dependency/cache directories and nested archives. No local credentials, real artifacts or backups belong in a package. Current commits are recorded in docs/history/commit-plan.md; the documentation receipt commit follows that list.

Gate R0 remains FAILED. Human actions are **30 record labels**, the separate **five-record spot-check**, and **NDA confirmation before enabling trace**. Only supplied labels may be scored. The original S2 requirement of at least 100 companies/500 real releases is unmet by this 40-company scope. S3 XBRL remains planned; S4 batch completeness/final publishable coverage and S5 human accuracy remain pending. Missing original K/tier acceptance specifications remain unverified. Synthetic success and parsed bakeoff responses do not close those quality gates.
