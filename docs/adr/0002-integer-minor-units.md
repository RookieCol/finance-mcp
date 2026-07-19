# 0002 — Money as integer minor units, never floats

**Status:** Accepted · **Date:** 2026-07-18

## Context

This ledger is the source of truth for a real business's cash. IEEE-754 floats cannot represent most decimal amounts exactly; rounding drift in aggregates is silent and compounding.

## Decision

Every amount is stored and computed as an integer count of minor units (`amount_minor`, `BigInteger`). Input parsing goes through `Decimal` (`core/validation.py`); aggregation happens in SQL over integers (`core/reporting.py`); division appears only at display time.

## Consequences

Sums are exact by construction, and property-based tests (`tests/unit/test_money_properties.py`) can assert invariants that would be unprovable with floats. The commitment: no float ever touches an amount — including in new code like FX conversion (ADR-0005) and annual-plan normalization, which use `Decimal` with explicit rounding. Trade-off accepted: display formatting is a deliberate step (`/100` at the edge), and every developer touching money must know the convention.
