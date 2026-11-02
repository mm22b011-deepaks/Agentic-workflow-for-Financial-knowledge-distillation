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

## Reduced scope, setup, scheduler and canvas delivery

The following reviewable local commits follow the prerelease snapshot. No push or history rewrite was performed. The documentation receipt commit follows this list; `git log ef4e696..HEAD` is the exact complete history.

- 9f989f0 feat(scope): freeze a request-budgeted forty-company panel
- 1ededaa feat(setup): initialize private credentials and local profiles safely
- 59d4c8e feat(schedule): reuse durable jobs for quota-aware daily tasks
- 004c5d8 fix(llm): preserve partial bakeoff scores and measure request attempts
- 5ab2c80 feat(web): add CLI workflow canvas and private node inspection
- 52f5b63 fix(labels): restrict review sheets to the current frozen scope
- 972cdf7 fix(web): show submitted jobs before metric polling completes
- 443f3ad fix(web): preserve replay and inspector artifact provenance
- 44a4653 fix(web): preserve imported graph edits and selection
- 12575e2 build: use the pinned toolchain for frontend tasks
- 487aefd fix(api): leave unfinished stage durations unmeasured
- e139129 fix(web): reveal contextual help across question pages

Final source checks: 454 tests / 84.95%, format 136 files, mypy 71. Browser, fresh-clone, mutation and live-batch evidence is recorded in HANDOVER.md. Exact-value scanning runs before each commit and over this session's history. The original v0.1.0-pre tag remains on the earlier snapshot.
