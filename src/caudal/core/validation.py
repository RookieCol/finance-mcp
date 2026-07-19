"""Shared validation for transaction input — consumed by both the MCP
clarification flow (Stage 5) and the internal UI's form-error display
(Stage 6), so a transaction created via chat and one entered by hand are
governed by identical rules.

No floats anywhere: amounts are validated and normalized to integer minor
units before ever reaching ``core.repository``.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from caudal.core.models import TransactionType

VALID_EXPENSE_CATEGORIES = {"cogs", "sales", "marketing", "rd", "ga"}
VALID_INCOME_CATEGORIES = {"subscription", "services", "other"}
VALID_CURRENCY_LENGTH = 3


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str


@dataclass(frozen=True)
class TransactionInput:
    """Raw, not-yet-validated fields as they might arrive from chat or a
    UI form — everything optional, since "missing/ambiguous" is exactly
    what validation needs to detect.
    """

    type: str | None = None
    amount: str | None = None  # decimal string, e.g. "50.00" — never a float
    currency: str | None = None
    occurred_on: str | None = None  # ISO date string
    description: str | None = None
    category: str | None = None
    is_recurring: bool = False


@dataclass(frozen=True)
class ValidTransaction:
    type: TransactionType
    amount_minor: int
    currency: str
    occurred_on: date
    description: str
    category: str
    is_recurring: bool = False


@dataclass(frozen=True)
class ValidationResult:
    transaction: ValidTransaction | None
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.transaction is not None and not self.issues


def validate_transaction(raw: TransactionInput) -> ValidationResult:
    issues: list[ValidationIssue] = []

    tx_type = _validate_type(raw.type, issues)
    amount_minor = _validate_amount(raw.amount, issues)
    currency = _validate_currency(raw.currency, issues)
    occurred_on = _validate_date(raw.occurred_on, issues)
    description = _validate_description(raw.description, issues)
    category = _validate_category(raw.category, tx_type, issues)

    if issues or tx_type is None or amount_minor is None or currency is None:
        return ValidationResult(transaction=None, issues=issues)
    if occurred_on is None or description is None or category is None:
        return ValidationResult(transaction=None, issues=issues)

    return ValidationResult(
        transaction=ValidTransaction(
            type=tx_type,
            amount_minor=amount_minor,
            currency=currency,
            occurred_on=occurred_on,
            description=description,
            category=category,
            is_recurring=raw.is_recurring,
        ),
        issues=[],
    )


def _validate_type(value: str | None, issues: list[ValidationIssue]) -> TransactionType | None:
    if not value:
        issues.append(ValidationIssue("type", "Missing: is this income or an expense?"))
        return None
    try:
        return TransactionType(value)
    except ValueError:
        issues.append(
            ValidationIssue("type", f"Invalid type '{value}' — must be 'income' or 'expense'")
        )
        return None


def _validate_amount(value: str | None, issues: list[ValidationIssue]) -> int | None:
    if not value:
        issues.append(ValidationIssue("amount", "Missing: what was the amount?"))
        return None
    try:
        decimal_amount = Decimal(value)
    except InvalidOperation:
        issues.append(ValidationIssue("amount", f"Invalid amount '{value}' — not a number"))
        return None
    if decimal_amount <= 0:
        issues.append(ValidationIssue("amount", "Amount must be positive"))
        return None
    minor = int((decimal_amount * 100).to_integral_exact())
    return minor


def _validate_currency(value: str | None, issues: list[ValidationIssue]) -> str | None:
    currency = (value or "USD").upper()
    if len(currency) != VALID_CURRENCY_LENGTH or not currency.isalpha():
        issues.append(
            ValidationIssue(
                "currency", f"Invalid currency '{currency}' — expected ISO 4217, e.g. USD"
            )
        )
        return None
    return currency


def _validate_date(value: str | None, issues: list[ValidationIssue]) -> date | None:
    if not value:
        issues.append(ValidationIssue("occurred_on", "Missing: when did this happen?"))
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        issues.append(
            ValidationIssue("occurred_on", f"Invalid date '{value}' — expected YYYY-MM-DD")
        )
        return None


def _validate_description(value: str | None, issues: list[ValidationIssue]) -> str | None:
    description = (value or "").strip()
    if not description:
        issues.append(ValidationIssue("description", "Missing: a short description is required"))
        return None
    return description


def _validate_category(
    value: str | None, tx_type: TransactionType | None, issues: list[ValidationIssue]
) -> str | None:
    if not value:
        issues.append(ValidationIssue("category", "Missing: which category does this belong to?"))
        return None
    if tx_type is None:
        # Can't validate against a taxonomy we can't select without a type;
        # the type issue itself is already recorded by _validate_type.
        return None
    valid_set = (
        VALID_EXPENSE_CATEGORIES if tx_type == TransactionType.expense else VALID_INCOME_CATEGORIES
    )
    if value not in valid_set:
        allowed = sorted(valid_set)
        issues.append(
            ValidationIssue(
                "category",
                f"Invalid category '{value}' for {tx_type.value} — must be one of {allowed}",
            )
        )
        return None
    return value
