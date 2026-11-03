# Tresata

Turn SEC earnings releases into an identifier-free knowledge base of index-level KPIs. Run the pipeline from the CLI or inspect each stage on the workflow canvas.

- Filing-date membership, frozen company panels and configurable KPI coverage gates.
- Free OpenRouter models, persistent request budgets, caching and resumable jobs.
- Visual pipeline, quality and cost views, with input/output inspection and offline replay.

## Quick start

Native Linux requires `git`, `curl`, `tar` and `make`. Bootstrap installs the pinned Python, Node and uv toolchain through mise.

```bash
./setup.sh bootstrap
./setup.sh init
./setup.sh demo
./setup.sh website
```

Open **http://localhost:8767**. The website binds to `0.0.0.0`; use it on a trusted workstation/network. It has CSRF protection but no user login.

Initialization accepts the API key without echo, stores it in ignored `.env`, and writes non-secret preferences to ignored `configs/local.yaml`. Exported environment values take precedence. Skip the key for offline use. SEC downloads require a contact-bearing `SEC_USER_AGENT`.

## Run

```bash
./setup.sh cli --help
./setup.sh cli validate-config
./setup.sh cli estimate-scope
./setup.sh schedule plan
./setup.sh schedule run --once
./setup.sh schedule status
```

The default panel is **40 companies × four completed seasons**, seed **42**. Configure sources, models, limits, paths and publication thresholds in `configs/config.yaml`; use `configs/local.yaml` for local overrides. Timer installation is optional: `./setup.sh schedule install` shows the changes and asks first.

Only models ending in `:free` are accepted. Tracked defaults are 50 requests/day and 20/minute; override them locally to match your account. Bakeoff and retries consume requests. Interrupted requests with unknown outcomes stop for attention rather than being silently repeated.

## Data and privacy

Runtime files stay under ignored `data/`: filings, checkpoints, request ledgers, aggregates and exports. The final knowledge base is `data/exports/kpis.json`, containing **index proxies only**. Coverage gates suppress unsupported values; partial runs remain visible.

Index view is the default. Private evidence requires explicit server enablement and a session toggle; it never enters public exports or replay. RAPTOR, XBRL and Nowcast are planned capabilities.

## Development

```bash
make check          # Offline lint, types, secret scan and Python tests
make demo           # 500 synthetic releases; independent pandas comparison
make references     # Regenerate contracts and the CLI-derived registry
make web-build      # Build with the pinned Node toolchain
```

Frontend checks use the `typecheck`, `lint` and `test` npm scripts in `web/`, through mise. For example: `mise exec -- npm --prefix web test`. Browser tests use Playwright/axe and require Chromium. Use `.tools/bin/mise` if mise is not on PATH.

Package committed source with `scripts/package.sh tresata-source.zip`. Credentials, real data, caches, dependency directories and archives are excluded. Do not submit a zip of the working directory.

MIT licensed. Third-party data retains its own rights and terms.
