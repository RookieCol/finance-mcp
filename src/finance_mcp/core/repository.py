"""CRUD against transactions/categories/budgets/alert_events.

Synchronous SQLAlchemy sessions throughout — the MCP server (stdio,
one-call-at-a-time) and the scheduler are naturally synchronous, and the
web UI (Stage 6) can dispatch these to a thread pool rather than forcing
an async ORM layer this project doesn't otherwise need.

Every write here also appends to ``audit_log`` in the same transaction —
audit entries are not a best-effort side effect, they're part of the
write.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_mcp.core.models import (
    AlertEvent,
    AlertSeverity,
    AuditAction,
    AuditActor,
    AuditLog,
    Budget,
    Category,
    CategoryType,
    Transaction,
    TransactionType,
)
from finance_mcp.core.validation import ValidTransaction


def create_transaction(
    session: Session,
    tx: ValidTransaction,
    *,
    source: str,
    actor: AuditActor,
    raw_input: str | None = None,
    idempotency_key: str | None = None,
) -> Transaction:
    """Insert a transaction; if ``idempotency_key`` matches an existing
    (non-deleted) row, returns that row unchanged instead of inserting —
    LLM/chat retries are a real duplicate risk this guards against.
    """
    if idempotency_key:
        existing = session.scalar(
            select(Transaction).where(
                Transaction.idempotency_key == idempotency_key,
                Transaction.deleted_at.is_(None),
            )
        )
        if existing is not None:
            return existing

    row = Transaction(
        type=tx.type,
        amount_minor=tx.amount_minor,
        currency=tx.currency,
        occurred_on=tx.occurred_on,
        description=tx.description,
        category=tx.category,
        is_recurring=tx.is_recurring,
        source=source,
        raw_input=raw_input,
        idempotency_key=idempotency_key,
    )
    session.add(row)
    session.flush()  # populate row.id for the audit entry below

    session.add(
        AuditLog(
            entity="transaction",
            entity_id=row.id,
            action=AuditAction.create,
            changed_fields={"new": _snapshot(row)},
            actor_source=actor,
        )
    )
    return row


def update_transaction(
    session: Session, transaction_id: uuid.UUID, *, actor: AuditActor, **fields: object
) -> Transaction | None:
    row = session.get(Transaction, transaction_id)
    if row is None or row.deleted_at is not None:
        return None

    before = _snapshot(row)
    for key, value in fields.items():
        setattr(row, key, value)
    session.flush()

    session.add(
        AuditLog(
            entity="transaction",
            entity_id=row.id,
            action=AuditAction.update,
            changed_fields={"before": before, "after": _snapshot(row)},
            actor_source=actor,
        )
    )
    return row


def soft_delete_transaction(
    session: Session, transaction_id: uuid.UUID, *, actor: AuditActor
) -> bool:
    row = session.get(Transaction, transaction_id)
    if row is None or row.deleted_at is not None:
        return False

    before = _snapshot(row)
    row.deleted_at = datetime.now()
    session.flush()

    session.add(
        AuditLog(
            entity="transaction",
            entity_id=row.id,
            action=AuditAction.delete,
            changed_fields={"before": before, "after": _snapshot(row)},
            actor_source=actor,
        )
    )
    return True


def list_transactions(
    session: Session,
    *,
    type: TransactionType | None = None,
    category: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
) -> Sequence[Transaction]:
    stmt = select(Transaction).where(Transaction.deleted_at.is_(None))
    if type is not None:
        stmt = stmt.where(Transaction.type == type)
    if category is not None:
        stmt = stmt.where(Transaction.category == category)
    if date_from is not None:
        stmt = stmt.where(Transaction.occurred_on >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.occurred_on <= date_to)
    stmt = stmt.order_by(Transaction.occurred_on.desc()).limit(limit)
    return session.scalars(stmt).all()


def list_categories(session: Session, *, type: CategoryType | None = None) -> Sequence[Category]:
    stmt = select(Category)
    if type is not None:
        stmt = stmt.where(Category.type == type)
    return session.scalars(stmt.order_by(Category.key)).all()


def list_active_budgets(session: Session) -> Sequence[Budget]:
    return session.scalars(select(Budget).where(Budget.active.is_(True))).all()


def list_budgets(session: Session) -> Sequence[Budget]:
    return session.scalars(select(Budget).order_by(Budget.category)).all()


def create_budget(
    session: Session, *, category: str, monthly_limit_minor: int, currency: str = "USD"
) -> Budget:
    row = Budget(category=category, monthly_limit_minor=monthly_limit_minor, currency=currency)
    session.add(row)
    session.flush()
    return row


def delete_budget(session: Session, budget_id: uuid.UUID) -> bool:
    row = session.get(Budget, budget_id)
    if row is None:
        return False
    session.delete(row)
    return True


def update_budget(
    session: Session,
    budget_id: uuid.UUID,
    *,
    monthly_limit_minor: int | None = None,
    active: bool | None = None,
) -> Budget | None:
    row = session.get(Budget, budget_id)
    if row is None:
        return None
    if monthly_limit_minor is not None:
        row.monthly_limit_minor = monthly_limit_minor
    if active is not None:
        row.active = active
    session.flush()
    return row


def list_alerts(session: Session, *, limit: int = 100) -> Sequence[AlertEvent]:
    return session.scalars(
        select(AlertEvent).order_by(AlertEvent.detected_at.desc()).limit(limit)
    ).all()


def get_transaction(session: Session, transaction_id: uuid.UUID) -> Transaction | None:
    row = session.get(Transaction, transaction_id)
    if row is None or row.deleted_at is not None:
        return None
    return row


def get_transaction_history(session: Session, transaction_id: uuid.UUID) -> Sequence[AuditLog]:
    return session.scalars(
        select(AuditLog)
        .where(AuditLog.entity == "transaction", AuditLog.entity_id == transaction_id)
        .order_by(AuditLog.at)
    ).all()


def list_open_alerts_for_rules(session: Session, rules: Sequence[str]) -> Sequence[AlertEvent]:
    return session.scalars(select(AlertEvent).where(AlertEvent.rule.in_(rules))).all()


def get_open_alert(session: Session, dedup_key: str) -> AlertEvent | None:
    """An "open" alert is one that hasn't been resolved by superseding it —
    we treat "already has an undelivered or recently-delivered event with
    this dedup_key" as "don't fire again"; callers decide what counts as
    stale enough to re-fire (Stage 7 scheduler).
    """
    return session.scalar(select(AlertEvent).where(AlertEvent.dedup_key == dedup_key))


def create_alert_event(
    session: Session,
    *,
    rule: str,
    severity: AlertSeverity,
    payload: dict[str, object],
    dedup_key: str,
) -> AlertEvent:
    row = AlertEvent(rule=rule, severity=severity, payload=payload, dedup_key=dedup_key)
    session.add(row)
    session.flush()
    return row


def mark_alert_delivered(session: Session, alert_id: uuid.UUID) -> None:
    row = session.get(AlertEvent, alert_id)
    if row is not None:
        row.delivered_at = datetime.now()


def delete_alert_event(session: Session, dedup_key: str) -> None:
    """Clears a dedup key so its rule can fire again — used when a
    condition resolves (e.g. spend drops back under budget) so the next
    genuine breach isn't silently swallowed by a stale dedup entry.
    """
    existing = get_open_alert(session, dedup_key)
    if existing is not None:
        session.delete(existing)


def _snapshot(row: Transaction) -> dict[str, object]:
    return {
        "type": row.type.value,
        "amount_minor": row.amount_minor,
        "currency": row.currency,
        "occurred_on": row.occurred_on.isoformat(),
        "description": row.description,
        "category": row.category,
        "is_recurring": row.is_recurring,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }
