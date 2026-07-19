# finance-mcp

Internal finance system for a bootstrapped SaaS: an [MCP](https://modelcontextprotocol.io) server that turns a chat conversation into structured income/expense records, plus an internal web UI, a proactive projections/alerting engine, and the observability and CI scaffolding expected of a production service — not a personal script.

## What this is

The primary interaction surface is chat: a message like *"pagué 50 dólares a AWS ayer"* or a forwarded receipt should end up as a structured, validated transaction in Postgres, without the user filling out a form. The chat side is handled by [Hermes Agent](https://github.com/NousResearch/hermes-agent), an existing personal AI agent the user already runs on Telegram/Slack — this repository does not build a chatbot, it builds the **tool Hermes calls**.

Three things this project is *not*:

- Not a second LLM. Hermes' own model already reads free text and image attachments; this server is a thin, deterministic **validation + storage + analytics layer** behind MCP tools. No duplicated extraction logic, no second inference cost.
- Not reactive-only. Beyond recording what already happened, the system computes forward-looking **projections** (cash-flow forecast, runway, MRR trend) and runs a **proactive alert engine** (budget overruns, spend spikes, missing recurring income) on a schedule — pushed to chat, not waited on.
- Not a toy. Money is stored as integer minor units (never floats), every write is idempotent and audit-logged, migrations are versioned, and the service ships with CI, structured logging, tracing, metrics, backups, and a tested restore path.

Domain background (SaaS accounting fundamentals, the category taxonomy, and the metric formulas this project implements) lives in [`finanzas-saas.md`](../finanzas-saas.md), a research document produced before this build started.

## Why MCP, not A2A

Hermes has no native support for Google's Agent2Agent (A2A) protocol, but it does have first-class MCP client support — external servers are registered with `hermes mcp add NAME --command "..."` (or a `mcp_servers:` block in `config.yaml`), with per-server tool allowlisting. MCP is also the protocol Hermes' own LLM already speaks fluently for tool calls, and it has a formal **elicitation** capability (`elicitation/create`) that lets a tool call pause and ask the user a clarifying question mid-conversation — exactly the "don't guess, ask" behavior this project needs when a transaction description is ambiguous. Building an A2A server would mean implementing a protocol Hermes can't consume; MCP is the integration surface that actually exists.

## Architecture

```mermaid
flowchart LR
    subgraph Chat
        H[Hermes Agent<br/>Telegram / Slack / CLI]
    end

    subgraph finance-mcp
        M[MCP server<br/>stdio]
        C[core/<br/>validation · repository<br/>projections · alerts]
        S[scheduler<br/>proactive digests & alerts]
        W[Internal web UI<br/>FastAPI]
    end

    PG[(Postgres)]
    LF[Langfuse<br/>self-hosted, optional]

    H <--MCP tools--> M
    M --> C
    S --> C
    W --> C
    C --> PG
    M -. traces .-> LF
    W -. traces .-> LF
```

Both entry points — the MCP tools Hermes calls and the internal UI a human uses directly — go through the same `core/` validation and storage layer, so a transaction created by chat and one entered by hand are governed by identical rules, and every write is logged/traced identically regardless of source.

## Tech stack

| Concern | Choice |
|---|---|
| Language / packaging | Python, [`uv`](https://github.com/astral-sh/uv) (matches Hermes' own tooling) |
| MCP server | official `mcp` Python SDK, stdio transport |
| Web UI | FastAPI + Jinja2/HTMX (server-rendered, no separate frontend build) |
| Database | Postgres, SQLAlchemy, Alembic migrations |
| Scheduler | APScheduler (fallback path when Hermes cron isn't available) |
| Logging / tracing / metrics | `structlog` (JSON), OpenTelemetry, `prometheus-client` |
| Agent observability & cost | [Langfuse](https://langfuse.com) (self-hosted) + LiteLLM proxy for budget governance, optional compose profile |
| Lint / types | `ruff`, `mypy` |
| Security | `bandit`, `pip-audit`, `gitleaks` |
| Tests | `pytest`, `testcontainers` (real Postgres in CI, no DB mocking), `hypothesis` (property-based tests on money math) |
| CI | GitHub Actions |
| Containers | Docker, Docker Compose |

## Repository layout

```
finance_mcp/
  core/          # domain layer: repository, validation, reporting, projections, alert engine, logging/tracing
  mcp_server/    # MCP tool definitions (thin wrappers over core/)
  web/           # FastAPI app + templates for the internal UI (thin wrappers over core/)
  scheduler/     # proactive digest/alert runner (no-Hermes fallback delivery)
  config.py      # environment-driven settings, fail-fast on missing/invalid values
tests/
alembic/         # versioned database migrations
docker/          # compose profile support files (hermes-dev config, etc.)
.github/workflows/
Dockerfile
docker-compose.yml
```

## How to run

**Makefile (simplest path — everything at once):**

```bash
make all     # core app + Langfuse/LiteLLM + Ollama (model pulled) — all in one shot
make chat    # then: open an interactive Hermes chat session against it all
make help    # see every target (up / langfuse / ollama / ps / logs / down / down-all / restore-drill)
```

`make all` brings up the core app (http://localhost:8000), the Langfuse UI (http://localhost:3000) + LiteLLM, and pulls the free local `qwen2.5:3b-instruct` model into Ollama — everything except the interactive Hermes chat itself, which `make chat` opens separately (it can't run "in the background" as part of a batch `up`). `make down-all` tears down every profile and deletes all volumes.

> **Docker Desktop memory**: this whole stack (app + Langfuse's 6 services + Ollama) plus anything else you have running shares Docker Desktop's VM memory limit (7.75GB by default on macOS). If a model fails to load with `"llama runner process has terminated"` (an empty error — the process was silently OOM-killed, not a config bug), either stop other unrelated containers (`docker stop $(docker ps --format '{{.Names}}' | grep -v finance-mcp)`) or raise the limit in Docker Desktop → Settings → Resources → Memory.

**Docker Compose directly (equivalent to `make up`, just the core app):**

```bash
cp .env.example .env   # optional: set NOTIFIER_WEBHOOK_URL for real alert/digest delivery
docker compose up -d
curl http://localhost:8000/healthz   # {"status":"ok"}
```

Brings up Postgres, runs migrations (`migrate`, a one-shot service), then the web UI (`web`, `:8000`), the proactive `scheduler`, and a `backup` service that `pg_dump`s the database on startup and then daily, pruning dumps older than `RETENTION_DAYS` (default 14) into `docker/backups/`. The MCP server isn't a standing compose service (it's a stdio process a client like Hermes launches on demand) — run it ad hoc with `docker compose run --rm web finance-mcp` or locally per below.

**Backup & restore drill** — a backup nobody has restored is unverified:

```bash
scripts/restore.sh docker/backups/finance-<timestamp>.sql.gz
```

Restores into whatever `PGHOST`/`PGPORT`/`PGUSER`/`PGDATABASE` are set to (defaults: `localhost`/`5432`/`finance`/`finance`) — point it at a throwaway database for a dry run, or the real one for actual disaster recovery. For production, copy `docker/backups/` offsite (3-2-1 rule) — this repo only handles the local dump/prune side.

**Plain local dev (no Docker):**

```bash
uv sync --all-groups
cp .env.example .env          # DATABASE_URL is required (a local Postgres, e.g. via docker run)
uv run ruff check .           # lint
uv run mypy src/finance_mcp   # type-check
uv run bandit -c pyproject.toml -r src/finance_mcp   # SAST
uv run pip-audit              # dependency vulnerabilities
uv run pytest --cov=finance_mcp --cov-report=term-missing   # tests + 85% coverage gate (real Postgres via testcontainers)
uv run pre-commit install     # wires the same checks into git hooks locally
```

CI (`.github/workflows/ci.yml`) runs the same steps on every push/PR, plus `gitleaks` secret scanning as a separate job — lint → format check → type-check → SAST → dependency audit → tests with a coverage gate (`fail_under = 85` in `pyproject.toml`).

The `finance-mcp`, `finance-web`, and `finance-scheduler` console scripts are all implemented (Stages 4, 6, 7 respectively) — run any of them directly once `DATABASE_URL` points at a real Postgres.

**Database schema** (Stage 2) is managed with Alembic against the SQLAlchemy models in `finance_mcp/core/models.py`:

```bash
export DATABASE_URL=postgresql+psycopg://finance:finance@localhost:5432/finance
uv run alembic upgrade head      # apply all migrations, incl. category taxonomy seed
uv run alembic downgrade base    # tear back down — verified to be a true inverse (tables + enum types)
```

Money is stored as integer minor units (`amount_minor`, e.g. cents) with an ISO 4217 currency code — never a float — per the fintech engineering practices linked below. Every transaction write is idempotent (`idempotency_key`) and soft-deleted (`deleted_at`), with a parallel append-only `audit_log`.

**Core layer** (`finance_mcp/core/`, Stage 3) is the single implementation both the MCP tools (Stage 4) and the internal UI (Stage 6) call into:

- `validation.py` — pure, no DB: turns raw chat/form input into a `ValidTransaction` or a list of `ValidationIssue`s (missing/invalid fields), which is exactly what Stage 5's clarification flow asks the user about.
- `repository.py` — CRUD, idempotent `create_transaction`, soft delete, and an audit-log entry written in the same transaction as every write.
- `reporting.py` — SQL aggregates (totals by category/month). Postgres `SUM()` over a `bigint` column returns `numeric` (Decimal) over the wire — caught by an integration test, fixed with an explicit cast back to `bigint` so callers only ever see `int`.
- `projections.py` — deterministic forecast/runway/growth math (no LLM), split into hand-verifiable pure functions and a DB-backed orchestrator. Historical trend data explicitly excludes recurring transactions to avoid double-counting them against the recurring base — also caught by an integration test.
- `alerts.py` — proactive rules (budget overrun, spend spike, runway threshold, missing recurring income), deduplicated via `AlertEvent.dedup_key` so a standing condition doesn't re-fire every run, and cleared once the condition resolves.
- `logging.py` / `tracing.py` — structured JSON logging with correlation IDs, and OpenTelemetry tracing (console exporter by default, OTLP when configured — Stage 8).

Registering this server with a real Hermes install is documented in "Connecting to Hermes" below; `docker-compose.hermes-dev.yml` (`--profile hermes-dev`) provides a local Hermes instance (with a free local LLM via Ollama by default) for testing the live chat integration without Telegram/Slack.

**MCP tools** (Stage 4, `finance_mcp/mcp_server/server.py`) — 8 tools, stdio transport, each a thin wrapper over `core/`:

| Tool | Purpose |
|---|---|
| `record_transaction` | Record income/expense. All fields accepted as optional at the schema level and validated internally. On a missing/invalid field, first tries `elicitation/create` to ask the client directly for just that field; if declined or the client doesn't support elicitation, falls back to a structured `clarification_needed` result — never a hard MCP error (see `tests/integration/test_mcp_tools.py` and `tests/unit/test_elicitation.py`). |
| `update_transaction` | Correct a field on an existing transaction. |
| `list_transactions` | Filtered listing by type/category/date range. |
| `get_totals` | Aggregate totals by category or month. |
| `list_categories` | The valid category taxonomy — call before `record_transaction`. |
| `get_projections` | Forecast, runway, MRR growth, with stated assumptions. |
| `get_digest` | Prose-ready summary for a scheduled push (Hermes cron or the internal scheduler, Stage 7). |
| `check_alerts` | Runs the proactive alert rules, returns newly-fired findings. |

Try it locally without Hermes: `uv run mcp dev src/finance_mcp/mcp_server/server.py` (MCP Inspector) or call tools directly against a running server via the official MCP Python client — see `tests/integration/test_mcp_tools.py` for exactly that pattern.

**Internal UI** (Stage 6, `finance_mcp/web/`) — FastAPI + server-rendered Jinja2 templates, no separate frontend build, running through the same `core/` validation and storage as the MCP tools:

```bash
uv run uvicorn finance_mcp.web.app:app --reload   # http://127.0.0.1:8000
```

| Route | Purpose |
|---|---|
| `GET /` | Dashboard: this month by category, a plain-HTML/CSS net-cash-flow bar chart (history + forecast, no JS dependency), open alerts, recent transactions. |
| `GET /transactions`, `/transactions/new`, `/transactions/{id}/edit`, `POST .../delete` | Filterable listing and manual CRUD, validated through `core.validation` — an invalid submission re-renders the form with field errors and writes nothing. |
| `GET /transactions/{id}/history` | Per-transaction audit trail from `audit_log`. |
| `GET /budgets`, `POST /budgets`, `POST /budgets/{id}/delete` | Manage the monthly limits the budget-overrun alert checks against. |
| `GET /alerts`, `POST /alerts/{id}/acknowledge` | Alert history and acknowledgement. |
| `GET /healthz` | DB connectivity check. |
| `GET /metrics` | Prometheus exposition. |

No auth in v1 — single-user, intended for localhost/private-network use; noted as a follow-up before any exposure beyond that.

**Proactive scheduler** (Stage 7, `finance_mcp/scheduler/`) — the internal fallback delivery path for when Hermes cron isn't set up:

```bash
uv run finance-scheduler
```

Runs `core.alerts.evaluate_alerts` daily and a weekly digest (`core.projections` + `core.reporting`), delivering via a pluggable notifier — a generic webhook POST (`NOTIFIER_WEBHOOK_URL`, works with Slack/Discord incoming webhooks) or, if unset, a log-only notifier so nothing is silently dropped. Alert delivery is idempotent: `core.alerts` dedupes by `AlertEvent.dedup_key`, so re-running the check doesn't re-send an already-open finding. The **primary** path, once Hermes is available, is Hermes cron calling the `get_digest`/`check_alerts` MCP tools directly and posting the result to chat — no code on this side, just a `hermes cron` recipe (documented below); this scheduler exists so alerts/digests work even without a Hermes install.

## Connecting to Hermes

On the machine where Hermes Agent actually runs (not required for this repo's own build/tests):

```bash
hermes mcp add finance --command "/app/.venv/bin/finance-mcp"
```

or the equivalent `mcp_servers:` block in Hermes' `config.yaml`:

```yaml
mcp_servers:
  finance:
    command: "/app/.venv/bin/finance-mcp"   # or `finance-mcp` if installed on PATH outside Docker
    env:
      DATABASE_URL: "postgresql+psycopg://finance:finance@<host>:5432/finance"
    tools:
      include:
        [record_transaction, update_transaction, list_transactions, get_totals,
         list_categories, get_projections, get_digest, check_alerts]
```

Then, for proactive digests/alerts via Hermes' own cron scheduler instead of (or in addition to) the internal `finance-scheduler` (Stage 7):

- *"Every Monday at 9am, call the finance get_digest tool and post the result to Telegram."*
- *"Every day at 8am, call the finance check_alerts tool and post any new alerts to Telegram."*

No changes to Hermes' own code are needed either way — this is pure configuration on top of Hermes' existing MCP client and cron scheduler.

## Status

Build is executed stage-by-stage, each stage landing as its own commit(s) on `main` — this checklist is the source of truth for what currently exists versus what's still planned.

- [x] Stage 0 — Repository bootstrap
- [x] Stage 1 — Project scaffolding & tooling
- [x] Stage 2 — Data model (Postgres + Alembic)
- [x] Stage 3 — Shared core layer
- [x] Stage 4 — MCP tools
- [x] Stage 5 — Clarification / elicitation flow
- [x] Stage 6 — Internal UI
- [x] Stage 7 — Proactive scheduler
- [x] Stage 8 — Observability — structured logging, tracing, `/metrics`, plus the optional self-hosted Langfuse + LiteLLM profile (see below).
- [x] Stage 9 — Testing & CI
- [x] Stage 10 — Containerization & run story (incl. backups/restore)
- [x] Stage 11 — Hermes dev container & integration (`docker-compose.hermes-dev.yml`, see below)

**Optional profiles** (not required for the core `docker compose up` — see `docs/observability.md` for the Langfuse/LiteLLM piece):

- **`docker-compose.langfuse.yml`** (`--profile langfuse`) — self-hosted [Langfuse](https://langfuse.com) (agent-execution tracing via this repo's own OTLP export) + a [LiteLLM](https://www.litellm.ai) proxy in front of Hermes' LLM provider for cost/budget governance (hard monthly cap, logged to Langfuse). Adapted from Langfuse's own official `docker-compose.yml` — its `postgres` service is renamed `langfuse-postgres` and moved off port 5432 to avoid colliding with this repo's own Postgres. **Verified end-to-end** via `make all`: all 36 ClickHouse migrations applied and the Langfuse UI served 200 at `:3000`. One real bug was caught and fixed this way — the adaptation had dropped `CLICKHOUSE_CLUSTER_ENABLED`, which defaults Langfuse to `ReplicatedMergeTree` table engines that need a Zookeeper ensemble a single-node ClickHouse doesn't have, crash-looping `langfuse-web`; `config` validation alone (no port/name collisions) hadn't caught it since nothing about the YAML shape was wrong.
- **`docker-compose.hermes-dev.yml`** (`--profile hermes-dev`) — a local Hermes Agent instance (official `nousresearch/hermes-agent` image) for testing the live chat → MCP integration without Telegram/Slack. Defaults to a **free, fully local LLM** via an `ollama` service running `qwen2.5:3b-instruct` (tool-calling capable, ~1.9GB), tagged as `qwen2.5-3b-64k` (`docker/hermes/Modelfile`: `PARAMETER num_ctx 65536`) since Ollama serves it at a 32K context window by default and Hermes refuses anything under 64K for its tool-calling working memory; an `ollama-pull` one-shot service pulls the base weights and creates the tagged variant. 3B rather than 7B specifically because 7B's weights (~4.5GB) plus its KV cache at 64K context (~3.7GB) don't fit Docker Desktop's default 7.75GB VM alongside the rest of this stack — confirmed by reproducing the crash (`"llama runner process has terminated"`, an empty error from a silent OOM-kill) with 7B even after freeing every other container's memory, while 3B answers real chat completions cleanly in the same environment. An OpenRouter (cloud) alternative — and how to bump back to 7B if you've raised Docker's memory limit — is documented in `docker/hermes/config.yaml` / `docker/hermes/Modelfile`'s comments. Since `docker/hermes/data/` is Hermes' own persistent volume (gitignored) and Hermes writes its own default `config.yaml` there on first launch, `scripts/patch_hermes_config.py` merges in the `model`/`mcp_servers`/`agent.reasoning_effort` overrides on every `make chat` run — three real bugs surfaced this way, each caught by actually driving `make chat` end-to-end rather than by config review alone: (1) the config file was never being read at all (Hermes' own generated default silently took over, `mcp_servers.finance` was never registered); (2) the raised-context model tag was missing, so Hermes rejected the 32K default with "below the minimum 64,000 required"; (3) Hermes' default `reasoning_effort: medium` sends a "thinking" request param that Ollama rejects for a plain instruct model with HTTP 400.

## License

MIT — see [LICENSE](LICENSE).
