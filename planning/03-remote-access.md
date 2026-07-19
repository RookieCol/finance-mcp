# Phase 03 — Remote access & channel strategy

**Status: planned · Hard prerequisite ordering: auth before any remote exposure.**

## Channel roles

The MCP-first architecture means one tool surface serves every client. The strategy is roles per channel, not one channel to rule them all:

| Channel | Role | Rationale |
|---|---|---|
| **Hermes** (Telegram/Slack/CLI) | **Capture** — record transactions on the go, check cartera, mark invoices paid | Already wired (`docker-compose.hermes-dev.yml`); MCP elicitation handles missing fields; its lightweight model is sufficient for structured capture, **not** for financial analysis |
| **Claude** (Code / Desktop / claude.ai) | **Analysis** — "why did burn rise?", scenario modeling, maintaining this codebase | Full-strength reasoning over the same tools |
| **Web UI** | **Review** — dashboards, cartera aging, approvals (Phase 02 queue) | Human-verification surface |

## 03.1 — Web UI auth *(prerequisite for everything below)*

The UI currently has no auth (README: localhost/private-network only). Minimum viable for single-user:

- Session-cookie login with a single bcrypt-hashed password from env (`UI_PASSWORD_HASH`); `itsdangerous`-signed cookie; all routes behind the check except `/healthz` + `/metrics`.
- Rate-limit the login route; secure/HttpOnly/SameSite cookie flags.
- Out of scope: multi-user, roles, OAuth — YAGNI at one user.

## 03.2 — MCP over streamable HTTP

The MCP server is stdio-only: clients must live on the same machine. Exposing it over streamable HTTP enables claude.ai custom connectors and a remote Hermes.

- FastMCP already supports the transport: `mcp.run(transport="streamable-http")` behind a new entrypoint (`caudal-mcp-http`), mounted on its own port or path.
- **Auth:** static bearer token from env checked in middleware; TLS terminated by a reverse proxy (Caddy/Traefik) — never exposed bare.
- **Scope tightening:** the HTTP surface can expose a reduced tool set (e.g. capture + read tools, no `update_transaction`) if the remote channel warrants less trust.
- Elicitation behavior must be re-verified over HTTP transport (it was designed against stdio).

## 03.3 — Hermes production wiring

Once 03.1/03.2 land: point real Hermes (Telegram) at the HTTP endpoint, enable its cron for proactive delivery (*"Monday 9am: call `get_digest`, post to Telegram"*), replacing the scheduler's webhook fallback as primary delivery — the scheduler remains as the no-Hermes fallback, as designed.

## Risks

- Exposing an unauthenticated financial system is the single biggest risk in this roadmap — hence the hard ordering.
- Token in env is single-user pragmatism; rotate on any suspicion, and revisit if a second human ever gets access.
