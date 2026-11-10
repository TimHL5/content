# Everything runs in containers: the host only needs Docker.
COMPOSE := docker compose
API     := $(COMPOSE) run --rm api
WEB     := $(COMPOSE) run --rm web

.PHONY: dev down test lint format migrate types fixtures eval lock

.env:
	cp .env.example .env

dev: .env ## all services with hot reload
	$(COMPOSE) up --build

down: ## stop services (add ARGS=-v to wipe volumes)
	$(COMPOSE) down $(ARGS)

test: .env ## pytest + vitest
	$(API) pytest
	$(WEB) pnpm -r test

lint: .env ## ruff, mypy, eslint, tsc
	$(API) sh -c "ruff check . && ruff format --check . && mypy"
	$(WEB) sh -c "pnpm --filter web lint && pnpm --filter web typecheck"

format: .env
	$(API) sh -c "ruff check --fix . && ruff format ."

migrate: .env ## alembic upgrade head
	$(API) alembic upgrade head

types: .env ## pydantic -> JSON Schema -> TS (packages/schemas/generated)
	$(API) python -m scripts.export_schemas
	$(WEB) pnpm --filter @stylecut/schemas generate

fixtures: .env ## synthetic test clips via ffmpeg lavfi
	$(API) python -m scripts.make_fixtures

eval: ## analysis over eval/ clips (lands in Phase 2)
	@echo "make eval is implemented in Phase 2 (needs the analysis pipeline)."

lock: ## refresh uv.lock and pnpm-lock.yaml
	$(API) uv lock
	$(WEB) pnpm install --no-frozen-lockfile
