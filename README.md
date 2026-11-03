# Tresata

Turn SEC earnings releases into an identifier-free knowledge base of index-level KPIs. Run the pipeline from the CLI or inspect each stage on the workflow canvas.

- Filing-date membership, frozen company panels and configurable KPI coverage gates.
- Free OpenRouter models, persistent request budgets, caching and resumable jobs.
- Visual pipeline, quality and cost views, with input/output inspection and offline replay.

## Quick start

Native Linux requires `git`, `curl`, `tar` and `make`. Bootstrap installs the pinned Python, Node and uv toolchain through mise.

```bash
./setup.sh
./setup.sh demo
./setup.sh website
```

Open **http://localhost:8767**. The website binds to `0.0.0.0`; use it on a trusted workstation/network. It has CSRF protection but no user login.

After `git pull`, restart with `./setup.sh website` and refresh your browser. This checks installed dependencies and rebuilds the website and registry before serving them. Your saved credentials and local configuration are kept.

On the canvas, start with **Validate config** and follow the arrows. Double-click a step to see what it takes and gives. **Run selected** executes that step using the latest unchanged upstream result; **Run all** runs the pipeline. Missing or changed inputs ask you to rerun the previous step. Dashed steps are planned and cannot run.

Bare `./setup.sh` bootstraps the toolchain and opens initialization. When `.env` has no key, it asks for a hidden paste and saves it with owner-only permissions. Skip the key for offline use. Existing values are kept by default; exported environment values take precedence. SEC downloads require a contact-bearing `SEC_USER_AGENT`. Use `./setup.sh bootstrap` for installation only, or `./setup.sh init --yes --no-key` for noninteractive offline setup.

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

Private runtime files stay ignored under `data/`. The checked-in **`data/offline/`** bundle contains 68 real index snapshots, 272 KPI observations and public coverage, cost, bakeoff, plan and stage summaries. Its manifest records capture time, checksums and partial-run limitations. It contains no raw filings, company identifiers, private evidence, credentials or job databases.

After bootstrap, view the bundled results without an API key or network access:

```bash
./setup.sh website --config data/offline/config.yaml
```

The bundle is a read-only, historical, partial snapshot; per-document inspection is unavailable. Published KPIs are in `data/offline/exports/kpis.json`, and `exports/index.json` can be loaded through Replay. Coverage gates suppress unsupported values.

Index view is the default. Private evidence requires explicit server enablement and a session toggle; it never enters public exports or replay. RAPTOR, XBRL and Nowcast are planned capabilities.

## Development

```bash
make check          # Offline lint, types, secret scan and Python tests
make demo           # 500 synthetic releases; independent pandas comparison
make references     # Regenerate contracts and the CLI-derived registry
make web-build      # Build with the pinned Node toolchain
```

Frontend checks use the `typecheck`, `lint` and `test` npm scripts in `web/`, through mise. For example: `mise exec -- npm --prefix web test`. Browser tests use Playwright/axe and require Chromium. Use `.tools/bin/mise` if mise is not on PATH.

Package committed source and the public offline bundle with `scripts/package.sh tresata-source.zip`. Private runtime data, credentials, caches, dependency directories and archives are excluded. Do not submit a zip of the working directory.

MIT licensed. Third-party data retains its own rights and terms.
