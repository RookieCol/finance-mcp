.DEFAULT_GOAL := help

COMPOSE        = docker compose
COMPOSE_HERMES = docker compose -f docker-compose.yml -f docker-compose.hermes-dev.yml

FINANCE_TOOLS = finance:record_transaction finance:update_transaction finance:list_transactions \
                finance:get_totals finance:list_categories finance:get_projections \
                finance:get_digest finance:check_alerts

.PHONY: help
help: ## Show this help
	@echo "finance-mcp — available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.env: ## Create .env from .env.example if it doesn't exist yet
	cp -n .env.example .env
	@echo "Created .env — set OPENROUTER_API_KEY before running the hermes-dev profile."

.PHONY: up
up: .env ## Start the core app (web + postgres + scheduler + backup) — http://localhost:8000
	$(COMPOSE) up -d --build

.PHONY: hermes-warm
hermes-warm: .env ## Pre-build finance-mcp's venv in a persistent volume (required before `make chat` works)
	$(COMPOSE_HERMES) --profile hermes-dev run --rm hermes-mcp-warm

.PHONY: all
all: up hermes-warm ## Start the core app + pre-build the finance-mcp venv for Hermes
	@echo ""
	@echo "Up: app http://localhost:8000"
	@echo "Set OPENROUTER_API_KEY in .env, then run 'make chat' to open an interactive"
	@echo "Hermes session (routes directly to OpenRouter — see docker/hermes/config.yaml)."
	@echo ""
	@echo "First time ever on a fresh docker/hermes/data volume: Hermes writes its own"
	@echo "default config.yaml on that very first launch, so 'make chat' won't have our"
	@echo "overrides applied yet — exit (/exit) and run 'make chat' again; every run"
	@echo "after that patches the config and enables the finance tools automatically."

.PHONY: hermes-config
hermes-config: ## Patch docker/hermes/data/config.yaml and enable the finance MCP tools
	@if [ ! -f docker/hermes/data/config.yaml ]; then \
		echo "No Hermes config yet — run 'make chat' once first (it bootstraps one on"; \
		echo "startup even if you exit immediately), then run this again."; \
		exit 1; \
	fi
	uv run python3 scripts/patch_hermes_config.py
	@# MCP tool registration (mcp_servers: in config.yaml) is separate from a
	@# platform's enabled-tools state (Hermes' own state.db) — a freshly
	@# registered MCP server's tools default to *not* selected for the cli
	@# platform, so the model never sees them even though `hermes mcp list`
	@# shows the server connected. This is idempotent (re-enabling an
	@# already-enabled tool is a no-op) and safe to run on every `make chat`.
	$(COMPOSE_HERMES) --profile hermes-dev run --rm --entrypoint hermes hermes tools enable $(FINANCE_TOOLS) --platform cli

.PHONY: chat
chat: hermes-warm ## Open an interactive Hermes chat session (set OPENROUTER_API_KEY in .env first, or run `make all`)
	@if [ -f docker/hermes/data/config.yaml ]; then $(MAKE) hermes-config; fi
	$(COMPOSE_HERMES) --profile hermes-dev run --rm hermes hermes

.PHONY: ps
ps: ## Show status of every service across all profiles
	$(COMPOSE_HERMES) --profile hermes-dev ps

.PHONY: logs
logs: ## Tail logs for the core app services
	$(COMPOSE) logs -f web scheduler

.PHONY: down
down: ## Stop the core app (keeps data volumes)
	$(COMPOSE) down

.PHONY: down-all
down-all: ## Stop EVERYTHING (core + Hermes) and delete all volumes/data
	$(COMPOSE_HERMES) --profile hermes-dev down -v

.PHONY: restore-drill
restore-drill: ## Verify the most recent backup restores cleanly (see scripts/restore.sh)
	@latest=$$(ls -t docker/backups/*.sql.gz 2>/dev/null | head -1); \
	if [ -z "$$latest" ]; then echo "No backups found in docker/backups/ yet — let 'make up' run a bit first."; exit 1; fi; \
	echo "Restoring $$latest ..."; \
	./scripts/restore.sh "$$latest"
