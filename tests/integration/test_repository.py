from datetime import date

from sqlalchemy.orm import Session

from caudal.core import repository
from caudal.core.models import AuditAction, AuditActor, TransactionType
from caudal.core.validation import ValidTransaction

from .conftest import requires_docker

pytestmark = requires_docker


def _valid_expense(**overrides: object) -> ValidTransaction:
    defaults: dict[str, object] = {
        "type": TransactionType.expense,
        "amount_minor": 5000,
        "currency": "USD",
        "occurred_on": date(2026, 7, 17),
        "description": "AWS bill",
        "category": "cogs",
        "is_recurring": False,
    }
    defaults.update(overrides)
    return ValidTransaction(**defaults)  # type: ignore[arg-type]


def test_create_transaction_persists_and_audits(db_session: Session) -> None:
    row = repository.create_transaction(
        db_session, _valid_expense(), source="chat", actor=AuditActor.chat
    )
    db_session.flush()

    assert row.id is not None
    fetched = list(repository.list_transactions(db_session))
    assert any(t.id == row.id for t in fetched)

    audit_rows = db_session.query(repository.AuditLog).filter_by(entity_id=row.id).all()
    assert len(audit_rows) == 1
    assert audit_rows[0].action == AuditAction.create


def test_create_transaction_is_idempotent(db_session: Session) -> None:
    first = repository.create_transaction(
        db_session,
        _valid_expense(),
        source="chat",
        actor=AuditActor.chat,
        idempotency_key="retry-key-1",
    )
    second = repository.create_transaction(
        db_session,
        _valid_expense(),
        source="chat",
        actor=AuditActor.chat,
        idempotency_key="retry-key-1",
    )
    assert first.id == second.id

    all_rows = list(repository.list_transactions(db_session))
    matching = [t for t in all_rows if t.idempotency_key == "retry-key-1"]
    assert len(matching) == 1


def test_soft_delete_excludes_from_listing_but_keeps_audit_trail(db_session: Session) -> None:
    row = repository.create_transaction(
        db_session, _valid_expense(), source="ui", actor=AuditActor.ui
    )
    db_session.flush()

    deleted = repository.soft_delete_transaction(db_session, row.id, actor=AuditActor.ui)
    assert deleted is True

    remaining = list(repository.list_transactions(db_session))
    assert all(t.id != row.id for t in remaining)

    audit_rows = db_session.query(repository.AuditLog).filter_by(entity_id=row.id).all()
    actions = {a.action for a in audit_rows}
    assert AuditAction.create in actions
    assert AuditAction.delete in actions


def test_update_transaction_records_before_and_after(db_session: Session) -> None:
    row = repository.create_transaction(
        db_session, _valid_expense(), source="ui", actor=AuditActor.ui
    )
    db_session.flush()

    updated = repository.update_transaction(
        db_session, row.id, actor=AuditActor.ui, amount_minor=7500
    )
    assert updated is not None
    assert updated.amount_minor == 7500

    audit_rows = db_session.query(repository.AuditLog).filter_by(entity_id=row.id).all()
    update_entry = next(a for a in audit_rows if a.action == AuditAction.update)
    assert update_entry.changed_fields["before"]["amount_minor"] == 5000
    assert update_entry.changed_fields["after"]["amount_minor"] == 7500


def test_list_categories_returns_seeded_taxonomy(db_session: Session) -> None:
    categories = repository.list_categories(db_session)
    keys = {c.key for c in categories}
    assert {"cogs", "sales", "marketing", "rd", "ga", "subscription", "services", "other"} == keys
