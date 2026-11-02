# Architecture

Typer delegates established commands to shared pipeline services. FastAPI accepts typed v1 requests and selects server-owned workflow definitions. Pydantic validates registries, DAG dependencies and versioned contracts. The React application uses generated schemas/types and precompiled validators, so its CSP does not require runtime code evaluation.

A SQLite database under DATA_DIR records jobs, stage progress, ordered events, request reservations and cooldowns. SQLAlchemy owns access and Alembic revision 0001 owns its schema. Workers run in independent Python processes with argument arrays, never shell strings. Restart reconciliation checks Linux process identity; resume requires the original configuration fingerprint. Resume currently reruns stages, with downloaded-file and extraction-fingerprint checks providing item reuse.

EDGAR downloads are published by atomic rename. Durable row receipts precede batched index checkpoints and are recovered on restart. Original index files and backups are retained. Index replacement requires an explicit source when the target is populated. `validate-index` checks in place without writing. Consolidation is read-only; derived writers and stale-result supersession are explicit operations.

Parsing preserves table rows, cell boundaries, period headers and evidence offsets. Ambiguous row matches do not become accepted by finding a number elsewhere. A central queue-effect function decides which fields may contribute. Aggregation deduplicates by configured model priority, retains observation counts, and computes equal-weight company-growth proxies with zero-base handling. Broader historical fact storage, XBRL-assisted extraction and forecasts remain planned.

Inspector requests select a server-owned node and refer to a prior run's artifact records. Alembic revision 0002 stores stage output hashes and the request identity. A missing, changed or differently configured upstream artifact blocks execution. The client never supplies a filesystem path. The inspector displays validated parameter bindings and their active configuration values. Parameter edits use the configuration file; arbitrary client overrides are not accepted.

The single-writer guard covers API-managed jobs in one DATA_DIR. Direct legacy CLI commands do not join that job queue; use them serially with website jobs that write the same artifacts. Cancellation is cooperative between items/stages. The worker records stage counts and ordered events; it does not yet stream per-document progress. Evidence offsets refer to the normalized parsed text, with the raw source hash retained separately.

The registry supplies the closed KPI definitions to prompts, generated Help and UI. The four supported metric algorithms and field validation rules remain Python code, using configured vocabularies and thresholds. Arbitrary metric formulas and the missing requested tier specification are not implemented by editing registry metadata.

The website binds to 0.0.0.0:8767 following an explicit network-access request. taskd owns port 8765 on the development workstation. Host validation accepts the connection's actual local address plus localhost/workstation names. Origin and CSRF checks remain enforced, but there is no login; reachable network clients have operator access. See ADR 006.

## Canvas and inspection contracts

`cli_registry.catalogue` reads argparse, including parent commands and flags. `configs/workflow-canvas.json` adds layout, icons, ports, subnodes and configuration bindings; `workflow_registry` validates the combined catalogue. `scripts/export_contracts.py` generates the built registry, response schemas, CLI reference and shared Help; the frontend generator emits TypeScript plus standalone Ajv validators. Runtime settings are served separately to prevent local overlays from drifting the built registry.

`phase_services` exposes independently inspectable steps using existing parser, index, extraction and aggregation services. `inspection` reads known artifacts and immutable job snapshots; default responses project anonymous rows and aggregate values. Explicit session trace is additionally gated by the server. The labels endpoint validates record/field/value and atomically updates the private CSV under CSRF protection. `knowledge` publishes only the closed index KPI contract. No RAPTOR hierarchy is implemented.

The feature folders under web/src separate canvas, inspector, lenses, runs and Help. Zustand persists layout/lens/theme only; privacy and artifact state remain in session memory. Graph files contain layout/typed edges only. Live jobs retain canonical CLI order and server-validated upstream artifacts. Replay never makes mutation requests.
