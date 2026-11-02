# Tresata

A private Linux workstation pipeline for index-level earnings proxies, with a React website that starts real worker jobs. It ingests earnings releases, extracts reported facts through configured free models, validates evidence and aggregates company-growth observations. Gate R0 remains failed; this prerelease is not an accepted nowcasting system.

```bash
./setup.sh bootstrap
./setup.sh check
./setup.sh demo
./setup.sh website
```

Open http://127.0.0.1:8767 after starting the website. The launcher resolves its checkout and works from another directory. Bootstrap installs pinned Python, Node and uv through mise, synchronizes locked dependencies and builds the frontend. It does not edit shell profiles or require root. Linux prerequisites: curl, tar, make and git. The local setup was exercised on Ubuntu 24.04 ARM64; other declared CI targets remain unverified until exercised.

Normal commands use environment variables exclusively. Supply `OPENROUTER_API_KEY`, a contact-bearing `SEC_USER_AGENT`, and optionally `DATA_DIR` in the launching process. Do not put secrets in configuration or command arguments. Only `scripts/smoke_llm.py` may internally read an untracked .env file. Key rotation remains an account-owner task.

The website has Pipeline, Quality, Optimise, inspector and shared Markdown Help views. Live controls use the same services as the CLI, persistent SQLite jobs and independent workers. Replay loads validated Index JSON and disables execution. API events can be read again after a restart; cancellation occurs between items. Fingerprinted resume replays stages and uses the extraction cache and downloaded-file checks.

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

The old `python -m nowcast.cli` interface remains available. Configuration lives in [configs/config.yaml](configs/config.yaml); KPI definitions, workflow DAGs, node ports, limits and XBRL concept candidates are in [configs/registry.yaml](configs/registry.yaml). Project-relative paths resolve against the actual configuration directory plus paths.project_dir. Runtime artifacts live beneath the configured data root. Production defaults visit the full eligible scope; sampling and limits require explicit verification settings.

The API binds to `0.0.0.0:8767` and checks workstation Host, Origin and CSRF tokens. Open `http://<workstation-ip>:8767` from another device. It supports one trusted workstation operator, one active artifact writer and no uploaded code. Default Index view omits identifiers. Internal trace is disabled unless the server operator explicitly enables it after NDA confirmation; it is session-only and excluded from exports. Do not expose this server through a public tunnel.

The deterministic demo generates 500 releases across 125 companies and four seasons, including controlled evidence corruptions. It uses a fake provider through the real extraction path, checks validator detections and compares aggregation exactly with an independent pandas computation. It makes no provider calls. Live 500-release, as-of XBRL and human-labelled acceptance gates remain separate.

See [CLI reference](docs/cli.md), [shared Help](docs/help.md), [architecture](docs/architecture.md), [verification](docs/verification.md), [configuration](docs/configuration.md), [decisions](docs/adr/001-native-workstation.md), [review](REVIEW.md) and [current status](docs/history/status.md). The original worklogs remain byte-for-byte under [history](docs/history/original-ef4e696/sha256.json). The MIT software licence does not grant rights to third-party data.

For exact local results, operating limits and remaining human actions, read [HANDOVER.md](HANDOVER.md). Public receipts are under [evidence](evidence/local-acceptance.json); private filings, panels, logs and screenshots remain under the ignored data root.

Network binding was requested explicitly. Port 8765 is occupied by the auto-restarting system taskd service on the development workstation, so Tresata defaults to 8767. Override with `./setup.sh website --port 9000`. There is no login: reachable network clients can obtain a session and operate jobs. Same-origin/CSRF checks protect browser requests but do not authenticate network users. See [ADR 006](docs/adr/006-network-binding.md).
