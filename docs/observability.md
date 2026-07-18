# Observability

What this service emits, how to look at it locally, and how the optional Langfuse profile fits in.

## Structured logging

Every entry point (`mcp_server/`, `web/`, `scheduler/`) uses `core/logging.py`: `structlog` configured for JSON output, with `correlation_id()` binding one ID per request/tool-call/scheduler-run to every log line emitted within that scope — nested calls into `core/` inherit it automatically via `structlog.contextvars`, no explicit passing required.

Locally: logs go to stdout as JSON — `docker compose logs -f web` / `scheduler` / (MCP server: stdout when run directly, since it's a stdio process).

## Tracing

`core/tracing.py` wraps every `core/` operation and MCP tool call in an OpenTelemetry span (`traced_operation(...)`), tagged with the same correlation ID as the logs. Two exporters:

- **Console** (always on): spans print to stdout, visible in `docker compose logs`.
- **OTLP** (opt-in): set `OTEL_EXPORTER_OTLP_ENDPOINT` (and `OTEL_EXPORTER_OTLP_HEADERS` for auth) to also export to a real collector — this is how the Langfuse profile below receives traces.

## Metrics

`GET /metrics` on the web UI serves Prometheus exposition (`prometheus-client`): request latency/count (via FastAPI), plus whatever custom counters are added over time. Inspect with `curl http://localhost:8000/metrics/` or point a local Prometheus at it.

## Health

`GET /healthz` checks DB connectivity and returns `{"status": "ok"|"error", ...}`. The scheduler doesn't currently expose an HTTP health endpoint (it's not a request-driven process) — its liveness is visible via `docker compose ps` and its structured log lines (`scheduler.starting`, `scheduler.alert_check_run`, `scheduler.digest_run`) on each cron tick.

## Optional: self-hosted Langfuse + LiteLLM

```bash
cp .env.example .env   # fill in LANGFUSE_* / LITELLM_* / OPENROUTER_API_KEY
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml --profile langfuse up -d
```

Brings up Langfuse's own stack (web, worker, ClickHouse, MinIO, Redis, a dedicated Postgres — adapted from Langfuse's official `docker-compose.yml`, see comments in `docker-compose.langfuse.yml` for what changed and why) plus a LiteLLM proxy.

- **Agent-execution traces**: with `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:3000/api/public/otel/v1/traces` and `OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <base64 of public_key:secret_key>,x-langfuse-ingestion-version=4"` set on the `web`/`scheduler`/MCP server processes, every `core/` operation's trace lands in the Langfuse UI (`http://localhost:3000`) — the "what did the agent actually do, and when" view: which MCP tool ran, how long it took, whether it hit the clarification/elicitation path.
- **LLM cost/budget governance**: point Hermes' LLM provider at the LiteLLM proxy (`http://localhost:4000`, using `LITELLM_MASTER_KEY` as the API key) instead of the provider directly. `docker/litellm/config.yaml` sets a hard monthly budget (`LITELLM_BUDGET_USD_MONTHLY`) at both the model and proxy level, and reports every call to Langfuse as a callback — so token usage and cost per conversation show up in the same Langfuse UI, and a runaway loop hits a budget error at the proxy instead of an unbounded bill.

Base64-encode the auth header with:

```bash
echo -n "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" | base64
```

This profile is genuinely optional — the service runs fully without it (console tracing + `/metrics` cover local development), and it's disabled by default in `docker compose up` since none of its services declare a bare (profile-less) entry.
