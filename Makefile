PYTHON ?= python
NPM ?= npm

.PHONY: bootstrap verify api-install api-migrate api-dev api-test api-seed web-install web-dev up down lint

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
