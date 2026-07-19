# Phase 02 — AI & automation

**Status: planned · Depends on: Phase 01 (collections needs invoices; digest gets richer with MRR/cartera).**

Governing rule for every item here: **the deterministic engine computes, the AI narrates/extracts/drafts.** No LLM output reaches the ledger or leaves the system without either a human approval step or a fully deterministic payload.

## 02.1 — Narrated weekly digest *(cheapest, highest immediate return)*

The scheduler already computes the digest and delivers via webhook (`scheduler/jobs.py` → `notifier.py`). Add one step: an LLM turns the numbers into a founder briefing — *"burn up 12% on infra; 4M of cartera is 30+ days overdue; runway 3.1 months"* — delivered to Telegram/Slack.

- **Design:** `run_weekly_digest` gains a narration hook: digest dict → prompt → short narrative → webhook. On LLM failure, fall back to the current numeric digest — delivery never depends on the model.
- **Model access:** OpenRouter key already in `.env`; a `narrator.py` module isolates the call (provider-agnostic, ~30 lines).
- **Test:** narration mocked; fallback path asserted.

## 02.2 — Email invoice ingest (cron + LLM extraction + review queue)

Forwarded/received vendor invoices land in the ledger without manual typing — but **never without review**.

```
mailbox (IMAP) ──► scheduler job ──► PDF text (pypdf) ──► LLM → {vendor, amount,
currency, issued_on, invoice_number, confidence} ──► ingest_queue (pending_review)
──► human approves via UI or chat ──► create_transaction(idempotency_key=invoice_number)
                                       └─ USD → COP at TRM automatically (core/fx.py)
```

- **New table `ingest_queue`:** raw source ref (message-id, filename), extracted fields JSONB, confidence, status (`pending_review | approved | rejected`), reviewed_by/at. Message-id + invoice-number uniqueness makes re-polling idempotent.
- **Approval surfaces:** a `/inbox` page (approve/edit/reject per row) and MCP tools `list_pending_ingests` / `approve_ingest` — so review works from chat too.
- **Hard rule:** the LLM writes to `ingest_queue`, never to `transactions`. A misread amount corrupts finances silently; the queue makes every automated entry inspectable before it counts.
- **Config:** `INGEST_IMAP_URL/USER/PASSWORD`, dedicated mailbox (e.g. `facturas@…`), poll on the existing APScheduler.
- **Honest ROI note:** at ~6 invoices/month this is convenience, not leverage. Build when volume (or friction) justifies it.

## 02.3 — Wire the two dead alert rules + LLM explanations

`spend_spike_findings` and `missing_recurring_income_finding` exist in `core/alerts.py` but are not registered in `evaluate_alerts` / `DEDUP_TRACKED_RULES` — they can never fire.

- Wire both into the orchestrator with dedup keys (mechanical; the pure rules are already unit-tested).
- On delivery, attach an optional LLM explanation grounded in the payload plus the offending transactions: *"cogs spike driven by 2 Vercel charges totaling 260k"*. Explanation is decoration on a deterministic finding — same fallback rule as 02.1.

## 02.4 — Assisted recurring registration

Recurring payments (salary on the 30th, infra on the 16th–18th) currently require remembering to record them.

- Scheduler job: on each recurring stream's expected date (derived from `latest_recurring_totals_by_category` + last occurrence), send a confirmation prompt via notifier: *"Register Juan's salary (3.3M) for July 30?"*
- Confirmation via chat (`record_transaction` with a deterministic idempotency key: `recurring:{category}:{YYYY-MM}`) or one click in the UI.
- **Not** auto-inserted: amounts change (prorated first month already happened); the human stays in the loop at one-tap cost.

## 02.5 — Collections drafts (cartera) *(needs Phase 01)*

For invoices in the `31-60` / `61+` aging buckets: a scheduled job drafts a payment-reminder email per client (invoice details, amount, days overdue) and delivers the draft via notifier/chat for approval. The system never sends autonomously.

## Explicit non-goals

- **No embedded chatbot in the web UI** — Claude and Hermes already are that interface via MCP; duplicating it inside the dashboard is maintenance without new capability.
- **No LLM-computed metrics** — every number stays in tested SQL/Python.
