from datetime import date

from sqlalchemy.orm import Session

from caudal.core import alerts, projections, reporting, repository
from caudal.core.models import AuditActor, Budget, TransactionType
from caudal.core.validation import ValidTransaction

from .conftest import requires_docker

pytestmark = requires_docker


def _tx(**overrides: object) -> ValidTransaction:
    defaults: dict[str, object] = {
        "type": TransactionType.expense,
        "amount_minor": 1000,
        "currency": "USD",
        "occurred_on": date(2026, 7, 1),
        "description": "test",
        "category": "marketing",
        "is_recurring": False,
    }
    defaults.update(overrides)
    return ValidTransaction(**defaults)  # type: ignore[arg-type]


def test_totals_by_category_sums_correctly(db_session: Session) -> None:
    repository.create_transaction(
        db_session, _tx(amount_minor=1000), source="ui", actor=AuditActor.ui
    )
    repository.create_transaction(
        db_session, _tx(amount_minor=500), source="ui", actor=AuditActor.ui
    )
    db_session.flush()

    totals = reporting.totals_by_category(db_session, type=TransactionType.expense)
    marketing = next(t for t in totals if t.category == "marketing")
    assert marketing.total_minor == 1500


def test_net_totals_by_month_subtracts_expense_from_income(db_session: Session) -> None:
    repository.create_transaction(
        db_session,
        _tx(type=TransactionType.income, amount_minor=10000, category="subscription"),
        source="ui",
        actor=AuditActor.ui,
    )
    repository.create_transaction(
        db_session,
        _tx(type=TransactionType.expense, amount_minor=3000),
        source="ui",
        actor=AuditActor.ui,
    )
    db_session.flush()

    totals = reporting.net_totals_by_month(db_session)
    row = next(t for t in totals if t.month == "2026-07")
    assert row.total_minor == 7000


def test_net_totals_by_month_is_negative_for_expense_only_month(db_session: Session) -> None:
    repository.create_transaction(
        db_session,
        _tx(type=TransactionType.expense, amount_minor=4200),
        source="ui",
        actor=AuditActor.ui,
    )
    db_session.flush()

    totals = reporting.net_totals_by_month(db_session)
    row = next(t for t in totals if t.month == "2026-07")
    assert row.total_minor == -4200


def test_latest_recurring_totals_use_only_each_categorys_most_recent_month(
    db_session: Session,
) -> None:
    # Same recurring stream paid in two consecutive months (rate changed):
    # the base must be July's 4000, not June+July summed (7000).
    repository.create_transaction(
        db_session,
        _tx(category="cogs", amount_minor=3000, is_recurring=True, occurred_on=date(2026, 6, 16)),
        source="ui",
        actor=AuditActor.ui,
    )
    repository.create_transaction(
        db_session,
        _tx(category="cogs", amount_minor=4000, is_recurring=True, occurred_on=date(2026, 7, 16)),
        source="ui",
        actor=AuditActor.ui,
    )
    # A different category whose latest recurring month is June only.
    repository.create_transaction(
        db_session,
        _tx(category="ga", amount_minor=5000, is_recurring=True, occurred_on=date(2026, 6, 30)),
        source="ui",
        actor=AuditActor.ui,
    )
    db_session.flush()

    totals = reporting.latest_recurring_totals_by_category(
        db_session, type=TransactionType.expense
    )
    by_category = {t.category: t.total_minor for t in totals}
    assert by_category == {"cogs": 4000, "ga": 5000}

    result = projections.compute_projections(db_session, as_of=date(2026, 7, 19))
    assert result.assumptions.recurring_expense_minor == 9000


def test_budget_overrun_alert_fires_and_dedupes(db_session: Session) -> None:
    db_session.add(Budget(category="marketing", monthly_limit_minor=1000, currency="USD"))
    db_session.flush()

    repository.create_transaction(
        db_session, _tx(amount_minor=1200), source="ui", actor=AuditActor.ui
    )
    db_session.flush()

    first_run = alerts.evaluate_alerts(db_session, as_of=date(2026, 7, 17))
    assert any(f.rule == "budget_overrun" for f in first_run)

    # Second run, same month, same overrun: must not re-fire (dedup).
    second_run = alerts.evaluate_alerts(db_session, as_of=date(2026, 7, 18))
    assert second_run == []


def test_budget_alert_clears_when_spend_drops_back_under_limit(db_session: Session) -> None:
    db_session.add(Budget(category="marketing", monthly_limit_minor=1000, currency="USD"))
    db_session.flush()

    over_budget_tx = repository.create_transaction(
        db_session, _tx(amount_minor=1200), source="ui", actor=AuditActor.ui
    )
    db_session.flush()
    assert any(f.rule == "budget_overrun" for f in alerts.evaluate_alerts(db_session))

    repository.soft_delete_transaction(db_session, over_budget_tx.id, actor=AuditActor.ui)
    db_session.flush()

    # Condition resolved: re-running must not leave a stale open alert
    # blocking a future genuine breach, and shouldn't report it as new.
    third_run = alerts.evaluate_alerts(db_session)
    assert third_run == []
    assert repository.get_open_alert(db_session, "budget_overrun:marketing:USD") is None


def test_compute_projections_uses_recurring_transactions_as_base(db_session: Session) -> None:
    repository.create_transaction(
        db_session,
        _tx(
            type=TransactionType.income,
            amount_minor=10000,
            category="subscription",
            is_recurring=True,
        ),
        source="ui",
        actor=AuditActor.ui,
    )
    repository.create_transaction(
        db_session,
        _tx(amount_minor=3000, category="cogs", is_recurring=True),
        source="ui",
        actor=AuditActor.ui,
    )
    db_session.flush()

    result = projections.compute_projections(
        db_session, months_ahead=2, cash_balance_minor=100_000, as_of=date(2026, 7, 17)
    )
    assert result.assumptions.recurring_income_minor == 10000
    assert result.assumptions.recurring_expense_minor == 3000
    # Net recurring = 7000/mo with no other history => forecast is flat 7000.
    assert result.monthly_net_forecast_minor == [7000, 7000]
    assert result.runway_months is None  # positive net cash flow => no burn
