from caudal.core.models import TransactionType
from caudal.core.validation import TransactionInput, validate_transaction


def test_valid_expense_produces_no_issues() -> None:
    result = validate_transaction(
        TransactionInput(
            type="expense",
            amount="50.00",
            currency="usd",
            occurred_on="2026-07-17",
            description="AWS bill",
            category="cogs",
        )
    )
    assert result.is_valid
    assert result.transaction is not None
    assert result.transaction.type == TransactionType.expense
    assert result.transaction.amount_minor == 5000
    assert result.transaction.currency == "USD"


def test_amount_is_never_a_float_and_rounds_to_exact_cents() -> None:
    result = validate_transaction(
        TransactionInput(
            type="income",
            amount="19.99",
            occurred_on="2026-07-17",
            description="Subscription",
            category="subscription",
        )
    )
    assert result.transaction is not None
    assert result.transaction.amount_minor == 1999
    assert isinstance(result.transaction.amount_minor, int)


def test_missing_amount_yields_clarification_issue_not_a_crash() -> None:
    result = validate_transaction(
        TransactionInput(type="expense", occurred_on="2026-07-17", description="?", category="cogs")
    )
    assert not result.is_valid
    assert any(issue.field == "amount" for issue in result.issues)


def test_negative_amount_is_rejected() -> None:
    result = validate_transaction(
        TransactionInput(
            type="expense",
            amount="-10",
            occurred_on="2026-07-17",
            description="refund?",
            category="cogs",
        )
    )
    assert not result.is_valid
    assert any(issue.field == "amount" for issue in result.issues)


def test_category_must_match_transaction_type_taxonomy() -> None:
    result = validate_transaction(
        TransactionInput(
            type="expense",
            amount="10",
            occurred_on="2026-07-17",
            description="oops",
            category="subscription",  # income-only category
        )
    )
    assert not result.is_valid
    assert any(issue.field == "category" for issue in result.issues)


def test_invalid_date_format_is_rejected() -> None:
    result = validate_transaction(
        TransactionInput(
            type="expense",
            amount="10",
            occurred_on="17/07/2026",
            description="oops",
            category="cogs",
        )
    )
    assert not result.is_valid
    assert any(issue.field == "occurred_on" for issue in result.issues)


def test_currency_defaults_to_usd_when_omitted() -> None:
    result = validate_transaction(
        TransactionInput(
            type="expense", amount="10", occurred_on="2026-07-17", description="x", category="cogs"
        )
    )
    assert result.transaction is not None
    assert result.transaction.currency == "USD"


def test_multiple_missing_fields_all_reported_at_once() -> None:
    result = validate_transaction(TransactionInput())
    fields = {issue.field for issue in result.issues}
    assert {"type", "amount", "occurred_on", "description", "category"} <= fields
