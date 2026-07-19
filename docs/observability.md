# Observability

What this service emits, how to look at it locally, and how the optional Langfuse Cloud piece fits in.

## Structured logging

Every entry point (`mcp_server/`, `web/`, `scheduler/`) uses `core/logging.py`: `structlog` configured for JSON output, with `correlation_id()` binding one ID per request/tool-call/scheduler-run to every log line emitted within that scope — nested calls into `core/` inherit it automatically via `structlog.contextvars`, no explicit passing required.

Locally: logs go to stdout as JSON — `docker compose logs -f web` / `scheduler` / (MCP server: stdout when run directly, since it's a stdio process).

## Tracing

`core/tracing.py` wraps every `core/` operation and MCP tool call in an OpenTelemetry span (`traced_operation(...)`), tagged with the same correlation ID as the logs. Two exporters:

- **Console** (always on): spans print to stdout, visible in `docker compose logs`.
- **OTLP** (opt-in): set `OTEL_EXPORTER_OTLP_ENDPOINT` (and `OTEL_EXPORTER_OTLP_HEADERS` for auth) to also export to a real collector — this is how the Langfuse Cloud piece below receives this service's own traces.

## Metrics

`GET /metrics` on the web UI serves Prometheus exposition (`prometheus-client`): request latency/count (via FastAPI), plus whatever custom counters are added over time. Inspect with `curl http://localhost:8000/metrics/` or point a local Prometheus at it.

## Health

`GET /healthz` checks DB connectivity and returns `{"status": "ok"|"error", ...}`. The scheduler doesn't currently expose an HTTP health endpoint (it's not a request-driven process) — its liveness is visible via `docker compose ps` and its structured log lines (`scheduler.starting`, `scheduler.alert_check_run`, `scheduler.digest_run`) on each cron tick.

## Optional: Langfuse Cloud (agent tracing + LLM cost)

No local infrastructure — a self-hosted Langfuse stack (ClickHouse, MinIO, Redis, its own Postgres, web, worker) and a LiteLLM proxy were tried during development and dropped: the self-hosted stack competed for memory with everything else on Docker Desktop's default VM size, and OpenRouter turns out to cover the same ground natively, upstream, with less to maintain.

1. **Create a free Langfuse Cloud project** at [cloud.langfuse.com](https://cloud.langfuse.com) and grab its public/secret API keys.
2. **This service's own traces** (MCP tool executions, `core/` operations): set in `.env`
   ```bash
   OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel/v1/traces
   OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64 of public_key:secret_key>,x-langfuse-ingestion-version=4
   ```
   Base64-encode the auth header with:
   ```bash
   echo -n "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" | base64
   ```
3. **Hermes' own LLM calls** (tokens, cost, latency — a separate stream from this service's tool-execution traces): on the OpenRouter dashboard, enable **Usage Accounting** (so OpenRouter returns its own accurate per-call cost) and **Broadcast to Langfuse**, pointing at the same Langfuse Cloud project's keys. No proxy, no code on this side — OpenRouter sends the trace directly.
4. **Budget control**: set a per-API-key spending cap (with a daily/weekly/monthly reset) on the OpenRouter dashboard under API Keys. Requests are rejected *before* reaching the model provider once the cap is hit — enforced upstream at OpenRouter, not something this repo needs to implement or maintain.

This is genuinely optional — the service runs fully without it (console tracing + `/metrics` cover local development).
