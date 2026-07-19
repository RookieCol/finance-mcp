# 0003 — Audit log written in the same transaction as every write

**Status:** Accepted · **Date:** 2026-07-18

## Context

Financial records get corrected — amounts fixed, dates moved, rows soft-deleted — by two different actors (chat and UI) plus a scheduler. "What changed, when, by which actor" must be answerable later, and an audit trail that can miss entries is worse than none: it creates false confidence.

## Decision

Every write in `core/repository.py` appends an `audit_log` row (entity, action, changed-field snapshots, actor) **inside the same database transaction** as the write itself. Audit is part of the write, not a best-effort side effect.

## Consequences

The ledger and its history can never disagree — a rollback takes both. Per-transaction history is served straight from this table. The commitment cuts deep: even data cleanups must go through repository functions (or the UI/MCP) rather than raw SQL or data migrations, because a bypass would create the one thing the invariant exists to prevent — an unexplained change. This is why the `ga → payroll` recategorization in Phase 01 is a manual step, not a migration.
