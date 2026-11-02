# Current implementation status

Updated 2026-11-02. The requested order was CLI implementation/review/checks, website completion/browser checks, then the approved free-model batch. The temporary acceptance hold is now released. Primary extraction is running under the independently managed user service; it does not depend on this chat or the API process. Original pre-canvas status is preserved in pre-canvas-20261102/status.md.

Day 0 completed live: 40 frozen companies, 160 planned pairs, 156 releases and four missing releases; 361 SEC attempts all HTTP 200. The active index retains 211 rows including historical data. Its pre-batch hash and the original 60-row backup hash are unchanged. All backups and raw files remain.

The authenticated account allowance was verified at 1,000/day; the human selected that cap locally. The unchanged per-minute limit is 20, scheduler usable allocation 895/day and tracked default 50/day. The approved user timer is active/enabled at 00:10 UTC / 05:40 IST.

The 20-request free-model bakeoff completed. Both configured models parsed ten of ten responses and produced nine usable core records. Lightning ranked first on measured field coverage, with median latency 246.68s versus Nano Omni 45.99s. Both emitted reasoning tokens. This ranking is not human accuracy. Primary extraction, aggregate/export and final quality/label reports are tracked in the live schedule; see evidence/live-batch-start.json for the timestamped starting receipt.

Final offline checks passed 454 tests in 175.17s, 84.95% Python statement coverage; Ruff/format 136 files and mypy 71 source files. Eight selected new mutants were killed in separate batches. Browser verification passed incrementally across 1280/1440 widths and light/dark themes, including all 54 panels, word budgets and axe. Typecheck, lint and production build passed. A fresh no-key clone passed 452 tests before the final two regressions, bootstrap/init/dated plan and the 500-release synthetic demo with exact pandas agreement. See docs/verification.md and evidence/canvas-acceptance.json for exact limitations.

The website serves the canonical CLI canvas on 0.0.0.0:8767. Ten real-artifact API projections passed schema/privacy checks. Index view remains identifier-free; Internal trace is server-disabled by default. The final knowledge base contains index proxies only. RAPTOR, XBRL and Nowcast remain visibly planned.

Gate R0 remains FAILED. Human labels (30), the separate five-record spot-check and NDA confirmation are pending and nonblocking for automation. Real extraction completeness, publishable coverage and human accuracy remain unresolved. Current scope cannot satisfy the original S2 requirement of 100 companies/500 real releases. Runtime/architecture targets beyond Ubuntu ARM64/Python 3.12 and off-machine access remain unverified. See HANDOVER.md for operation and remaining gates.
