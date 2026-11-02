# Configuration

`configs/config.yaml` defines runtime, locations, sources, parsing, provider parameters, cache, budget, extraction vocabularies, aggregation gates, reporting and universe reconstruction. Unknown keys fail validation. Overrides use repeated `--set dotted.key=value`; secrets are environment variables, never overrides.

`paths.project_dir` is relative to the configuration file's actual parent. The shipped value is `..`. `DATA_DIR` selects the runtime data root. `paths.registry_file` locates the versioned business/workflow registry. Prompts remain project source, not mutable runtime data.

`configs/registry.yaml` is the closed KPI and workflow registry. Its node definitions declare input/output ports, executable/planned capability and shared Help. Workflow edges must connect compatible ports and form a DAG with every required upstream input. Unknown/planned nodes cannot run. Concept candidates are declarative preparation; XBRL fallback execution is not implemented yet.

Production uses every eligible interval and season: `subset_n=0`, `edgar_max_documents=0`, `edgar_docs_per_cik=0`. For verification, explicitly supply a seeded subset/cap or the frozen panel constituents. Do not call a capped run production-complete.

`aggregation.min_constituents` and `min_observations` remain 10. `quote_match_min_ratio` remains 0.85. Missing requested tier-gate definitions are unverified rather than invented. Model priority defaults to configured model order; bakeoff recommendations require human-labelled accuracy before being treated as a quality ranking.

The conservative provider request cap is 50 per UTC day and 20 per minute until account limits are verified. The configured 32,768-token reply budget covers the largest historical successful completion, but does not establish future reliability.

Guidance presence is recorded separately from guidance revision direction. Numeric future outlooks can be present without any stated raise/maintain/lower comparison. Legacy records without presence observations cannot establish complete provider counts. The fiscal-period proximity diagnostic is a review hint and may flag companies with non-calendar fiscal calendars; no company-specific calendar is guessed.

Quota reservations share the jobs database beneath the same DATA_DIR and provider URL. Separate data roots have separate reservation stores; they do not establish an account-wide allowance. The Optimise view shows UTC reservations separately from ledger HTTP attempts and displays measured token counts with their observed-attempt denominators. Unknown historical content/reasoning breakdowns remain unavailable.

`estimate-scope` labels token assumptions per model and reports base requests, the configured retry upper plan and UTC days at the configured cap. The shipped output-token assumption is 32,768, based on the measured historical maximum plus headroom; it is a conservative planning assumption, not measured average use. Expected documents assume one release per eligible company-quarter/form. Missing releases, cache reuse, prior daily usage and verified account limits can change elapsed days.

SEC ingestion refuses unmapped, non-ASCII or zero CIKs before any SEC request. It retains every planned pair as unvisited when this check fails. Resolve the seven recorded unmapped eligible intervals before attempting the full production window; do not hide them by reducing the universe.

## Reduced scope

- `scope.profile`: `small` (20x4), `standard` (40x4, default), `large` (100x4), or `custom`.
- `scope.companies`: count for custom; zero with zero seasons means the full configured window. Presets determine their own counts.
- `scope.seasons`: latest N completed calendar quarters for custom; presets use four. Zero with zero companies retains the original window.
- `scope.seed`: deterministic panel seed, default 42.

The same point-in-time companies are frozen across all seasons in `data/manifests/panel.json`. Changed input specifications/universe never silently redraw the file. A changed panel requires preserving/archiving the old one or choosing a separate DATA_DIR. The historical 150-company panel remains separate and preserved.

The shared forecast also reads `scheduler.safety_margin` (0.10), `scheduler.retry_reserve` (5 requests held per model day), `scheduler.bakeoff_requests` (20), `scheduler.max_days` (365), and `schedule.run_at_utc` (`00:10`, HH:MM UTC). The usable daily capacity is floor(limit x (1-margin)) minus reserve. The human sets `llm.requests_per_day` and `llm.requests_per_minute`; these are UNSURE until verified and are never raised automatically. Insufficient numeric per-season scope is warned against `aggregation.min_observations`.

## Local initialization

`./setup.sh init` checks/bootstrap-installs the pinned tools, accepts a hidden key, preserves a mode-600 ignored .env, checks exported-value shadowing, accepts SEC contact and scope/quota choices, and writes only non-secret settings to ignored `configs/local.yaml`. Existing values are defaults. `./setup.sh init --yes --no-key --scope standard` is noninteractive and disables model requests. `--key-from-env`, `--sec-contact-from-env`, `--daily-limit` and `--minute-limit` support automated provisioning without key-valued arguments.

Local YAML layers over the tracked base; explicit --set wins. `llm.offline=true` forbids model requests. `TRESATA_IGNORE_LOCAL_CONFIG=1` disables the operator layer for hermetic checks; setup explicitly reads its own local choices. Bootstrap stamps hash uv.lock, web/package-lock.json and mise.toml so a repeated init can remain offline. The dedicated child launcher reads dotenv without overriding exports; direct library callers remain environment-only. No shell profile is changed and timers are never silently installed.

## Scheduling

`schedule.run_at_utc` is an HH:MM UTC daily timer time (00:10). `scheduler.safety_margin` reserves a fraction of the configured daily limit (0.10). `scheduler.retry_reserve` withholds additional requests (5). `scheduler.bakeoff_requests` caps the initial measured comparison (20). `scheduler.max_days` stops an overdue plan for attention (365). These controls do not increase the provider cap.

`setup.sh schedule plan` prints UTC and local dates. `status` reports durable tasks; `run --once` performs due work and exits; `run --daemon` waits between checks. `pause` requests cancellation between items. `resume` unpauses; `resume --confirm-models` is the operator's explicit approval of model batches. `install` and `uninstall` show their exact systemd/cron changes and require confirmation. `setup.sh doctor` checks local credential provenance, contact, disk and remaining reservations without printing a secret.

Daily totals include other workstation processes using the shared quota database. Unknown in-flight responses block for attention rather than being resent. Model ranking uses measured parse success, empty rate, field coverage, reasoning/completion tokens and latency data, not unprovided human labels. Prepared label sheets remain private under data/inputs; the historical fact-store migration remains separate.

`doctor --verify-provider` performs authenticated key-information and zero-pricing checks without exposing response bodies. The verified current account allowance is recorded separately from configured limits. The human changed this workstation's ignored local overlay to 1,000/day on 2026-11-02; the tracked default stays 50/day. With 10% margin and five withheld requests, this gives 895 usable requests/day.

`schedule run --start-models --once` explicitly advances approved model work to today after Day 0 completes. It refuses absent approval or an active acceptance hold and retains every quota/dependency check. This session's order is CLI checks, website checks, then the first real batch. The temporary acceptance hold was released after those checks passed; the approved timer and service now run model work.

The exported KPI knowledge base (`data/exports/kpis.json`, schema `KPIKnowledgeBase.json`) contains index proxies only: KPI, filing season, as-of date, value, unit, usable/expected counts, coverage, status and artifact/configuration hashes. Suppressed values are null. Company identifiers, source text and verdicts are excluded. RAPTOR, XBRL and Nowcast remain planned capabilities.
