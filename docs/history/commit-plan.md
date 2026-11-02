# Current-state snapshot commits

Baseline: ef4e696. Nothing was pushed or rewritten. Local data/backups were preserved.

| Commit | Slice |
|---|---|
| b52c849 | Hygiene, exact-value secret scan, source packaging, archive untracking |
| 072c0d2 | Coupled pipeline fixes, contracts/storage/jobs/API and connected tests |
| 2330f36 | Existing React application, schemas, generated artifacts and website CI |
| 122d253 | Preserved original worklogs, handover, ADRs, architecture and evidence |
| v0.1.0-pre | This commit record and prerelease tag; resolve with git rev-parse v0.1.0-pre |

Before committing, make check passed: Ruff/format 118 files, mypy 58 source files, 403 pytest tests in 109.91s, coverage 87.00%. Exact-value tree scanning passed before every slice. The source package was generated and verified without dotenv, data, dependency trees or caches. The session history was separately scanned from ef4e696.

The backend slice combines mutually dependent fixes/services/tests rather than committing broken intermediate imports; see ADR 007. The tag freezes the existing UI before reduced scope, setup, scheduler and canvas work.
