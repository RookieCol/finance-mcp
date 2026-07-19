# Architecture Decision Records

Short records (≤1 page) of the decisions that shape this system — the *why* that a diff can't show. The *what* per release lives in [`CHANGELOG.md`](../../CHANGELOG.md).

A decision earns an ADR when it alters the data model, an invariant, or the architecture — or when it would be expensive to reverse.

| # | Decision | Status |
|---|---|---|
| [0001](0001-mcp-first-over-a2a.md) | MCP-first integration, not A2A | Accepted |
| [0002](0002-integer-minor-units.md) | Money as integer minor units, never floats | Accepted |
| [0003](0003-audit-log-in-transaction.md) | Audit log written in the same transaction as every write | Accepted |
| [0004](0004-single-core-layer.md) | One `core/` layer shared by chat and UI | Accepted |
| [0005](0005-single-currency-trm-at-the-door.md) | Single-currency ledger: USD→COP at the daily TRM at record time | Accepted |
| [0006](0006-deterministic-engine-narrating-ai.md) | Deterministic engine computes; AI narrates, extracts, drafts | Accepted |
| [0007](0007-server-rendered-ui-no-build-step.md) | Server-rendered UI with no build step | Accepted |
| [0008](0008-recurring-base-latest-month.md) | Recurring forecast base = each category's latest month | Accepted |

Template: [`template.md`](template.md).
