# Verification and acceptance

Run `make check` for deterministic Ruff, formatting, mypy, redacted credential scanning and pytest. Run `make demo` for 500 synthetic releases and exact independent pandas aggregation. `make mutations` edits/restores source temporarily and must run separately. Coverage is measured before setting a floor. Browser tests use Playwright and axe, with screenshots under private data/screenshots.

S1 measures 100 clean releases and 100 each with wrong numbers, wrong signs, missing quotes and wrong-period values. Per-case detections and the independent metric comparison are saved under data/demo. Synthetic precision/recall measures these controlled corruptions; it is not a claim about real-release accuracy.

S2 freezes 150 companies from eligible membership intervals, with stable panel identity and every planned pair. Live ingestion must still reach at least 500 verified releases, 100 companies and four seasons before S2 passes. The current restored real corpus has 60 releases/57 companies/eight seasons and does not meet this gate.

S3 requires a verified real company-facts response before implementing concept fallbacks, filing-date availability selection and comparable-observation agreement. The public company-facts URL was not accessible through the browsing tool; no fabricated fixture is presented as live verification. The contact-bearing SEC_USER_AGENT is absent.

S4 requires resumable real batches within verified account quotas. A successful HTTP smoke is separate from quality acceptance. The historical ledger has 60 successes and 42 truncations; old missing latency/reasoning measurements remain unknown. The updated one-call budget has not been verified live.

S5 prepares 30 reproducible private records with blank labels, scored=0. The agent's ten-record guidance inspection is separate from human labels and the five-record human spot-check. Numeric future guidance does not by itself imply raised/maintained/lowered guidance; the current direction field cannot measure all guidance providers.

Missing acceptance definitions (remaining K findings, tier gates, original screenshot widths, needle-recall margin) stay unverified. Local browser checks use 1440px and 390px, light and dark appearances. CI declares Python 3.10–3.14 and native Linux architectures; unrun targets remain unverified.

The empty target before restoration remains data/document_index.v2.empty-before-restore-20261102.parquet. All original backups remain. A failed rebuild or missing proof must never authorize deleting those files. The smoke's two HTTP 200 statuses verify authentication at that time only.

A real loopback restart probe is retained locally at data/verification/restart_probe.py, with its receipt at data/api-restart-proof.json. It starts a secret-free demo worker, terminates the API, starts a new API process, confirms the same worker remains running, then cancels it and checks recovered events. It makes no provider calls and is separate from socket-disabled unit checks.

The historical ledger's 102 attempts and the four later authentication probes were conservatively imported into UTC reservations with a private receipt. On UTC 2026-11-01 this was 106 known attempts, so the newly configured 50/day cap was already exhausted. This is a minimum known history, not verification of the account's actual allowance; a new UTC day resets the reservation cohort.

Final local results are recorded in [the acceptance receipt](../evidence/local-acceptance.json), [S1 receipt](../evidence/offline-verification.json) and [API restart receipt](../evidence/api-restart-verification.json). The isolated final suite passed 396 tests with 86.91% pytest coverage. Sixty-one selected mutants were caught across separate runs. Browser verification passed four tests; see HANDOVER.md for limitations and private log locations.

Network binding update: `./setup.sh website` now listens on 0.0.0.0:8767, following the explicit request for network access. Eighteen focused tests and two new mutants passed; static checks passed. An actual launcher run from /tmp served the website and all read-only API views over loopback, LAN and Tailscale interface addresses; same-origin/CSRF/forged-host checks passed. The verification server was stopped afterwards. No off-machine/firewall check was performed. See [network receipt](../evidence/network-binding-verification.json). The previous full-suite receipt predates this patch.
