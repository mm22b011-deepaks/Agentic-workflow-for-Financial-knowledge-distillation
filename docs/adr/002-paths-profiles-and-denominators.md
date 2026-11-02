# ADR 002: paths, membership and production scope

The actual configuration file's directory plus `paths.project_dir` defines the project root. Runtime locations use the shared Paths implementation; DATA_DIR overrides only the data root. Readers do not create directories.

Filing-date membership supersedes first-day-of-quarter membership. Planned pairs include every interval intersecting a season; the downloaded release must also fall inside membership on its filing date. Production defaults have no document or per-company cap and no sampling. Explicit verification invocations may set a subset or document limit. Every planned pair remains in the private outcome artifact; attempted pairs define n_expected, while planned totals and execution completeness must be reported separately.

The frozen verification panel is never silently redrawn to improve coverage. Missing outcomes are part of its result. A complete production run still depends on the quality of the membership source and unmapped-company audit.

The first freeze was found to contain one unresolved identifier. It was retained privately as a rejected panel, and the corrected seeded panel includes 150 valid companies/1,153 pairs. Seven eligible unmapped intervals remain recorded in panel metadata. This correction is an explicit validation repair, not a coverage-driven redraw.
