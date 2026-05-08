PYTHON ?= python
NPM ?= npm
TRIVY ?= trivy
K6 ?= k6

.PHONY: bootstrap verify api-install api-migrate api-dev api-test api-seed web-install web-dev up down lint security-scan audit-deps verify-all repo-secrets-check load-smoke load-gateway load-all e2e-install e2e e2e-headed prod-config-check worker validate-deployment validate-local verify-restore observability-files observability-check release-check pilot-rehearsal pilot-rehearsal-local

bootstrap:
	cd apps/api && $(PYTHON) -m pip install -e .[dev]
	cd apps/api && $(PYTHON) -m alembic upgrade head
	cd apps/api && $(PYTHON) -m app.db.seed
	cd apps/web && $(NPM) install

verify:
	cd apps/api && $(PYTHON) -m pytest app/tests -q
	cd apps/web && $(NPM) run build

api-install:
	cd apps/api && $(PYTHON) -m pip install -e .[dev]

api-migrate:
	cd apps/api && $(PYTHON) -m alembic upgrade head

api-dev:
	cd apps/api && $(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	cd apps/api && $(PYTHON) -m app.worker

api-test:
	cd apps/api && $(PYTHON) -m pytest app/tests -q

api-seed:
	cd apps/api && $(PYTHON) -m app.db.seed

web-install:
	cd apps/web && $(NPM) install

web-dev:
	cd apps/web && $(NPM) run dev

up:
	docker compose up --build

down:
	docker compose down --remove-orphans

lint:
	cd apps/api && $(PYTHON) -m ruff check app

security-scan:
	cd apps/api && $(PYTHON) -m bandit -c bandit.yaml -r app -iii
	@if command -v $(TRIVY) >/dev/null 2>&1; then \
		$(TRIVY) fs --config .trivy.yaml .; \
	else \
		echo "trivy not installed locally; run 'trivy fs --config .trivy.yaml .' or rely on GitHub Actions"; \
	fi

audit-deps:
	cd apps/api && $(PYTHON) -m pip_audit --progress-spinner off
	cd apps/web && $(NPM) audit --audit-level=high

verify-all: lint security-scan audit-deps
	cd apps/api && $(PYTHON) -m compileall app
	cd apps/api && $(PYTHON) -m pytest app/tests -q -o cache_dir=.tmp/pytest_cache
	cd apps/web && $(NPM) run build
	docker compose config
	$(PYTHON) scripts/check-no-live-secrets.py

repo-secrets-check:
	$(PYTHON) scripts/check-no-live-secrets.py

release-check:
	$(PYTHON) scripts/check-no-live-secrets.py
	$(PYTHON) scripts/validate-policy-pack.py --pack policy-packs/pilot-default/policies.json
	$(PYTHON) scripts/run-pilot-rehearsal.py --skip-live-api

prod-config-check:
	docker compose -f compose.prod.example.yml config

validate-deployment:
	$(PYTHON) scripts/validate-deployment.py

validate-local:
	AGENTGATE_VALIDATE_API_URL=http://127.0.0.1:8000 \
	AGENTGATE_VALIDATE_WEB_URL=http://127.0.0.1:3000 \
	AGENTGATE_VALIDATE_EMAIL=admin@demo.agentgate.example.com \
	AGENTGATE_VALIDATE_PASSWORD=AgentGate123! \
	AGENTGATE_VALIDATE_TENANT_SLUG=demo-agentgate \
	$(PYTHON) scripts/validate-deployment.py

verify-restore:
	$(PYTHON) scripts/validate-deployment.py

pilot-rehearsal:
	$(PYTHON) scripts/run-pilot-rehearsal.py

pilot-rehearsal-local:
	$(PYTHON) scripts/run-pilot-rehearsal.py --local

observability-files:
	@echo observability/prometheus/prometheus.yml
	@echo observability/prometheus/alert-rules.yml
	@echo observability/grafana/agentgate-overview-dashboard.json

observability-check:
	$(PYTHON) -c "import json, pathlib; files=[pathlib.Path('observability/prometheus/prometheus.yml'), pathlib.Path('observability/prometheus/alert-rules.yml'), pathlib.Path('observability/grafana/agentgate-overview-dashboard.json')]; missing=[str(p) for p in files if not p.exists()]; assert not missing, 'Missing files: ' + ', '.join(missing); json.load(files[-1].open(encoding='utf-8')); print('Observability starter files present and dashboard JSON is valid.')"

load-smoke:
	@if command -v $(K6) >/dev/null 2>&1; then \
		$(K6) run load-tests/k6/smoke.js; \
	else \
		echo "k6 not installed locally; run 'k6 run load-tests/k6/smoke.js' after installing k6 OSS"; \
	fi

load-gateway:
	@if command -v $(K6) >/dev/null 2>&1; then \
		AGENTGATE_K6_INCLUDE_APPROVAL_PATH=true $(K6) run load-tests/k6/gateway.js; \
	else \
		echo "k6 not installed locally; run 'AGENTGATE_K6_INCLUDE_APPROVAL_PATH=true k6 run load-tests/k6/gateway.js' after installing k6 OSS"; \
	fi

load-all:
	@if command -v $(K6) >/dev/null 2>&1; then \
		$(K6) run load-tests/k6/smoke.js && \
		$(K6) run load-tests/k6/auth.js && \
		AGENTGATE_K6_INCLUDE_APPROVAL_PATH=true $(K6) run load-tests/k6/gateway.js && \
		$(K6) run load-tests/k6/jobs.js && \
		$(K6) run load-tests/k6/integrity.js; \
	else \
		echo "k6 not installed locally; run the scripts in load-tests/k6/ manually after installing k6 OSS"; \
	fi

e2e-install:
	cd apps/web && $(NPM) run e2e:install

e2e:
	cd apps/web && $(NPM) run e2e

e2e-headed:
	cd apps/web && $(NPM) run e2e:headed
