# Contributing

Run `./setup.sh bootstrap`, then `./setup.sh check`. Keep source syntax compatible with Python 3.10 and the pinned native toolchain for the normal development environment. Use `make` targets in CI and locally. The bootstrap can use network; ordinary checks must not.

Before changing shared behavior, locate callers, fixtures, configuration, schema exports and tests. A defect starts with a failing regression through the real path. Security, money, parsers, branches and scripts need a meaningful check; reversible cosmetic edits do not need mirror tests. Keep domain values and workflows in the validated registry. Do not add company-specific branches.

Run `make references web-build` after changing contracts, registry or shared Help. Commit generated schemas/types/help with source. Run `make mutations` separately from ordinary tests because mutants temporarily edit source files. Never run it alongside editors or tests. Mutants that cannot apply are malformed, not killed.

Secrets, caches, downloaded filings, local databases, archives, browser traces and screenshots stay untracked. Use synthetic fixtures. The redacted scanner runs in pre-commit and CI; it reports locations, never matched values. Run `make audit-online` separately for current vulnerability lookups.

Report exact check results and limits. Do not turn human labelling, NDA confirmation, key rotation or absent hardware evidence into automated passes. Preserve original worklogs and real-data backups.
