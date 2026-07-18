"""SQLAlchemy models — the single source of truth for the schema (Alembic
autogenerates migrations from ``Base.metadata``).

Money-handling rule (see README "why MCP" / fintech engineering research):
amounts are stored as **integer minor units** (``amount_minor``, e.g. cents)
paired with an ISO 4217 currency code. Never a float anywhere in this
pipeline — Python-side arithmetic uses ints/``Decimal`` only, and
aggregations never sum across differing currencies.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Enum as SAEnum


class Base(DeclarativeBase):
    pass


class TransactionType(StrEnum):
    income = "income"
    expense = "expense"


class TransactionSource(StrEnum):
    chat = "chat"
    attachment = "attachment"
    ui = "ui"


class CategoryType(StrEnum):
    income = "income"
    expense = "expense"


class AuditAction(StrEnum):
    create = "create"
    update = "update"
    delete = "delete"


class AuditActor(StrEnum):
    chat = "chat"
    ui = "ui"
    scheduler = "scheduler"


class AlertSeverity(StrEnum):
    info = "info"
    warning = "warning"
    critical = "critical"


class Category(Base):
    """Seeded taxonomy — see finanzas-saas.md for the accounting rationale.

    Expense: cogs, sales, marketing, rd, ga.
    Income: subscription, services, other.
    """

    __tablename__ = "categories"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    type: Mapped[CategoryType] = mapped_column(SAEnum(CategoryType, name="category_type"))
    label: Mapped[str] = mapped_column(String(64))


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type: Mapped[TransactionType] = mapped_column(SAEnum(TransactionType, name="transaction_type"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    occurred_on: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(ForeignKey("categories.key"))
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[TransactionSource] = mapped_column(
        SAEnum(TransactionSource, name="transaction_source")
    )
    raw_input: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("length(currency) = 3", name="ck_transactions_currency_iso4217_len"),
    )


class AuditLog(Base):
    """Append-only audit trail. No update/delete grants at the DB-role level
    (enforced in Stage 10 deployment config) — this table is a legal record
    of what changed, not application state to be corrected in place.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[uuid.UUID] = mapped_column()
    action: Mapped[AuditAction] = mapped_column(SAEnum(AuditAction, name="audit_action"))
    changed_fields: Mapped[dict[str, object]] = mapped_column(JSONB)
    actor_source: Mapped[AuditActor] = mapped_column(SAEnum(AuditActor, name="audit_actor"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(ForeignKey("categories.key"))
    monthly_limit_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (CheckConstraint("monthly_limit_minor > 0", name="ck_budgets_limit_positive"),)


class AlertEvent(Base):
    """Outbox/audit of proactive findings — dedup point for both the
    internal scheduler and Hermes cron delivery paths (Stage 7).
    """

    __tablename__ = "alert_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    rule: Mapped[str] = mapped_column(String(64))
    severity: Mapped[AlertSeverity] = mapped_column(SAEnum(AlertSeverity, name="alert_severity"))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Rule-level dedup key: prevents re-firing the same finding before it's
    # resolved (e.g. one open "budget overrun: marketing" event at a time).
    dedup_key: Mapped[str] = mapped_column(String(200), unique=True)
