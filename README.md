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
| Containers | Docker, Docker Compose (profiles for `langfuse` and `hermes-dev`) |

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

Docker Compose and a working database are not wired up yet (Stages 2 and 10) — this README's run instructions are updated as each stage lands. What already works, today:

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

Registering this server with a real Hermes install, and the local `hermes-dev` compose profile for testing the live chat integration without Telegram/Slack, are documented once Stage 11 lands.

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
- [x] Stage 8 — Observability — structured logging, tracing, `/metrics` (done as part of Stages 3/6). Self-hosted Langfuse + LiteLLM (agent tracing, LLM cost/budget governance) is **deprioritized/optional** — not required to run this repo, see "Deferred / optional" below.
- [x] Stage 9 — Testing & CI
- [ ] Stage 10 — Containerization & run story (incl. backups/restore)
- Stage 11 — Hermes dev container & integration: **deprioritized/optional**, see below.

**Deferred / optional** (not required to build or run this repo; documented as future follow-ups):
- Self-hosted Langfuse + LiteLLM proxy for agent-level tracing and LLM cost/budget governance.
- A `hermes-dev` Docker Compose profile for testing the live Hermes chat integration locally. The MCP tool surface is fully tested independently (`tests/integration/test_mcp_tools.py`) and the registration steps for a real Hermes install are documented below — only the local dev-container convenience is deferred.

## License

MIT — see [LICENSE](LICENSE).
