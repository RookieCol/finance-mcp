# 0004 — One `core/` layer shared by chat and UI

**Status:** Accepted · **Date:** 2026-07-18

## Context

Transactions enter through two doors: MCP tools (chat) and web forms. If each door had its own validation and persistence, the rules would drift — one door accepting what the other rejects, or worse, writing different shapes to the same table.

## Decision

All domain logic lives in `core/` (validation, repository, reporting, projections, alerts, fx). `mcp_server/` and `web/` are thin adapters: they parse their transport's input, call the same functions, and format the result. Neither contains business rules.

## Consequences

A transaction created by chat and one typed into a form are governed by identical rules *by construction* — there is one implementation to test, and the integration suite proves the shared path (an MCP-created row is visible in the UI with no special-casing). The commitment: new capabilities (revenue, metrics) land in `core/` first; adapters stay thin. Trade-off accepted: adapters occasionally feel like boilerplate, which is the cost of never having two sources of truth.
