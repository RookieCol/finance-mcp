"""Internal UI routes — read + manual CRUD, going through the same
`core.validation`/`core.repository` the MCP tools use, so a transaction
entered by hand and one created via chat are governed by identical
rules.
"""

import uuid
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from caudal.config import get_settings
from caudal.core import alerts, fx, projections, reporting, repository
from caudal.core.models import AuditActor, CategoryType, TransactionType
from caudal.core.validation import TransactionInput, ValidationIssue, validate_transaction
from caudal.web import charts
from caudal.web.deps import get_db

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

MAX_FORECAST_BAR_MONTHS = 3
REPORTS_DEFAULT_WINDOW_MONTHS = 6

# Plain-language labels for the accounting-shorthand category keys
# (validated against core.validation.VALID_EXPENSE_CATEGORIES /
# VALID_INCOME_CATEGORIES) — shown alongside the raw key everywhere a
# category appears, so "cogs"/"ga"/"rd" aren't the only thing on screen.
CATEGORY_LABELS: dict[str, str] = {
    "cogs": "Infrastructure & hosting",
    "sales": "Sales",
    "marketing": "Marketing",
    "rd": "R&D / engineering",
    "ga": "General & admin",
    "subscription": "Subscription revenue",
    "services": "Services revenue",
    "other": "Other income",
}


@router.get("/")
def dashboard(request: Request, session: Session = Depends(get_db)) -> Any:
    today = date.today()
    month_start = today.replace(day=1)
    # Full calendar month, not month-to-date: a payment already recorded
    # with a date later this month (e.g. a salary paid on the 30th) is
    # part of "this month" — and the hero's net, which has no date
    # filter, already counts it. Cutting the breakdown at `today` made
    # the two disagree.
    month_end = charts.add_months(month_start, 1) - timedelta(days=1)
    expense_totals = reporting.totals_by_category(
        session, type=TransactionType.expense, date_from=month_start, date_to=month_end
    )
    infra_transactions = repository.list_transactions(
        session,
        type=TransactionType.expense,
        category="cogs",
        date_from=month_start,
        date_to=month_end,
    )
    recent = repository.list_transactions(session, limit=10)
    open_alerts = repository.list_open_alerts_for_rules(session, alerts.DEDUP_TRACKED_RULES)

    proj = projections.compute_projections(
        session,
        months_ahead=MAX_FORECAST_BAR_MONTHS,
        cash_balance_minor=_configured_cash_balance_minor(),
    )
    history = reporting.net_totals_by_month(session)
    series = charts.build_net_series(history, proj.monthly_net_forecast_minor, today)
    net_chart = charts.monthly_net_bar_svg(series)

    current_month_net = next(
        (p.value_minor for p in reversed(series) if not p.is_forecast), None
    )
    runway_segments = _runway_segments(proj.runway_months)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "expense_breakdown": _category_breakdown_rows(expense_totals),
            "expense_total_display": (
                _fmt_money(sum(r.total_minor for r in expense_totals)) if expense_totals else None
            ),
            "expense_total_currency": expense_totals[0].currency if expense_totals else None,
            "infra_breakdown": _infra_breakdown_rows(infra_transactions),
            "recent": [_transaction_view(t) for t in recent],
            "open_alerts": [{"rule": a.rule, "severity": a.severity.value} for a in open_alerts],
            "net_chart": net_chart,
            "current_month_net": current_month_net,
            "current_month_net_display": (
                _fmt_money(current_month_net) if current_month_net is not None else None
            ),
            "runway_months": proj.runway_months,
            "runway_segments": runway_segments,
            "mrr_growth_rate": proj.mrr_growth_rate,
        },
    )


@router.get("/transactions")
def list_transactions(
    request: Request,
    type: str | None = None,
    category: str | None = None,
    session: Session = Depends(get_db),
) -> Any:
    rows = repository.list_transactions(
        session,
        type=TransactionType(type) if type else None,
        category=category or None,
    )
    return templates.TemplateResponse(
        request,
        "transactions_list.html",
        {
            "transactions": [_transaction_view(t) for t in rows],
            "type": type,
            "category": category,
        },
    )


@router.get("/transactions/new")
def new_transaction_form(request: Request, session: Session = Depends(get_db)) -> Any:
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        {
            "transaction": None,
            "form": {},
            "errors": [],
            "categories": repository.list_categories(session),
        },
    )


@router.post("/transactions/new")
def create_transaction_submit(
    request: Request,
    type: str = Form(...),
    amount: str = Form(...),
    currency: str = Form("USD"),
    occurred_on: str = Form(...),
    description: str = Form(...),
    category: str = Form(...),
    is_recurring: bool = Form(False),
    session: Session = Depends(get_db),
) -> Any:
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
    if not result.is_valid or result.transaction is None:
        return templates.TemplateResponse(
            request,
            "transaction_form.html",
            {
                "transaction": None,
                "form": raw.__dict__,
                "errors": result.issues,
                "categories": repository.list_categories(session),
            },
            status_code=422,
        )
    try:
        tx = fx.convert_to_cop(result.transaction)
    except fx.FxRateUnavailable as exc:
        return templates.TemplateResponse(
            request,
            "transaction_form.html",
            {
                "transaction": None,
                "form": raw.__dict__,
                "errors": [ValidationIssue(field="currency", message=str(exc))],
                "categories": repository.list_categories(session),
            },
            status_code=422,
        )
    repository.create_transaction(
        session,
        tx,
        source="ui",
        actor=AuditActor.ui,
        raw_input=f"web form: {description}",
    )
    return RedirectResponse("/transactions", status_code=303)


@router.get("/transactions/{transaction_id}/edit")
def edit_transaction_form(
    request: Request, transaction_id: str, session: Session = Depends(get_db)
) -> Any:
    row = repository.get_transaction(session, uuid.UUID(transaction_id))
    if row is None:
        return RedirectResponse("/transactions", status_code=303)
    form = {
        "type": row.type.value,
        "amount": f"{row.amount_minor / 100:.2f}",
        "currency": row.currency,
        "occurred_on": row.occurred_on.isoformat(),
        "description": row.description,
        "category": row.category,
        "is_recurring": row.is_recurring,
    }
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        {
            "transaction": row,
            "form": form,
            "errors": [],
            "categories": repository.list_categories(session),
        },
    )


@router.post("/transactions/{transaction_id}/edit")
def edit_transaction_submit(
    request: Request,
    transaction_id: str,
    type: str = Form(...),
    amount: str = Form(...),
    currency: str = Form("USD"),
    occurred_on: str = Form(...),
    description: str = Form(...),
    category: str = Form(...),
    is_recurring: bool = Form(False),
    session: Session = Depends(get_db),
) -> Any:
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
    if not result.is_valid or result.transaction is None:
        row = repository.get_transaction(session, uuid.UUID(transaction_id))
        return templates.TemplateResponse(
            request,
            "transaction_form.html",
            {
                "transaction": row,
                "form": raw.__dict__,
                "errors": result.issues,
                "categories": repository.list_categories(session),
            },
            status_code=422,
        )
    tx = result.transaction
    repository.update_transaction(
        session,
        uuid.UUID(transaction_id),
        actor=AuditActor.ui,
        type=tx.type,
        amount_minor=tx.amount_minor,
        currency=tx.currency,
        occurred_on=tx.occurred_on,
        description=tx.description,
        category=tx.category,
        is_recurring=tx.is_recurring,
    )
    return RedirectResponse("/transactions", status_code=303)


@router.post("/transactions/{transaction_id}/delete")
def delete_transaction(transaction_id: str, session: Session = Depends(get_db)) -> Any:
    repository.soft_delete_transaction(session, uuid.UUID(transaction_id), actor=AuditActor.ui)
    return RedirectResponse("/transactions", status_code=303)


@router.get("/transactions/{transaction_id}/history")
def transaction_history(
    request: Request, transaction_id: str, session: Session = Depends(get_db)
) -> Any:
    entries = repository.get_transaction_history(session, uuid.UUID(transaction_id))
    return templates.TemplateResponse(
        request,
        "history.html",
        {
            "transaction_id": transaction_id,
            "entries": [
                {
                    "at": e.at.isoformat(),
                    "action": e.action.value,
                    "actor_source": e.actor_source.value,
                    "changed_fields": e.changed_fields,
                }
                for e in entries
            ],
        },
    )


@router.get("/budgets")
def list_budgets(request: Request, session: Session = Depends(get_db)) -> Any:
    budgets = repository.list_budgets(session)
    expense_categories = repository.list_categories(session, type=CategoryType.expense)
    return templates.TemplateResponse(
        request,
        "budgets.html",
        {
            "budgets": [
                {
                    "id": b.id,
                    "category": b.category,
                    "monthly_limit": _fmt_money(b.monthly_limit_minor),
                    "currency": b.currency,
                    "active": b.active,
                }
                for b in budgets
            ],
            "expense_categories": expense_categories,
            "errors": [],
        },
    )


@router.post("/budgets")
def create_budget(
    request: Request,
    category: str = Form(...),
    monthly_limit: str = Form(...),
    currency: str = Form("USD"),
    session: Session = Depends(get_db),
) -> Any:
    try:
        monthly_limit_minor = int(round(float(monthly_limit) * 100))
        if monthly_limit_minor <= 0:
            raise ValueError("Monthly limit must be positive")
    except ValueError as exc:
        budgets = repository.list_budgets(session)
        expense_categories = repository.list_categories(session, type=CategoryType.expense)
        return templates.TemplateResponse(
            request,
            "budgets.html",
            {
                "budgets": [
                    {
                        "id": b.id,
                        "category": b.category,
                        "monthly_limit": _fmt_money(b.monthly_limit_minor),
                        "currency": b.currency,
                        "active": b.active,
                    }
                    for b in budgets
                ],
                "expense_categories": expense_categories,
                "errors": [str(exc)],
            },
            status_code=422,
        )
    repository.create_budget(
        session, category=category, monthly_limit_minor=monthly_limit_minor, currency=currency
    )
    return RedirectResponse("/budgets", status_code=303)


@router.post("/budgets/{budget_id}/delete")
def delete_budget(budget_id: str, session: Session = Depends(get_db)) -> Any:
    repository.delete_budget(session, uuid.UUID(budget_id))
    return RedirectResponse("/budgets", status_code=303)


@router.post("/budgets/{budget_id}/toggle")
def toggle_budget(budget_id: str, session: Session = Depends(get_db)) -> Any:
    row = repository.list_budgets(session)
    current = next((b for b in row if str(b.id) == budget_id), None)
    if current is not None:
        repository.update_budget(session, uuid.UUID(budget_id), active=not current.active)
    return RedirectResponse("/budgets", status_code=303)


@router.post("/budgets/{budget_id}/edit")
def edit_budget(
    budget_id: str,
    monthly_limit: str = Form(...),
    session: Session = Depends(get_db),
) -> Any:
    try:
        monthly_limit_minor = int(round(float(monthly_limit) * 100))
        if monthly_limit_minor <= 0:
            raise ValueError
    except ValueError:
        return RedirectResponse("/budgets", status_code=303)
    repository.update_budget(session, uuid.UUID(budget_id), monthly_limit_minor=monthly_limit_minor)
    return RedirectResponse("/budgets", status_code=303)


@router.get("/alerts")
def list_alerts(request: Request, session: Session = Depends(get_db)) -> Any:
    rows = repository.list_alerts(session)
    return templates.TemplateResponse(
        request,
        "alerts.html",
        {
            "alerts": [
                {
                    "id": a.id,
                    "rule": a.rule,
                    "severity": a.severity.value,
                    "detected_at": a.detected_at.isoformat(),
                    "delivered_at": a.delivered_at.isoformat() if a.delivered_at else None,
                    "summary": _format_alert_payload(a.rule, a.payload),
                    "payload": a.payload,
                }
                for a in rows
            ]
        },
    )


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, session: Session = Depends(get_db)) -> Any:
    repository.mark_alert_delivered(session, uuid.UUID(alert_id))
    return RedirectResponse("/alerts", status_code=303)


@router.get("/projections")
def projections_page(request: Request, session: Session = Depends(get_db)) -> Any:
    today = date.today()
    proj = projections.compute_projections(
        session, months_ahead=6, cash_balance_minor=_configured_cash_balance_minor()
    )
    history = reporting.net_totals_by_month(session)
    series = charts.build_net_series(history, proj.monthly_net_forecast_minor, today)
    net_chart = charts.monthly_net_bar_svg(series)

    forecast_rows = [p for p in series if p.is_forecast]

    return templates.TemplateResponse(
        request,
        "projections.html",
        {
            "net_chart": net_chart,
            "forecast_rows": [
                {"month": p.label, "display": _fmt_money(p.value_minor), "value": p.value_minor}
                for p in forecast_rows
            ],
            "runway_months": proj.runway_months,
            "mrr_growth_rate": proj.mrr_growth_rate,
            "assumptions": {
                "trend_window_months": proj.assumptions.trend_window_months,
                "historical_months_used": proj.assumptions.historical_months_used,
                "recurring_income": _fmt_money(proj.assumptions.recurring_income_minor),
                "recurring_expense": _fmt_money(proj.assumptions.recurring_expense_minor),
            },
        },
    )


@router.get("/reports")
def reports_page(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    session: Session = Depends(get_db),
) -> Any:
    today = date.today()
    default_from = charts.add_months(today.replace(day=1), -(REPORTS_DEFAULT_WINDOW_MONTHS - 1))
    parsed_from = _parse_date(date_from) or default_from
    parsed_to = _parse_date(date_to) or today
    if parsed_from > parsed_to:
        parsed_from, parsed_to = default_from, today

    month_totals = reporting.net_totals_by_month(session, date_from=parsed_from, date_to=parsed_to)
    expense_totals = reporting.totals_by_category(
        session, type=TransactionType.expense, date_from=parsed_from, date_to=parsed_to
    )
    income_totals = reporting.totals_by_category(
        session, type=TransactionType.income, date_from=parsed_from, date_to=parsed_to
    )

    months_present = sorted({m.month for m in month_totals})
    previous_month = (
        charts.add_months(_month_to_date(months_present[-1]), -1).strftime("%Y-%m")
        if months_present
        else ""
    )
    mom_delta = (
        reporting.month_over_month_delta(month_totals, previous_month) if months_present else {}
    )

    sparkline_values: dict[str, list[int]] = {}
    for m in month_totals:
        sparkline_values.setdefault(m.currency, []).append(m.total_minor)

    return templates.TemplateResponse(
        request,
        "reports.html",
        {
            "date_from": parsed_from.isoformat(),
            "date_to": parsed_to.isoformat(),
            "month_totals": [
                {
                    "month": m.month,
                    "currency": m.currency,
                    "amount": _fmt_money(m.total_minor),
                    "value": m.total_minor,
                }
                for m in month_totals
            ],
            "expense_breakdown": _category_breakdown_rows(expense_totals),
            "income_breakdown": _category_breakdown_rows(income_totals),
            "mom_delta": [
                {"currency": ccy, "display": _fmt_money(delta), "value": delta}
                for ccy, delta in mom_delta.items()
            ],
            "sparklines": {
                ccy: charts.sparkline_svg(values) for ccy, values in sparkline_values.items()
            },
        },
    )


def _transaction_view(t: Any) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "type": t.type.value,
        "amount": _fmt_money(t.amount_minor),
        "currency": t.currency,
        "occurred_on": t.occurred_on.isoformat(),
        "description": t.description,
        "category": t.category,
        "is_recurring": t.is_recurring,
    }


def _fmt_money(minor: int) -> str:
    return f"{minor / 100:,.2f}"


def _configured_cash_balance_minor() -> int:
    return int(round(float(get_settings().scheduler_cash_balance) * 100))


def _category_label(key: str) -> str:
    return CATEGORY_LABELS.get(key, key)


templates.env.filters["category_label"] = _category_label


def _category_breakdown_rows(totals: list[reporting.CategoryTotal]) -> list[dict[str, Any]]:
    """Category totals as display-ready rows, biggest first, each
    carrying a plain-language label alongside the raw key and its share
    of the group's total — so a breakdown reads by size, not
    alphabetically, and the accounting shorthand isn't the only label
    on screen."""
    ordered = sorted(totals, key=lambda r: r.total_minor, reverse=True)
    total_minor = sum(r.total_minor for r in ordered) or 1
    return [
        {
            "category": r.category,
            "label": _category_label(r.category),
            "currency": r.currency,
            "amount": _fmt_money(r.total_minor),
            "pct": round(r.total_minor / total_minor * 100),
        }
        for r in ordered
    ]


# Description keywords used to split the single "cogs" (infrastructure)
# category into per-vendor rows for the dashboard's infra breakdown —
# there's no structured vendor field, so this is a best-effort read of
# the free-text description written at record time.
INFRA_VENDOR_KEYWORDS: list[tuple[str, str]] = [
    ("vercel", "Vercel"),
    ("supabase", "Supabase"),
    ("resend", "Resend"),
    ("registrar", "Domain registrar"),
    ("cloudflare", "Cloudflare"),
]


def _infer_vendor(description: str) -> str:
    lower = description.lower()
    for needle, label in INFRA_VENDOR_KEYWORDS:
        if needle in lower:
            return label
    return "Other infra"


def _infra_breakdown_rows(transactions: Sequence[Any]) -> list[dict[str, Any]]:
    totals: dict[tuple[str, str], int] = {}
    for t in transactions:
        key = (_infer_vendor(t.description), t.currency)
        totals[key] = totals.get(key, 0) + t.amount_minor
    total_minor = sum(totals.values()) or 1
    ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {
            "label": vendor,
            "currency": ccy,
            "amount": _fmt_money(minor),
            "pct": round(minor / total_minor * 100),
        }
        for (vendor, ccy), minor in ordered
    ]


def _runway_segments(runway_months: float | None, *, total: int = 12) -> list[str]:
    """Twelve-segment meter for the dashboard hero — each segment is one
    month, filled up to the runway value and colored by how close the
    remaining runway is to the alerting thresholds (matches
    core.alerts.DEFAULT_RUNWAY_WARNING_MONTHS and its critical half)."""
    if runway_months is None:
        return ["filled"] * total
    filled = min(total, max(0, round(runway_months)))
    tone = "critical" if runway_months < 3 else "warn" if runway_months < 6 else ""
    return [f"filled {tone}".strip() if i < filled else "" for i in range(total)]


def _format_alert_payload(rule: str, payload: dict[str, Any]) -> str:
    if rule == "budget_overrun":
        category = payload.get("category", "?")
        currency = payload.get("currency", "")
        spend = _fmt_money(payload.get("spend_minor", 0))
        limit = _fmt_money(payload.get("limit_minor", 0))
        ratio = payload.get("ratio", 0) or 0
        return f"{category}: spent {currency} {spend} of {currency} {limit} budget ({ratio:.0%})"
    if rule == "runway_threshold":
        runway = payload.get("runway_months", 0) or 0
        warning = payload.get("warning_months", 0) or 0
        return f"{runway:.1f} months of runway left (warns below {warning:.0f})"
    if rule == "spend_spike":
        category = payload.get("category", "?")
        currency = payload.get("currency", "")
        current = _fmt_money(payload.get("current_minor", 0))
        avg = _fmt_money(round(payload.get("trailing_average_minor", 0) or 0))
        return f"{category}: {currency} {current} this month vs {currency} {avg} trailing average"
    if rule == "missing_recurring_income":
        missing = payload.get("missing_categories") or []
        return "missing recurring income: " + ", ".join(missing)
    return str(payload)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _month_to_date(month: str) -> date:
    year, month_num = (int(part) for part in month.split("-"))
    return date(year, month_num, 1)
