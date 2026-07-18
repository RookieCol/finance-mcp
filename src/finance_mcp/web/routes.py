"""Internal UI routes — read + manual CRUD, going through the same
`core.validation`/`core.repository` the MCP tools use, so a transaction
entered by hand and one created via chat are governed by identical
rules.
"""

import uuid
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from finance_mcp.core import alerts, projections, reporting, repository
from finance_mcp.core.models import AuditActor, CategoryType, TransactionType
from finance_mcp.core.validation import TransactionInput, validate_transaction
from finance_mcp.web.deps import get_db

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

MAX_FORECAST_BAR_MONTHS = 3


@router.get("/")
def dashboard(request: Request, session: Session = Depends(get_db)) -> Any:
    today = date.today()
    month_start = today.replace(day=1)
    category_totals = reporting.totals_by_category(session, date_from=month_start, date_to=today)
    recent = repository.list_transactions(session, limit=10)
    open_alerts = repository.list_open_alerts_for_rules(session, alerts.DEDUP_TRACKED_RULES)

    proj = projections.compute_projections(session, months_ahead=MAX_FORECAST_BAR_MONTHS)
    history = reporting.totals_by_month(session)
    bars = _build_bars(history, proj.monthly_net_forecast_minor, today)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "category_totals": [
                {
                    "category": r.category,
                    "currency": r.currency,
                    "amount": f"{r.total_minor / 100:.2f}",
                }
                for r in category_totals
            ],
            "recent": [_transaction_view(t) for t in recent],
            "open_alerts": [{"rule": a.rule, "severity": a.severity.value} for a in open_alerts],
            "bars": bars,
            "runway_months": proj.runway_months,
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
    repository.create_transaction(
        session,
        result.transaction,
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
                    "monthly_limit": f"{b.monthly_limit_minor / 100:.2f}",
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
                        "monthly_limit": f"{b.monthly_limit_minor / 100:.2f}",
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


def _transaction_view(t: Any) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "type": t.type.value,
        "amount": f"{t.amount_minor / 100:.2f}",
        "currency": t.currency,
        "occurred_on": t.occurred_on.isoformat(),
        "description": t.description,
        "category": t.category,
        "is_recurring": t.is_recurring,
    }


def _build_bars(
    history: list[reporting.MonthTotal], forecast_minor: list[int], today: date
) -> list[dict[str, Any]]:
    """Simple flexbox bar chart data — historical net (income - expense
    isn't directly available from totals_by_month alone since it doesn't
    split by type here; this uses the already-computed net forecast plus
    a same-shaped trailing history window for a consistent scale)."""
    months = sorted({m.month for m in history})[-MAX_FORECAST_BAR_MONTHS:]
    history_by_month: dict[str, int] = {}
    for m in history:
        history_by_month[m.month] = history_by_month.get(m.month, 0) + m.total_minor

    values: list[tuple[str, int, bool]] = [(m, history_by_month.get(m, 0), False) for m in months]
    forecast_start = today.replace(day=1)
    for i, amount in enumerate(forecast_minor):
        forecast_month = _add_months(forecast_start, i + 1)
        values.append((forecast_month.strftime("%Y-%m"), amount, True))

    if not values:
        return []
    max_abs = max(abs(v) for _, v, _ in values) or 1
    bars = []
    for month, minor, is_forecast in values:
        pct = abs(minor) / max_abs * 50  # half-width scale, bars grow from center
        offset = 50 - pct if minor >= 0 else 50 - pct
        bars.append(
            {
                "label": month,
                "value": minor,
                "display": f"{minor / 100:.2f}",
                "width_pct": round(pct, 1),
                "offset_pct": round(offset if minor >= 0 else 50, 1),
                "is_forecast": is_forecast,
            }
        )
    return bars


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)
