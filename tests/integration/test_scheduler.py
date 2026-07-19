from datetime import date

from sqlalchemy.orm import Session

from caudal.core import repository
from caudal.core.models import AuditActor, Budget, TransactionType
from caudal.core.validation import ValidTransaction
from caudal.scheduler.jobs import run_alert_check, run_weekly_digest

from .conftest import requires_docker

pytestmark = requires_docker


class _RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, title: str, body: str) -> None:
        self.sent.append((title, body))


def _expense_tx(**overrides: object) -> ValidTransaction:
    defaults: dict[str, object] = {
        "type": TransactionType.expense,
        "amount_minor": 1200,
        "currency": "USD",
        "occurred_on": date(2026, 7, 5),
        "description": "over budget",
        "category": "marketing",
        "is_recurring": False,
    }
    defaults.update(overrides)
    return ValidTransaction(**defaults)  # type: ignore[arg-type]


def test_run_alert_check_delivers_new_findings(db_session: Session) -> None:
    db_session.add(Budget(category="marketing", monthly_limit_minor=1000, currency="USD"))
    repository.create_transaction(db_session, _expense_tx(), source="ui", actor=AuditActor.ui)
    db_session.flush()

    notifier = _RecordingNotifier()
    findings = run_alert_check(
        db_session, notifier, cash_balance_minor=1_000_000, as_of=date(2026, 7, 17)
    )

    assert len(findings) == 1
    assert len(notifier.sent) == 1
    assert "budget_overrun" in notifier.sent[0][0]


def test_run_alert_check_does_not_redeliver_on_second_run(db_session: Session) -> None:
    db_session.add(Budget(category="marketing", monthly_limit_minor=1000, currency="USD"))
    repository.create_transaction(db_session, _expense_tx(), source="ui", actor=AuditActor.ui)
    db_session.flush()

    notifier = _RecordingNotifier()
    run_alert_check(db_session, notifier, cash_balance_minor=1_000_000, as_of=date(2026, 7, 17))
    run_alert_check(db_session, notifier, cash_balance_minor=1_000_000, as_of=date(2026, 7, 18))

    assert len(notifier.sent) == 1  # dedup: no second delivery for the same finding


def test_run_weekly_digest_always_sends_and_includes_totals(db_session: Session) -> None:
    repository.create_transaction(
        db_session,
        _expense_tx(amount_minor=500, description="hosting"),
        source="ui",
        actor=AuditActor.ui,
    )
    db_session.flush()

    notifier = _RecordingNotifier()
    body = run_weekly_digest(db_session, notifier)

    assert len(notifier.sent) == 1
    assert "marketing" in body
    assert "5.00" in body
