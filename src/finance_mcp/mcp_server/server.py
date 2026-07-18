"""MCP server: the tool surface Hermes (or any MCP client) calls to
record, correct, list, and report on transactions, and to pull
projections/digests/alerts.

Every tool wraps ``core/`` — no business logic lives here. Errors are
returned as structured content (``{"status": "error", ...}``), never a
raised exception surfaced to the client. Ambiguous ``record_transaction``
input first tries ``elicitation/create`` to ask the client for exactly
the missing field(s); if that's declined or the client doesn't support
elicitation, it falls back to a structured
``{"status": "clarification_needed", ...}`` response instead.
"""

import dataclasses
import uuid
from datetime import date
from typing import Any

from mcp.server.elicitation import AcceptedElicitation
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field, create_model

from finance_mcp.config import get_settings
from finance_mcp.core import alerts, db, projections, reporting, repository
from finance_mcp.core.logging import configure_logging, correlation_id, get_logger
from finance_mcp.core.models import AuditActor, CategoryType, TransactionType
from finance_mcp.core.tracing import configure_tracing, traced_operation
from finance_mcp.core.validation import TransactionInput, ValidationIssue, validate_transaction

mcp = FastMCP(name="finance-mcp")
logger = get_logger(__name__)


def _issues_to_payload(issues: list[ValidationIssue]) -> dict[str, Any]:
    return {
        "status": "clarification_needed",
        "missing": [i.field for i in issues],
        "message": " / ".join(f"{i.field}: {i.message}" for i in issues),
    }


async def _try_elicit_missing_fields(
    ctx: Context[Any, Any, Any], raw: TransactionInput, issues: list[ValidationIssue]
) -> TransactionInput | None:
    """Attempt to fill in the fields flagged by ``issues`` via MCP's
    elicitation/create (form mode) — pausing this tool call to ask the
    connected client for exactly the missing data, per-field.

    Returns an updated ``TransactionInput`` when the client accepted and
    provided values, or ``None`` if the client declined/cancelled, or
    doesn't support elicitation at all (older/simpler MCP clients — this
    is a plain client capability gap, not a bug, so we swallow the error
    and let the caller fall back to the structured clarification_needed
    response instead).
    """
    fields = {issue.field: (str, Field(description=issue.message)) for issue in issues}
    ElicitedFields = create_model("ElicitedTransactionFields", **fields)  # type: ignore[call-overload]
    message = "Missing/invalid fields for this transaction: " + ", ".join(
        f"{i.field} ({i.message})" for i in issues
    )
    try:
        result = await ctx.elicit(message=message, schema=ElicitedFields)
    except Exception:
        logger.info("elicitation.unsupported_or_failed", fields=list(fields))
        return None

    if not isinstance(result, AcceptedElicitation):
        logger.info("elicitation.declined_or_cancelled", fields=list(fields))
        return None

    updates = {name: getattr(result.data, name) for name in fields}
    return dataclasses.replace(raw, **updates)


@mcp.tool()
async def record_transaction(
    ctx: Context[Any, Any, Any],
    type: str | None = None,
    amount: str | None = None,
    occurred_on: str | None = None,
    description: str | None = None,
    category: str | None = None,
    currency: str = "USD",
    is_recurring: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Record an income or expense transaction.

    All of ``type``/``amount``/``occurred_on``/``description``/``category``
    are conceptually required, but accepted as optional here on purpose:
    omitting one must produce a 'clarification_needed' result (see below),
    not a hard schema-validation error that never reaches that logic.

    ``type`` is 'income' or 'expense'. ``amount`` is a decimal string
    (e.g. "50.00"), never a float. ``occurred_on`` is an ISO date
    (YYYY-MM-DD). ``category`` must be one of the values returned by
    ``list_categories`` for the given type. If any field is missing or
    invalid, this tool first tries to ask the client directly via MCP
    elicitation; if that's declined or unsupported, it returns a
    'clarification_needed' result instead of an error — ask the user in
    chat and retry with the corrected field(s).
    """
    # Not merged with the DB `with` below (SIM117): validation can
    # short-circuit before a session is ever needed.
    with correlation_id() as cid, traced_operation("record_transaction", correlation_id=cid):  # noqa: SIM117
        raw = TransactionInput(
            type=type,
            amount=amount,
            currency=currency,
            occurred_on=occurred_on,
            description=description,
            category=category,
            is_recurring=is_recurring,
        )
        result = validate_transaction(raw)

        if not result.is_valid:
            elicited = await _try_elicit_missing_fields(ctx, raw, result.issues)
            if elicited is not None:
                result = validate_transaction(elicited)

        if not result.is_valid or result.transaction is None:
            logger.info("record_transaction.clarification_needed", missing=len(result.issues))
            return _issues_to_payload(result.issues)

        with db.session_scope() as session:
            row = repository.create_transaction(
                session,
                result.transaction,
                source="chat",
                actor=AuditActor.chat,
                raw_input=(
                    f"{result.transaction.type.value} {result.transaction.amount_minor / 100:.2f} "
                    f"{result.transaction.currency} {result.transaction.description}"
                ),
                idempotency_key=idempotency_key,
            )
            session.flush()
            tx_id = str(row.id)
    logger.info("record_transaction.created", transaction_id=tx_id)
    return {"status": "ok", "transaction_id": tx_id}


@mcp.tool()
def update_transaction(
    transaction_id: str,
    amount: str | None = None,
    currency: str | None = None,
    occurred_on: str | None = None,
    description: str | None = None,
    category: str | None = None,
    is_recurring: bool | None = None,
) -> dict[str, Any]:
    """Correct an existing transaction — only the fields you pass are
    changed, e.g. update_transaction(id, amount="120.00") leaves
    everything else as-is."""
    fields: dict[str, Any] = {}
    if amount is not None:
        fields["amount_minor"] = int(round(float(amount) * 100))
    if currency is not None:
        fields["currency"] = currency.upper()
    if occurred_on is not None:
        fields["occurred_on"] = date.fromisoformat(occurred_on)
    if description is not None:
        fields["description"] = description
    if category is not None:
        fields["category"] = category
    if is_recurring is not None:
        fields["is_recurring"] = is_recurring

    with (
        correlation_id() as cid,
        traced_operation("update_transaction", correlation_id=cid),
        db.session_scope() as session,
    ):
        row = repository.update_transaction(
            session, uuid.UUID(transaction_id), actor=AuditActor.chat, **fields
        )
        if row is None:
            return {"status": "error", "message": f"No such transaction: {transaction_id}"}
        return {"status": "ok", "transaction_id": str(row.id)}


@mcp.tool()
def list_transactions(
    type: str | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List transactions, optionally filtered by type/category/date range."""
    with (
        correlation_id() as cid,
        traced_operation("list_transactions", correlation_id=cid),
        db.session_scope() as session,
    ):
        rows = repository.list_transactions(
            session,
            type=TransactionType(type) if type else None,
            category=category,
            date_from=date.fromisoformat(date_from) if date_from else None,
            date_to=date.fromisoformat(date_to) if date_to else None,
            limit=limit,
        )
        return {
            "status": "ok",
            "transactions": [
                {
                    "id": str(r.id),
                    "type": r.type.value,
                    "amount": f"{r.amount_minor / 100:.2f}",
                    "currency": r.currency,
                    "occurred_on": r.occurred_on.isoformat(),
                    "description": r.description,
                    "category": r.category,
                    "is_recurring": r.is_recurring,
                }
                for r in rows
            ],
        }


@mcp.tool()
def get_totals(
    type: str | None = None,
    group_by: str = "category",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Aggregate totals, grouped by 'category' or 'month'."""
    with (
        correlation_id() as cid,
        traced_operation("get_totals", correlation_id=cid),
        db.session_scope() as session,
    ):
        tx_type = TransactionType(type) if type else None
        df = date.fromisoformat(date_from) if date_from else None
        dt = date.fromisoformat(date_to) if date_to else None
        totals: list[dict[str, Any]]
        if group_by == "month":
            month_rows = reporting.totals_by_month(session, type=tx_type, date_from=df, date_to=dt)
            totals = [
                {"month": r.month, "currency": r.currency, "amount": f"{r.total_minor / 100:.2f}"}
                for r in month_rows
            ]
        else:
            category_rows = reporting.totals_by_category(
                session, type=tx_type, date_from=df, date_to=dt
            )
            totals = [
                {
                    "category": r.category,
                    "currency": r.currency,
                    "amount": f"{r.total_minor / 100:.2f}",
                }
                for r in category_rows
            ]
        return {"status": "ok", "group_by": group_by, "totals": totals}


@mcp.tool()
def list_categories(type: str | None = None) -> dict[str, Any]:
    """List the valid category taxonomy — call this before record_transaction
    to map free text to a valid category value."""
    with (
        correlation_id() as cid,
        traced_operation("list_categories", correlation_id=cid),
        db.session_scope() as session,
    ):
        rows = repository.list_categories(session, type=CategoryType(type) if type else None)
        return {
            "status": "ok",
            "categories": [{"key": c.key, "type": c.type.value, "label": c.label} for c in rows],
        }


@mcp.tool()
def get_projections(months_ahead: int = 3, cash_balance: str = "0") -> dict[str, Any]:
    """Forecast net cash flow, runway, and MRR growth, with the
    assumptions the numbers were computed from."""
    with (
        correlation_id() as cid,
        traced_operation("get_projections", correlation_id=cid),
        db.session_scope() as session,
    ):
        cash_balance_minor = int(round(float(cash_balance) * 100))
        result = projections.compute_projections(
            session, months_ahead=months_ahead, cash_balance_minor=cash_balance_minor
        )
        return {
            "status": "ok",
            "monthly_net_forecast": [f"{m / 100:.2f}" for m in result.monthly_net_forecast_minor],
            "runway_months": result.runway_months,
            "mrr_growth_rate": result.mrr_growth_rate,
            "assumptions": {
                "trend_window_months": result.assumptions.trend_window_months,
                "historical_months_used": result.assumptions.historical_months_used,
                "recurring_income": f"{result.assumptions.recurring_income_minor / 100:.2f}",
                "recurring_expense": f"{result.assumptions.recurring_expense_minor / 100:.2f}",
            },
        }


@mcp.tool()
def get_digest(period: str = "weekly") -> dict[str, Any]:
    """A prose-ready summary: totals, deltas vs the prior period, and
    pending alerts. This is the tool a scheduled job (Hermes cron or the
    internal scheduler, Stage 7) calls to push a proactive digest."""
    with (
        correlation_id() as cid,
        traced_operation("get_digest", correlation_id=cid),
        db.session_scope() as session,
    ):
        month_totals = reporting.totals_by_month(session)
        category_totals = reporting.totals_by_category(session)
        open_alerts = repository.list_open_alerts_for_rules(session, alerts.DEDUP_TRACKED_RULES)
        return {
            "status": "ok",
            "period": period,
            "totals_by_month": [
                {"month": m.month, "currency": m.currency, "amount": f"{m.total_minor / 100:.2f}"}
                for m in month_totals
            ],
            "totals_by_category": [
                {
                    "category": c.category,
                    "currency": c.currency,
                    "amount": f"{c.total_minor / 100:.2f}",
                }
                for c in category_totals
            ],
            "open_alerts": [{"rule": a.rule, "severity": a.severity.value} for a in open_alerts],
        }


@mcp.tool()
def check_alerts(cash_balance: str = "0") -> dict[str, Any]:
    """Run the proactive alert rules and return newly-fired findings
    (already-open findings are not re-reported — see core.alerts dedup)."""
    with (
        correlation_id() as cid,
        traced_operation("check_alerts", correlation_id=cid),
        db.session_scope() as session,
    ):
        cash_balance_minor = int(round(float(cash_balance) * 100))
        findings = alerts.evaluate_alerts(session, cash_balance_minor=cash_balance_minor)
        return {
            "status": "ok",
            "new_alerts": [
                {"rule": f.rule, "severity": f.severity.value, "payload": f.payload}
                for f in findings
            ],
        }


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings.otel_exporter_otlp_endpoint)
    db.init_engine(settings.database_url)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
