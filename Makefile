PYTHON ?= .venv/bin/python
RUFF = .venv/bin/ruff
MISE_BIN = $(if $(wildcard .tools/bin/mise),.tools/bin/mise,mise)
.PHONY: bootstrap check lint format typecheck test demo website references web-build mutations audit-online
bootstrap:
	./setup.sh bootstrap
check: lint format typecheck test
lint:
	$(RUFF) check src scripts tests
	$(PYTHON) scripts/scan_secrets.py
format:
	$(RUFF) format --check src scripts tests
typecheck:
	.venv/bin/mypy src
test:
	$(PYTHON) -m pytest -q --cov=nowcast --cov-fail-under=80 --cov-report=term:skip-covered --cov-report=json:data/coverage.json
demo:
	$(PYTHON) -m nowcast.app demo --config configs/config.yaml
website:
	$(PYTHON) -m nowcast.app serve --config configs/config.yaml
references:
	$(PYTHON) scripts/export_contracts.py
web-build:
	$(MISE_BIN) exec -- npm --prefix web run build
mutations:
	$(PYTHON) scripts/mutation_check.py --verbose
audit-online:
	.venv/bin/pip-audit --skip-editable
	cd web && npm audit
