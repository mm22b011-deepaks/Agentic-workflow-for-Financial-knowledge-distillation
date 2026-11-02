# Verification and acceptance

`make check` runs Ruff, formatting, exact-value secret scanning, mypy and pytest offline. Dependency vulnerability and external-link lookups are separate online gates. Mutation checks temporarily edit and restore source and run separately from ordinary checks. Screenshots, browser traces, real artifacts and full logs remain private under ignored directories.

## Current delivery, 2026-11-02

The final working-tree offline gate passed **454 tests in 175.17s**, coverage **84.95%** against the unchanged 80% floor. Ruff passed, 136 files passed formatting and mypy checked 71 source files. Four multiprocessing/fork warnings remain. Receipt: data/final-delivery-check.log. Coverage is the fraction of measured Python statements exercised by tests; it is not KPI coverage or extraction accuracy. Historical 86.91% belongs to the earlier 396-test snapshot, preserved in evidence/local-acceptance.json.

A fresh source clone bootstrapped without credentials, then passed socket-disabled `make check`: **452 tests in 176.32s, 84.88%**, before the two subsequent provenance/duration regressions. Its no-key noninteractive init and dated schedule plan passed; no dotenv was created. Fresh bootstrap reused host tools and dependency caches with RAM-backed symlinks, so this is not clean-host evidence. Logs: data/fresh-delivery-check.log and data/fresh-delivery-plan.log.

The fresh offline demo processed **500 releases, 125 companies, four seasons and 500 fake calls**, with exact independent pandas aggregation. There were 100 clean releases with zero false positives, and 100 each of missing-quote, wrong-number, wrong-period and wrong-sign corruptions, all detected. Controlled-class precision/recall was 1.0 where defined. This establishes synthetic behavior only. Receipt: data/fresh-delivery-demo.log.

The canvas browser checks use 1280/1440 widths and dark/light themes. All 54 node panels, text budgets, CLI/flag and served/built registry parity, evidence wrong-row detection, CSV verdict persistence, Help/tour, measured/empty charts, replay isolation, schema rejection, live job controls and identifier-free exports were exercised. Separate passing batches comprise 40 canvas cases, 12 provenance/live cases, eight graph/canvas cases and four contextual Help cases; overlapping cases are not additional unique tests. Axe reported no violations in the exercised views. Typecheck, lint and production build passed using pinned Node 24. Logs: data/playwright-canvas-final.log, data/provenance-browser-final.log, data/graph-canvas-final.log and data/context-help-final.log. Earlier live/landing checks also passed eight cases. Screenshots: data/screenshots/.

Six selected delivery mutants, one canonical-input provenance mutant and one running-duration mutant were killed in separate runs, with zero survivors or malformed mutations. These extend, rather than rerun, the historical 61 selected mutants. Python/npm online audits reported zero known vulnerabilities; two external provider documentation links returned HTTP 200. Logs: data/python-audit-delivery.log, data/npm-audit-delivery.log and data/online-links-delivery.log.

Real API restart evidence confirms that the independent worker survives API restart and cancellation still works. Current real-artifact typed/privacy probes cover ten endpoints; production landing uses real release presence even before KPI publication. Network binding is 0.0.0.0:8767; historical localhost/LAN/Tailscale interface checks passed, but off-machine/firewall access remains untested. See evidence/api-restart-verification.json and evidence/network-binding-verification.json.

## Quality gates

S1 synthetic behavior passes as described above. S2's original minimum remains 500 real releases, 100 companies and four seasons. Day 0 completed 156 releases across a reduced frozen 40-company/four-season panel, with four missing-release outcomes; it cannot satisfy that original size gate. The previous 150-company and rejected panels remain preserved.

S3 is planned: no verified real company-facts response or implemented as-of concept fallback/Q4 derivation is claimed. S4 is running: account allowance and zero pricing were verified; 20 free-model bakeoff requests completed before primary extraction began. Current reservations and task states are in data/manifests/schedule.json. Completion, real extraction accuracy and final publishable coverage remain unresolved until the batch and human review finish.

S5 prepares a private 30-record sheet after extraction; only supplied human verdicts may be scored. Thirty labels, the separate five-record human spot-check and NDA confirmation remain pending. The ten-record agent guidance inspection is separate. Gate R0 remains FAILED. Missing original K findings/tier specifications remain unverified, not silently closed.

RAPTOR, XBRL, Nowcast and broader historical fact/hierarchy migration remain planned. The exercised platform is Ubuntu 24.04 ARM64, Python 3.12.12. Other declared Python 3.10–3.14/runtime/architecture targets have not been run.

All original index backups, raw files and the empty-before-restore index remain intact. Historical latency/reasoning measurements remain unknown. See HANDOVER.md and evidence/canvas-acceptance.json for the current result, rather than treating historical receipts as current acceptance.
