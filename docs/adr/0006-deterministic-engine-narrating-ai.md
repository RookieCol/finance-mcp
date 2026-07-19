# 0006 — Deterministic engine computes; AI narrates, extracts, drafts

**Status:** Accepted · **Date:** 2026-07-18

## Context

This system lives next to LLMs by design (Hermes for chat capture, Claude for analysis) and the roadmap adds more AI: narrated digests, invoice extraction from email, collections drafts. A misread amount or hallucinated figure that lands in a financial ledger corrupts it silently — the failure mode is not "wrong answer", it's "wrong books".

## Decision

Every number — MRR, runway, aging, forecasts, alert thresholds — is computed by tested SQL/Python (`core/projections.py` states it in its docstring: *deterministic forecasting engine — no LLM involved*). LLMs are confined to three verbs: **narrate** computed results, **extract** structure from unstructured input, and **draft** text for humans. Anything an LLM produces reaches the ledger only through the same validated, audited, idempotent write path as a human — and automated extraction additionally lands in a review queue, never directly in `transactions`.

## Consequences

Financial figures are reproducible and unit-testable; AI failures degrade to "no narration" or "nothing to review", never to wrong numbers. The commitment shapes the roadmap (`planning/02-ai-automation.md`): the email-ingest pipeline gets a `pending_review` queue as a hard requirement, and the corollary holds — no chatbot embedded in the web UI, since Claude and Hermes already are that interface via MCP. Trade-off accepted: some automation keeps a human tap in the loop that pure-AI products would remove.
