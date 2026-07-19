.DEFAULT_GOAL := help

COMPOSE            = docker compose
COMPOSE_LANGFUSE   = docker compose -f docker-compose.yml -f docker-compose.langfuse.yml
COMPOSE_HERMES     = docker compose -f docker-compose.yml -f docker-compose.hermes-dev.yml
COMPOSE_EVERYTHING = docker compose -f docker-compose.yml -f docker-compose.langfuse.yml -f docker-compose.hermes-dev.yml

.PHONY: help
help: ## Show this help
	@echo "finance-mcp — available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.env: ## Create .env from .env.example if it doesn't exist yet
	cp -n .env.example .env
	@echo "Created .env — review it (Langfuse/Hermes keys, notifier webhook, etc.) before running the optional profiles."

.PHONY: up
up: .env ## Start the core app (web + postgres + scheduler + backup) — http://localhost:8000
	$(COMPOSE) up -d --build

.PHONY: langfuse
langfuse: .env ## Start the optional Langfuse + LiteLLM profile — http://localhost:3000
	$(COMPOSE_LANGFUSE) --profile langfuse up -d

.PHONY: ollama
ollama: .env ## Start Ollama and pull the free local model (qwen2.5:7b-instruct)
	$(COMPOSE_HERMES) --profile hermes-dev up -d ollama
	$(COMPOSE_HERMES) --profile hermes-dev run --rm ollama-pull

.PHONY: all
all: up langfuse ollama ## Start EVERYTHING at once: core app + Langfuse/LiteLLM + Ollama (model pulled)
	@echo ""
	@echo "Up: app http://localhost:8000  |  Langfuse http://localhost:3000  |  LiteLLM http://localhost:4000"
	@echo "Run 'make chat' to open an interactive Hermes session against it all."
	@echo "First time ever on a fresh docker/hermes/data volume: Hermes writes its own"
	@echo "default config.yaml on that very first launch, so 'make chat' won't have our"
	@echo "Ollama/finance-mcp overrides applied yet — exit (/exit) and run 'make chat'"
	@echo "again; every run after that patches the config automatically."

.PHONY: hermes-config
hermes-config: ## Patch docker/hermes/data/config.yaml with the Ollama model + finance-mcp server
	@if [ ! -f docker/hermes/data/config.yaml ]; then \
		echo "No Hermes config yet — run 'make chat' once first (it bootstraps one on"; \
		echo "startup even if you exit immediately), then run this again."; \
		exit 1; \
	fi
	uv run python3 scripts/patch_hermes_config.py

.PHONY: chat
chat: ## Open an interactive Hermes chat session (run `make ollama` first, or `make all`)
	@if [ -f docker/hermes/data/config.yaml ]; then $(MAKE) hermes-config; fi
	$(COMPOSE_HERMES) --profile hermes-dev run --rm hermes hermes

.PHONY: ps
ps: ## Show status of every service across all profiles
	$(COMPOSE_EVERYTHING) --profile langfuse --profile hermes-dev ps

.PHONY: logs
logs: ## Tail logs for the core app services
	$(COMPOSE) logs -f web scheduler

.PHONY: down
down: ## Stop the core app (keeps data volumes)
	$(COMPOSE) down

.PHONY: down-all
down-all: ## Stop EVERYTHING (core + Langfuse + Hermes/Ollama) and delete all volumes/data
	$(COMPOSE_EVERYTHING) --profile langfuse --profile hermes-dev down -v

.PHONY: restore-drill
restore-drill: ## Verify the most recent backup restores cleanly (see scripts/restore.sh)
	@latest=$$(ls -t docker/backups/*.sql.gz 2>/dev/null | head -1); \
	if [ -z "$$latest" ]; then echo "No backups found in docker/backups/ yet — let 'make up' run a bit first."; exit 1; fi; \
	echo "Restoring $$latest ..."; \
	./scripts/restore.sh "$$latest"
