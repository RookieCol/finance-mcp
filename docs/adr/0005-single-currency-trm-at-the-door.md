# 0005 — Single-currency ledger: USD→COP at the daily TRM at record time

**Status:** Accepted · **Date:** 2026-07-19

## Context

The business operates in COP, but platform vendors (Vercel, Supabase, Resend, Cloudflare) charge in USD. The reporting and projection engines sum `amount_minor` across rows **without converting between currencies** — a USD row sitting next to COP rows would be added as if pesos, silently corrupting runway, MRR, and every forecast.

## Decision

Convert at the door: when a transaction is recorded in USD (web form or MCP tool), `core/fx.py` fetches the official TRM (Banco de la República, mirrored on datos.gov.co) for the transaction's `occurred_on` and stores the amount in COP. If the rate is unavailable, the transaction is **rejected with a clear error** — never stored in USD, never converted at a stale or guessed rate. The original USD amount and rate are preserved in the description for traceability. Rejected alternative: multi-currency aggregation (per-currency grouping everywhere) — heavy machinery for a business with one operating currency.

## Consequences

Aggregates are correct by construction; no caller needs to remember currency handling. Conversion uses the rate legally in effect on the payment date (TRM validity ranges cover weekends/holidays). The commitment: conversion happens only at creation — edits never re-convert, so correcting a field can't mutate an amount unexpectedly. Trade-off accepted: recording a USD expense requires network access to the TRM service, and failing closed means occasionally retrying instead of risking silent corruption.
