# Tresata

A private Linux workstation pipeline for index-level earnings proxies, with a React website that starts real worker jobs. It ingests earnings releases, extracts reported facts through configured free models, validates evidence and aggregates company-growth observations. Gate R0 remains failed; this prerelease is not an accepted nowcasting system.

```bash
./setup.sh bootstrap
./setup.sh init
./setup.sh check
./setup.sh demo
./setup.sh website
```

Open http://127.0.0.1:8767 after starting the website. The launcher resolves its checkout and works from another directory. Bootstrap installs pinned Python, Node and uv through mise, synchronizes locked dependencies and builds the frontend. It does not edit shell profiles or require root. Linux prerequisites: curl, tar, make and git. The local setup was exercised on Ubuntu 24.04 ARM64; other declared CI targets remain unverified until exercised.

`./setup.sh init` accepts a hidden key and SEC contact, stores local credentials in an ignored mode-600 `.env`, and writes non-secret scope/quota choices to ignored `configs/local.yaml`. The dedicated launcher reads dotenv without overriding exported values; direct library execution reads the environment. Keys never belong in arguments, logs or archives. `./setup.sh init --yes --no-key --scope standard` configures offline operation without prompts.

The website is a node canvas with Flow, Quality and Cost overlays. Double-click a node to inspect input, parameters and output; CLI-generated controls and schemas share the backend contracts. Evidence and human verdicts require explicit Internal trace. Replay disables execution and accepts only identifier-free Index JSON. The schedule strip uses the same durable jobs, events and quota reservations as the CLI.

```bash
./setup.sh cli --help
./setup.sh cli validate-config
./setup.sh cli validate-index
./setup.sh cli freeze-panel
./setup.sh cli estimate-scope
./setup.sh cli ingest
./setup.sh cli extract
./setup.sh cli aggregate
```

The old `python -m nowcast.cli` interface remains available. Configuration lives in [configs/config.yaml](configs/config.yaml); KPI definitions, workflow DAGs, node ports, limits and XBRL concept candidates are in [configs/registry.yaml](configs/registry.yaml). Project-relative paths resolve against the actual configuration directory plus paths.project_dir. Runtime artifacts live beneath the configured data root. The default is a frozen 40-company × four-season panel (seed 42). The configured custom profile retains full-window capability; changing a frozen panel never silently redraws it.

The API binds to `0.0.0.0:8767` and checks workstation Host, Origin and CSRF tokens. Open `http://<workstation-ip>:8767` from another device. It supports one trusted workstation operator, one active artifact writer and no uploaded code. Default Index view omits identifiers. Internal trace is disabled unless the server operator explicitly enables it after NDA confirmation; it is session-only and excluded from exports. Do not expose this server through a public tunnel.

The deterministic demo generates 500 releases across 125 companies and four seasons, including controlled evidence corruptions. It uses a fake provider through the real extraction path, checks validator detections and compares aggregation exactly with an independent pandas computation. It makes no provider calls. Live 500-release, as-of XBRL and human-labelled acceptance gates remain separate.

See [CLI reference](docs/cli.md), [shared Help](docs/help.md), [architecture](docs/architecture.md), [verification](docs/verification.md), [configuration](docs/configuration.md), [decisions](docs/adr/001-native-workstation.md), [review](REVIEW.md) and [current status](docs/history/status.md). The original worklogs remain byte-for-byte under [history](docs/history/original-ef4e696/sha256.json). The MIT software licence does not grant rights to third-party data.

For exact local results, operating limits and remaining human actions, read [HANDOVER.md](HANDOVER.md). Public receipts are under [evidence](evidence/local-acceptance.json); private filings, panels, logs and screenshots remain under the ignored data root.

Network binding was requested explicitly. Port 8765 is occupied by the auto-restarting system taskd service on the development workstation, so Tresata defaults to 8767. Override with `./setup.sh website --port 9000`. There is no login: reachable network clients can obtain a session and operate jobs. Same-origin/CSRF checks protect browser requests but do not authenticate network users. See [ADR 006](docs/adr/006-network-binding.md).

Schedule: `./setup.sh schedule plan`, `status`, `run --once`, `pause`, and `resume`. Timer installation is explicit. Free-only models, persisted UTC request limits and a shared writer guard apply to both API and scheduler jobs. Current delivery order is CLI acceptance, website acceptance, then the approved model batch. See [ADR 012](docs/adr/012-verified-allowance-and-delivery-order.md).
