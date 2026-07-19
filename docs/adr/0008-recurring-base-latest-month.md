# 0008 — Recurring forecast base = each category's latest month

**Status:** Accepted · **Date:** 2026-07-19

## Context

The projection engine's recurring base was computed as the sum of **all** transactions ever flagged `is_recurring`. That works while each recurring stream has exactly one row (how the original tests were written) — but a real recurring stream leaves one payment row *per month*. After the second month of real data, Vercel June + Vercel July both counted, doubling that stream's "monthly" rate; every further month inflated the forecast a little more. Found with real data, two months in.

## Decision

The recurring base is, per `(category, currency)`, the recurring total of that category's **most recent month with recurring activity** (`reporting.latest_recurring_totals_by_category`) — i.e., the current monthly rate of each stream, summed. Rejected alternatives: trailing averages (wrong mid-month and slow to reflect rate changes) and per-stream identity via description matching (descriptions carry variable text like FX rates; no stable stream key exists without schema changes).

## Consequences

The base is self-correcting: when a new month's payment lands (including a rate change, like a prorated first salary), the forecast updates automatically with no data grooming. Known limitation, accepted knowingly: category granularity means a mid-month category with mixed streams reflects only months where its streams actually billed — Phase 01's subscriptions become the proper stream model for *income*, and this heuristic remains for expenses. Pinned by integration tests so the double-count can't regress.
