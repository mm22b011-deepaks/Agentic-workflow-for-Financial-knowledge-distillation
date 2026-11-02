# ADR 007: ordered delivery and secret boundary

The current request supersedes earlier key-rotation advice: the human keeps the key. Its value is handled only inside the scanner, setup wizard or provider process; it is never displayed, passed in arguments, committed or packaged. The scanner reads environment and dotenv values internally, scans every tracked/untracked non-ignored candidate including binary files, and emits file names only. Its history mode audits this session's new commits. Pre-commit always invokes it; CI invokes it through make check.

Only scripts/package.sh is supported for source zip production. It scans first, exports committed source through git archive, excludes secrets/runtime data/dependencies/caches/archives, and validates entries. Local files and all real-data backups remain untouched.

Work order is current-state commits, reduced scope, interactive setup, scheduler, then the requested canvas/API integration. No RULES file exists in this checkout or its applicable ancestors; claude.md and CONTRIBUTING.md supply the available repository rules. Related backend changes and their tests are committed together where separating imports would break an intermediate tree. Historical receipts remain dated evidence, not certification of future changes.

Installer and scheduler processes may internally read/write dotenv because the current request explicitly requires it. Ordinary CLI/API processes remain environment-driven; launcher-managed dotenv loading is confined to a dedicated child entry point and never silently overrides an exported value. Any discovered conflicting requirement is recorded in a further ADR rather than silently weakening privacy, quotas or test claims.
