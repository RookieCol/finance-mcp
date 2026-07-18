"""Unit tests for the elicitation-first clarification flow
(`_try_elicit_missing_fields`), covering an elicitation-capable client
(accept/decline/cancel) and a client that doesn't support elicitation at
all — both must be handled without raising.
"""

import pytest
from mcp.server.elicitation import AcceptedElicitation, CancelledElicitation, DeclinedElicitation
from pydantic import create_model

from finance_mcp.core.validation import TransactionInput, ValidationIssue
from finance_mcp.mcp_server.server import _try_elicit_missing_fields


class _StubContext:
    def __init__(self, response: object) -> None:
        self._response = response
        self.calls: list[tuple[str, object]] = []

    async def elicit(self, message: str, schema: object) -> object:
        self.calls.append((message, schema))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


ISSUES = [ValidationIssue(field="amount", message="Missing: what was the amount?")]
RAW = TransactionInput(
    type="expense", occurred_on="2026-07-17", description="AWS bill", category="cogs"
)


@pytest.mark.asyncio
async def test_elicitation_accepted_fills_in_the_missing_field() -> None:
    AmountModel = create_model("AmountModel", amount=(str, ...))
    accepted = AcceptedElicitation(data=AmountModel(amount="50.00"))
    ctx = _StubContext(accepted)

    result = await _try_elicit_missing_fields(ctx, RAW, ISSUES)  # type: ignore[arg-type]

    assert result is not None
    assert result.amount == "50.00"
    # Everything else from the original input is preserved.
    assert result.description == "AWS bill"
    assert len(ctx.calls) == 1


@pytest.mark.asyncio
async def test_elicitation_declined_falls_back_to_none() -> None:
    ctx = _StubContext(DeclinedElicitation())
    result = await _try_elicit_missing_fields(ctx, RAW, ISSUES)  # type: ignore[arg-type]
    assert result is None


@pytest.mark.asyncio
async def test_elicitation_cancelled_falls_back_to_none() -> None:
    ctx = _StubContext(CancelledElicitation())
    result = await _try_elicit_missing_fields(ctx, RAW, ISSUES)  # type: ignore[arg-type]
    assert result is None


@pytest.mark.asyncio
async def test_client_without_elicitation_support_falls_back_without_raising() -> None:
    """A client that never declared the elicitation capability will
    error on the request (varies by transport/client); this must be
    swallowed, not propagated as a tool failure.
    """
    ctx = _StubContext(RuntimeError("client does not support elicitation/create"))
    result = await _try_elicit_missing_fields(ctx, RAW, ISSUES)  # type: ignore[arg-type]
    assert result is None
