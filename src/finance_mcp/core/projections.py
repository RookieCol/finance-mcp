"""Deterministic forecasting engine — no LLM involved.

Split into pure math functions (hand-verifiable against fixtures — see
tests/unit/test_projections.py) and a thin orchestrator that pulls the
required historical series via ``core.reporting`` / ``core.repository``.
Every result carries the assumptions it was computed from, so callers
(chat/UI) can show *why* a number is what it is, not just the number.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from finance_mcp.core import reporting
from finance_mcp.core.models import TransactionType

DEFAULT_TREND_WINDOW_MONTHS = 3


# --- Pure math -------------------------------------------------------------


def moving_average(values: list[int]) -> float:
    """Arithmetic mean of the trailing window the caller has already
    sliced. Returns 0.0 for an empty series (no history => no base).
    """
    if not values:
        return 0.0
    return sum(values) / len(values)


def linear_trend_slope(values: list[int]) -> float:
    """Least-squares slope of ``values`` treated as y at x = 0..n-1.

    Returns 0.0 for fewer than two points (flat: no trend can be inferred).
    """
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values, strict=True))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    return numerator / denominator


def forecast_monthly_net(
    *,
    recurring_income_minor: int,
    recurring_expense_minor: int,
    historical_non_recurring_net_minor: list[int],
    months_ahead: int,
    trend_window: int = DEFAULT_TREND_WINDOW_MONTHS,
) -> list[int]:
    """Project net cash flow (income - expense, minor units) for each of
    the next ``months_ahead`` months: recurring base + a trend-extrapolated
    non-recurring component from the trailing ``trend_window`` months of
    history.
    """
    recurring_net = recurring_income_minor - recurring_expense_minor
    window = historical_non_recurring_net_minor[-trend_window:]
    base = moving_average(window)
    slope = linear_trend_slope(window)

    forecast = []
    for month_offset in range(1, months_ahead + 1):
        trend_component = base + slope * month_offset
        forecast.append(round(recurring_net + trend_component))
    return forecast


def runway_months(cash_balance_minor: int, monthly_net_burn_minor: float) -> float | None:
    """Months of runway at the current net burn rate.

    Returns ``None`` when burn is <= 0 (net income is flat or growing —
    runway is not a meaningful/finite number in that case), matching the
    formula documented in finanzas-saas.md.
    """
    if monthly_net_burn_minor <= 0:
        return None
    return cash_balance_minor / monthly_net_burn_minor


def growth_rate(current_minor: int, previous_minor: int) -> float | None:
    """Month-over-month (or any two-period) growth rate as a fraction,
    e.g. 0.05 == +5%. Returns ``None`` when the previous period is zero
    (division is undefined, not "infinite growth").
    """
    if previous_minor == 0:
        return None
    return (current_minor - previous_minor) / previous_minor


# --- Orchestration -----------------------------------------------------


@dataclass(frozen=True)
class ProjectionAssumptions:
    trend_window_months: int
    historical_months_used: list[str]
    recurring_income_minor: int
    recurring_expense_minor: int


@dataclass(frozen=True)
class ProjectionResult:
    monthly_net_forecast_minor: list[int]
    runway_months: float | None
    mrr_growth_rate: float | None
    assumptions: ProjectionAssumptions


def compute_projections(
    session: Session,
    *,
    months_ahead: int = 3,
    cash_balance_minor: int = 0,
    as_of: date | None = None,
    trend_window: int = DEFAULT_TREND_WINDOW_MONTHS,
) -> ProjectionResult:
    as_of = as_of or date.today()

    recurring_income = sum(
        row.total_minor
        for row in reporting.totals_by_category(
            session, type=TransactionType.income, is_recurring=True
        )
    )
    recurring_expense = sum(
        row.total_minor
        for row in reporting.totals_by_category(
            session, type=TransactionType.expense, is_recurring=True
        )
    )

    # Unfiltered totals (recurring + non-recurring) — used for MRR growth,
    # where recurring revenue should count.
    income_by_month = {
        row.month: row.total_minor
        for row in reporting.totals_by_month(session, type=TransactionType.income)
    }

    # Non-recurring-only totals for the trend component — recurring income
    # and expense are already counted once via recurring_income/
    # recurring_expense above; including them again here would double-count
    # them in the forecast.
    non_recurring_income_by_month = {
        row.month: row.total_minor
        for row in reporting.totals_by_month(
            session, type=TransactionType.income, is_recurring=False
        )
    }
    non_recurring_expense_by_month = {
        row.month: row.total_minor
        for row in reporting.totals_by_month(
            session, type=TransactionType.expense, is_recurring=False
        )
    }
    income_months = sorted(income_by_month)
    non_recurring_months = sorted(
        set(non_recurring_income_by_month) | set(non_recurring_expense_by_month)
    )
    historical_net = [
        non_recurring_income_by_month.get(m, 0) - non_recurring_expense_by_month.get(m, 0)
        for m in non_recurring_months
    ]

    forecast = forecast_monthly_net(
        recurring_income_minor=recurring_income,
        recurring_expense_minor=recurring_expense,
        historical_non_recurring_net_minor=historical_net,
        months_ahead=months_ahead,
        trend_window=trend_window,
    )

    avg_projected_burn = -moving_average(forecast) if forecast else 0.0
    runway = runway_months(cash_balance_minor, avg_projected_burn)

    mrr_growth = None
    if len(income_months) >= 2:
        current_month_income = income_by_month[income_months[-1]]
        previous_month_income = income_by_month[income_months[-2]]
        mrr_growth = growth_rate(current_month_income, previous_month_income)

    return ProjectionResult(
        monthly_net_forecast_minor=forecast,
        runway_months=runway,
        mrr_growth_rate=mrr_growth,
        assumptions=ProjectionAssumptions(
            trend_window_months=trend_window,
            historical_months_used=non_recurring_months[-trend_window:],
            recurring_income_minor=recurring_income,
            recurring_expense_minor=recurring_expense,
        ),
    )
