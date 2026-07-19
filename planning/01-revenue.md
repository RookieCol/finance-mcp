# Phase 01 — Revenue: clients, plans, subscriptions, cartera

**Status: in progress · Why:** the ledger sees every peso leaving but nothing coming in — MRR reads `n/a` and ~10M COP of outstanding receivables are invisible. This phase models the revenue side on a cash basis and separates payroll from general expenses.

Domain grounding: [`../../finanzas-saas.md`](../../finanzas-saas.md) — MRR = active subscribers × ARPU decomposed into new/expansion/contraction/churned; AR tracking as a daily-ops requirement.

## Data model (`core/models.py`)

Same conventions as existing tables: UUID PKs, `BigInteger` minor units, timezone-aware timestamps, `CheckConstraint`s, PG enums via `SAEnum(StrEnum)`.

| Table | Columns (essentials) | Notes |
|---|---|---|
| `clients` | `name` unique · `contact_email` · `tax_id` (NIT) · `notes` · `archived_at` | Soft-archive mirrors `deleted_at` pattern |
| `plans` | `name` unique · `amount_minor > 0` · `currency` · `billing_period` (`monthly\|annual`) · `active` | Price per billing period |
| `subscriptions` | `client_id` FK · `plan_id` FK · `started_on` · `canceled_on?` | Status **derived**, never stored: active = `started ≤ as_of < canceled` |
| `invoices` | `client_id` FK · `subscription_id?` FK · `amount_minor > 0` · `issued_on` · `due_on ≥ issued_on` · `status` (`pending\|paid\|void`) · `paid_on?` · `transaction_id?` FK **unique** · `description` | No `draft` state; `overdue` derived (`pending ∧ due_on < today`) |

**Key decision — payment link lives on the invoice** (`invoices.transaction_id`, nullable + unique), not on `transactions`. The core table stays untouched (zero risk to the existing suite), direction matches the domain (the invoice knows what settled it), and uniqueness enforces one-payment-per-invoice — the v1 cash model (no partial payments).

## Migrations

- **A — revenue tables**: four tables + `billing_period`, `invoice_status` enums (autogenerate, hand-adjusted; `down_revision = f0493be25eec`).
- **B — seed `payroll`**: `{"key": "payroll", "type": "expense", "label": "Payroll & compensation"}` via the `f0493be25eec` bulk-insert pattern. **Same commit must update** `VALID_EXPENSE_CATEGORIES` (`core/validation.py`) and `CATEGORY_LABELS` (`web/routes.py`); a new test asserts seed ≡ validation sets so the invariant can never drift again.
- Existing salary transaction recategorizes `ga → payroll` **manually via UI/MCP post-deploy** — a data migration would bypass the audit-log-on-every-write invariant.
- Test infra: add the four tables to both `TRUNCATE` statements in `tests/integration/conftest.py`.

## Repository (`core/revenue.py`, new module)

Sibling to `repository.py` (already ~280 lines), same session + audit conventions — every write appends `AuditLog` with entities `client|plan|subscription|invoice`.

CRUD: `create_client` / `list_clients` / `get_client` · `create_plan` / `list_plans` · `create_subscription` / `cancel_subscription` (idempotent) / `list_subscriptions(active_on=…)` · `create_invoice` / `void_invoice` (pending-only — voiding a paid invoice would orphan a cash transaction) / `list_invoices` / `list_outstanding_invoices`.

**`mark_invoice_paid(session, invoice_id, *, paid_on, actor, source)`** — the critical path, one session transaction:

1. Already `paid` → return unchanged (idempotent). Missing/void → `None`.
2. Create the income transaction **through the existing `repository.create_transaction`** — validation, audit, and dedup reuse the proven path — with `idempotency_key = f"invoice-payment:{invoice_id}"`, category `subscription` (linked to a sub) or `services` (one-off), `is_recurring=False` (the recurring signal now comes from subscriptions — prevents MRR double-count).
3. Set `status=paid`, `paid_on`, `transaction_id`; append the invoice audit entry.

Invoice state and cash can never disagree: everything commits or rolls back together.

## Metrics (`core/saas_metrics.py`, new module)

Pure functions first (unit-testable, no DB), thin orchestrator second — the `projections.py` structure.

- `monthly_amount_minor(amount, period)` — annual normalizes `/12` via `Decimal`, never float; per-subscription rounding documented.
- `aging_bucket(due_on, as_of)` → `current | 0-30 | 31-60 | 61+` days past due · `aging_totals(...)`.
- `arpu_minor`, `logo_churn_rate` — `None` on zero denominators.
- `compute_saas_metrics(session, as_of) -> SaasMetrics{mrr_minor, active_subscriptions, arpu_minor, new_mrr_minor, churned_mrr_minor, logo_churn_rate, cartera_total_minor, cartera_aging}`.

**v1 limitation (documented):** a plan change is modeled as cancel + create, which reports phantom churn + new MRR in the same month. Fix later with `subscription.replaced_by_id`.

**Projections integration** (`core/projections.py`): when active subscriptions exist, `recurring_income = subscription MRR + recurring income transactions excluding category "subscription"` (exclusion prevents double-count — pinned by a unit test); otherwise current behavior (fallback). `mrr_growth_rate` becomes real month-end MRR deltas derived from `started_on`/`canceled_on` history. `ProjectionAssumptions` gains `subscription_mrr_minor` so both render sites show which base was used.

## MCP tools (`mcp_server/server.py`, +9)

`create_client` · `list_clients` · `create_plan` · `create_subscription` · `cancel_subscription` · `create_invoice` · `record_invoice_payment` (idempotent) · `get_cartera` (outstanding + aging, client names resolved) · `get_saas_metrics`.

Existing conventions throughout: amounts as decimal strings, `{"status": "ok"|"error"|"clarification_needed"}`, correlation-id + tracing, never a raised exception to the client.

## Web UI

- New `web/revenue_routes.py` (`APIRouter` registered in `app.py`; `routes.py` is at ~670 lines) + templates `clients.html`, `client_detail.html`, `plans.html`, `cartera.html` built from existing macros (`stat_tile`, `badge`, `empty_state`, `category_breakdown`).
- **/cartera** — the daily-ops page: outstanding total + aging-bucket stat tiles, invoice table (badge tone by bucket), *Mark paid* (date input, default today), *Void*, create-invoice form.
- **/clients** (+ detail: subscriptions, invoices, balance) · **/plans** (list + create, `budgets.html` structure).
- **Dashboard**: hero chip becomes **real MRR** (+growth), new *Cartera* card; payroll separates automatically in the expense breakdown (data-driven).
- **Nav**: desktop gains a *Revenue* pill → `/cartera` with `Cartera | Clients | Plans` sub-tabs inside the pages; mobile tabbar swaps *Budgets* for *Revenue* (budgets is set-and-forget; cartera is daily).

## Milestones

| # | Ships | Gate |
|---|---|---|
| M1 | Models + migrations + `payroll` + `core/revenue.py` | CRUD/audit tests, idempotent payment, category-sync test |
| M2 | `core/saas_metrics.py` + projections integration | Rounding/aging/zero-denominator units, no-double-count pin |
| M3 | 9 MCP tools | Per-tool happy/clarification/error paths; **real data loads via chat here** |
| M4 | Web UI + dashboard + nav | Page renders, pay-flow → `/transactions`, full suite green |

M3 lands before M4 deliberately: the founder loads real clients and the ~10M cartera via chat, so the UI is built against real data. Every milestone ends with `pytest` + `ruff` + `mypy` green and the 85% coverage gate intact.

## Risks

Validation/seed drift (blocked by sync test) · conftest TRUNCATE omission (M1 checklist) · annual-plan rounding (Decimal, documented) · MRR double-count (exclusion + test) · upgrade-as-churn artifact (documented v1) · mobile tabbar swap (owner may veto).
