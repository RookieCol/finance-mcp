"""Aggregate queries — totals by category/month, month-over-month deltas.

Powers both the `get_totals` MCP tool (Stage 4) and the UI dashboard
(Stage 6). Aggregation happens in SQL over ``amount_minor`` (integers),
never in Python floats.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import BigInteger, Select, case, func, select
from sqlalchemy.orm import Session

from caudal.core.models import Transaction, TransactionType


@dataclass(frozen=True)
class CategoryTotal:
    category: str
    currency: str
    total_minor: int


@dataclass(frozen=True)
class MonthTotal:
    month: str  # "YYYY-MM"
    currency: str
    total_minor: int


def totals_by_category(
    session: Session,
    *,
    type: TransactionType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    is_recurring: bool | None = None,
) -> list[CategoryTotal]:
    stmt = (
        select(
            Transaction.category,
            Transaction.currency,
            func.sum(Transaction.amount_minor).cast(BigInteger).label("total_minor"),
        )
        .where(Transaction.deleted_at.is_(None))
        .group_by(Transaction.category, Transaction.currency)
        .order_by(Transaction.category)
    )
    stmt = _apply_common_filters(
        stmt, type=type, date_from=date_from, date_to=date_to, is_recurring=is_recurring
    )
    rows = session.execute(stmt).all()
    return [
        CategoryTotal(category=r.category, currency=r.currency, total_minor=int(r.total_minor))
        for r in rows
    ]


def totals_by_month(
    session: Session,
    *,
    type: TransactionType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    is_recurring: bool | None = None,
) -> list[MonthTotal]:
    month_expr = func.to_char(Transaction.occurred_on, "YYYY-MM").label("month")
    stmt = (
        select(
            month_expr,
            Transaction.currency,
            func.sum(Transaction.amount_minor).cast(BigInteger).label("total_minor"),
        )
        .where(Transaction.deleted_at.is_(None))
        .group_by(month_expr, Transaction.currency)
        .order_by(month_expr)
    )
    stmt = _apply_common_filters(
        stmt, type=type, date_from=date_from, date_to=date_to, is_recurring=is_recurring
    )
    rows = session.execute(stmt).all()
    return [
        MonthTotal(month=r.month, currency=r.currency, total_minor=int(r.total_minor)) for r in rows
    ]


def net_totals_by_month(
    session: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[MonthTotal]:
    """Net cash flow by month (income minus expense) — unlike
    totals_by_month(), which sums ``amount_minor`` across both
    transaction types unsigned (every row is stored as a positive
    magnitude; only ``type`` distinguishes income from expense). A
    month that's all expense would otherwise report a large *positive*
    total here instead of the burn it actually is.
    """
    month_expr = func.to_char(Transaction.occurred_on, "YYYY-MM").label("month")
    signed_amount = (
        func.sum(
            case(
                (Transaction.type == TransactionType.income, Transaction.amount_minor),
                else_=-Transaction.amount_minor,
            )
        )
        .cast(BigInteger)
        .label("total_minor")
    )
    stmt = (
        select(month_expr, Transaction.currency, signed_amount)
        .where(Transaction.deleted_at.is_(None))
        .group_by(month_expr, Transaction.currency)
        .order_by(month_expr)
    )
    stmt = _apply_common_filters(stmt, type=None, date_from=date_from, date_to=date_to)
    rows = session.execute(stmt).all()
    return [
        MonthTotal(month=r.month, currency=r.currency, total_minor=int(r.total_minor)) for r in rows
    ]


def latest_recurring_totals_by_category(
    session: Session, *, type: TransactionType
) -> list[CategoryTotal]:
    """Per category+currency, the recurring total of the most recent
    month with recurring activity in that category — i.e. the *current
    monthly rate* of each recurring stream. Summing all recurring rows
    unconditioned on month (what a bare ``totals_by_category(...,
    is_recurring=True)`` gives) double-counts a stream every time a new
    month's payment lands, inflating the forecast base a little more
    each month.
    """
    month_expr = func.to_char(Transaction.occurred_on, "YYYY-MM").label("month")
    stmt = (
        select(
            Transaction.category,
            Transaction.currency,
            month_expr,
            func.sum(Transaction.amount_minor).cast(BigInteger).label("total_minor"),
        )
        .where(Transaction.deleted_at.is_(None))
        .where(Transaction.type == type)
        .where(Transaction.is_recurring.is_(True))
        .group_by(Transaction.category, Transaction.currency, month_expr)
    )
    rows = session.execute(stmt).all()
    latest: dict[tuple[str, str], tuple[str, int]] = {}
    for r in rows:
        key = (r.category, r.currency)
        if key not in latest or r.month > latest[key][0]:
            latest[key] = (r.month, int(r.total_minor))
    return [
        CategoryTotal(category=category, currency=currency, total_minor=total)
        for (category, currency), (_, total) in sorted(latest.items())
    ]


def month_over_month_delta(current: list[MonthTotal], previous_month: str) -> dict[str, int]:
    """Given totals_by_month() output, return {currency: delta_minor}
    between the latest month present and ``previous_month`` (e.g. "2026-06").
    Pure function over already-fetched data — no DB access — so it's
    trivially unit-testable against fixtures.
    """
    if not current:
        return {}
    latest_month = max(row.month for row in current)
    latest = {row.currency: row.total_minor for row in current if row.month == latest_month}
    previous = {row.currency: row.total_minor for row in current if row.month == previous_month}
    currencies = set(latest) | set(previous)
    return {ccy: latest.get(ccy, 0) - previous.get(ccy, 0) for ccy in currencies}


def _apply_common_filters[S: Select[Any]](
    stmt: S,
    *,
    type: TransactionType | None,
    date_from: date | None,
    date_to: date | None,
    is_recurring: bool | None = None,
) -> S:
    if type is not None:
        stmt = stmt.where(Transaction.type == type)
    if date_from is not None:
        stmt = stmt.where(Transaction.occurred_on >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.occurred_on <= date_to)
    if is_recurring is not None:
        stmt = stmt.where(Transaction.is_recurring.is_(is_recurring))
    return stmt
