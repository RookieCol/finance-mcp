"""Property-based tests on the money paths — the highest-leverage test
class in a finance codebase: instead of hand-picked examples, Hypothesis
generates hundreds of cases per run, which is what actually catches the
class of bug real money code fails on (rounding, precision loss, sign
errors) rather than just the cases a human happened to think of.
"""

from datetime import date
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from finance_mcp.core.projections import growth_rate, moving_average, runway_months
from finance_mcp.core.validation import TransactionInput, validate_transaction

# Two decimal places, always positive, capped well under overflow ranges.
money_strings = st.decimals(
    min_value=Decimal("0.01"), max_value=Decimal("999999.99"), places=2
).map(str)


@given(money_strings)
def test_validated_amount_is_always_an_exact_integer_number_of_cents(amount: str) -> None:
    result = validate_transaction(
        TransactionInput(
            type="expense",
            amount=amount,
            occurred_on="2026-07-17",
            description="x",
            category="cogs",
        )
    )
    assert result.transaction is not None
    assert isinstance(result.transaction.amount_minor, int)
    # Round-tripping back to a decimal string must reproduce the input
    # exactly — no float ever touched this value.
    reconstructed = Decimal(result.transaction.amount_minor) / 100
    assert reconstructed == Decimal(amount)


@given(st.integers(min_value=-10_000_000, max_value=10_000_000))
def test_negative_or_zero_amount_is_always_rejected(cents: int) -> None:
    amount = str(Decimal(cents) / 100)
    result = validate_transaction(
        TransactionInput(
            type="expense",
            amount=amount,
            occurred_on="2026-07-17",
            description="x",
            category="cogs",
        )
    )
    if cents <= 0:
        assert not result.is_valid
    else:
        assert result.is_valid


@given(st.lists(st.integers(min_value=-1_000_000, max_value=1_000_000), min_size=0, max_size=12))
def test_moving_average_of_a_list_of_ints_is_always_within_its_bounds(values: list[int]) -> None:
    avg = moving_average(values)
    if values:
        assert min(values) <= avg <= max(values)
    else:
        assert avg == 0.0


@given(
    st.integers(min_value=1, max_value=10_000_000),
    st.floats(min_value=0.01, max_value=1_000_000, allow_nan=False, allow_infinity=False),
)
def test_runway_months_is_never_negative_when_burning_cash(cash_minor: int, burn: float) -> None:
    result = runway_months(cash_minor, burn)
    assert result is not None
    assert result >= 0


@given(
    st.integers(min_value=-10_000_000, max_value=10_000_000),
    st.integers(min_value=1, max_value=10_000_000),
)
def test_growth_rate_matches_its_algebraic_definition(current: int, previous: int) -> None:
    rate = growth_rate(current, previous)
    assert rate is not None
    assert rate == (current - previous) / previous


@given(money_strings)
def test_amount_parsing_never_produces_a_python_float(amount: str) -> None:
    """Floats are the one type explicitly banned for money throughout
    this codebase — this asserts it holds across generated inputs, not
    just the hand-picked examples in test_validation.py.
    """
    result = validate_transaction(
        TransactionInput(
            type="income",
            amount=amount,
            occurred_on=date(2026, 7, 17).isoformat(),
            description="x",
            category="subscription",
        )
    )
    assert result.transaction is not None
    assert not isinstance(result.transaction.amount_minor, float)
