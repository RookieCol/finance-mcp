# 0001 — MCP-first integration, not A2A

**Status:** Accepted · **Date:** 2026-07-18

## Context

The primary interaction surface is chat: a message like *"pagué 50 dólares a AWS ayer"* must become a validated transaction. The chat runtime (Hermes Agent) needed a protocol to call this system's capabilities, and ambiguous input ("paid AWS yesterday" — how much?) needed a way to ask back instead of guessing.

## Decision

Expose all capabilities as an MCP server. Rejected: Google A2A — Hermes has no A2A support, and A2A has no equivalent of MCP **elicitation** (`elicitation/create`), which lets a tool call pause mid-conversation to request exactly the missing field.

## Consequences

One tool surface serves every MCP client — Hermes, Claude Code/Desktop, and anything future — with zero per-client code. Elicitation gives "don't guess, ask" for free. The commitment: capabilities land as MCP tools first, and the web UI renders the same `core/` layer rather than growing its own logic. Trade-off accepted: stdio transport limits clients to the same machine until a streamable-HTTP endpoint ships (planned, `planning/03-remote-access.md`).
