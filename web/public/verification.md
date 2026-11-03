# Website verification — 3 November 2026

The website uses generated node contracts and schema labels for Input/Output, canvas quantities and Help. Planned capabilities say “Not built yet”. `./setup.sh website` rebuilds the registry and website after a pull.

## Completed checks

`PYTHONPATH=tests/offline make check`:

```text
All checks passed!
134 files already formatted
Success: no issues found in 72 source files
Required test coverage of 80% reached. Total coverage: 86.28%
492 passed, 4 warnings in 395.51s (0:06:35)
```

`npm --prefix web run build` completed TypeScript and Vite successfully. Frontend lint passed. The focused browser rerun for real action receipts, data-source badges, failed/completed summaries and missing duplicate counts passed in all four projects:

```text
20 passed (2.6m)
```

The final functional rerun on 1440 dark covered all measured fixture quantities, session pseudonyms, canvas accessibility, production routing, run selection, evidence review, help/tour, charts, replay, public exports, graph editing, execution guards and demo reload/cancellation:

```text
20 passed (8.5m)
```

The earlier four-project broad matrix passed 92 cases; its three failures led to the fast-action refresh fix, labelled keyboard-focusable pane scrolling and removal of a fragile test-only response proxy. Their replacements were rerun, rather than treating the earlier matrix as entirely green.

The corrected Plan, Ingest and Cohort screenshot/accessibility rerun passed:

```text
3 passed (1.4m)
```

The final demo-plan fixture regression check also passed:

```text
15 passed in 11.41s
```

The demo's 13-day estimate now comes from the same planning function as execution: the configured 50-request daily limit leaves 40 requests after the safety margin and retry reserve; 500 releases plus 20 bakeoff requests require 13 days. The expected 585 requests include the reserved retries.

The full node-panel audit completed with no axe violations in either theme at 1280 pixels; it captured both themes at 1280 and 1440 pixels for every node:

```text
54 passed (16.4m)
Screenshots verified: 216 / 216; newcomer sentences: 54 / 54
```

The screenshot manifest and extracted newcomer sentences are saved beside the images. The rebuilt website also returned HTTP 200 on port 8767, with execution enabled for its normal profile.

## Execution checks

The sequential worker audit completed 27 actions successfully using local filing fixtures and deterministic model replies. It covered configuration, planning, cohort selection, parsing, extraction, validation, review, consolidation, aggregation, coverage gates, publish/suppress, exports, reports, maintenance and scheduler actions. Build-members submission was accepted and cancelled before contacting its provider. The 500-release offline demo completed with independent pandas agreement.

Public demo pane audit (actual command output):

```text
{"node": "demo", "count": 1, "unit": "check", "informative_fields": 5}
{"node": "demo-ingest", "count": 500, "unit": "file", "informative_fields": 8}
{"node": "demo-parse", "count": 500, "unit": "text", "informative_fields": 8}
{"node": "demo-extract", "count": 500, "unit": "record", "informative_fields": 14}
{"node": "demo-validate", "count": 500, "unit": "record", "informative_fields": 14}
{"node": "demo-aggregate", "count": 16, "unit": "index row", "informative_fields": 10}
```

The populated real-worker pane field audit reported zero mismatches: each displayed example had at least three schema-labelled informative fields. Index output was checked for forbidden identifier and source-text fields. Session pseudonyms are tested separately from Internal trace.

## Reproduce

```bash
PYTHONPATH=tests/offline make check
npm --prefix web run build
npm --prefix web run lint
PLAYWRIGHT_BROWSERS_PATH=/path/to/browsers npm --prefix web test -- --workers=1
```

The Playwright configuration creates its own offline API fixture. `panels.spec.ts` saves four screenshots per node under `data/screenshots/panels/`: 1280 and 1440 pixels, dark and light. It checks newcomer source/count/description/visual content, human field labels, demo and measured quantities, pseudonym privacy and axe accessibility. Each node prints its “what goes in” sentence.

## Screenshot-only newcomer check

The refreshed dark screenshots show:

- **Build members:** checked settings (1 check) go in; 125 members come out, with joined dates, membership status and identifier-mapping summaries.
- **Plan:** 125 members go in; a plan for 500 releases, 500 base requests and 13 days comes out.
- **Extract:** 500 texts from Parse go in; 500 records containing EPS, revenue, guidance and tone come out, with values, currency and confidence.

Files: `build-constituents-1440-dark.png`, `estimate-scope-1280-dark.png`, and `extract-1440-dark.png` under `data/screenshots/panels/`.

## Limits

Live SEC and model-provider calls were not exercised. Local fixtures verify execution and data handoffs; they do not establish external service availability. Planned nodes remain disabled. The checked-in historical bundle is read-only and intentionally contains no per-document private evidence.
