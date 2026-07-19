# Planning

Roadmap for evolving finance-mcp from a cash ledger into the operating system of the business. Each phase is independently shippable; order reflects value, not convenience.

| Phase | Scope | Status |
|---|---|---|
| [01 — Revenue](01-revenue.md) | Clients, plans, subscriptions, invoices/AR (cartera), payroll category, real MRR | **In progress** |
| [02 — AI & automation](02-ai-automation.md) | Narrated weekly digest, email invoice ingest with review queue, alert wiring + LLM explanations, assisted recurring registration, collections drafts | Planned |
| [03 — Remote access](03-remote-access.md) | Web UI auth, MCP over streamable HTTP, channel roles (Hermes = capture, Claude = analysis) | Planned |

## Principles

1. **Deterministic engine, narrating AI.** Every number (MRR, runway, aging) is computed by tested SQL/Python. LLMs explain, extract, and draft — they never write to the ledger without a human approval step.
2. **One tool surface, N clients.** All capabilities land as MCP tools first; the web UI renders the same `core/` layer. No embedded chatbot — Claude and Hermes *are* the chat interface.
3. **Cash basis, minor units, audited.** No deferred revenue / ASC 606 in scope. Money is integer minor units in COP (USD converts at the official TRM at the door, `core/fx.py`). Every write appends to `audit_log` in the same transaction — including anything automated.
4. **No payment-provider rebuild.** If billing moves to Stripe/Wompi, ingest from the provider; don't hand-model their domain.
