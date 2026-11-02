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
