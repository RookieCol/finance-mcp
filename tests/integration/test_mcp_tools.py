"""Integration tests calling the MCP tools exactly as a client (Hermes)
would, via `mcp.call_tool` — not by importing and calling the underlying
Python functions directly. This is what catches schema-level bugs a unit
test on the plain function would miss (see the missing-required-field
fix below).
"""

import pytest

from caudal.mcp_server.server import mcp

from .conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.usefixtures("mcp_env")]


async def _call(name: str, **arguments: object) -> dict:
    _content, structured = await mcp.call_tool(name, arguments)
    assert isinstance(structured, dict)
    return structured


async def test_record_transaction_happy_path() -> None:
    result = await _call(
        "record_transaction",
        type="expense",
        amount="50.00",
        occurred_on="2026-07-17",
        description="AWS bill",
        category="cogs",
    )
    assert result["status"] == "ok"
    assert "transaction_id" in result


async def test_record_transaction_missing_field_asks_for_clarification_not_a_hard_error() -> None:
    """Regression test: amount/type/etc. must NOT be schema-required MCP
    arguments, or a client omitting one gets a raw ToolError instead of
    our structured clarification_needed response — which defeats the
    entire ask-before-guessing design.
    """
    result = await _call(
        "record_transaction",
        type="expense",
        occurred_on="2026-07-17",
        description="AWS bill",
        category="cogs",
    )
    assert result["status"] == "clarification_needed"
    assert "amount" in result["missing"]


async def test_record_transaction_is_idempotent_over_mcp() -> None:
    first = await _call(
        "record_transaction",
        type="expense",
        amount="10.00",
        occurred_on="2026-07-17",
        description="retry test",
        category="cogs",
        idempotency_key="dup-1",
    )
    second = await _call(
        "record_transaction",
        type="expense",
        amount="10.00",
        occurred_on="2026-07-17",
        description="retry test",
        category="cogs",
        idempotency_key="dup-1",
    )
    assert first["transaction_id"] == second["transaction_id"]


async def test_list_categories_returns_taxonomy() -> None:
    result = await _call("list_categories")
    keys = {c["key"] for c in result["categories"]}
    assert "cogs" in keys
    assert "subscription" in keys


async def test_full_flow_record_list_totals_digest() -> None:
    await _call(
        "record_transaction",
        type="income",
        amount="1000.00",
        currency="COP",
        occurred_on="2026-07-01",
        description="July invoice",
        category="subscription",
        is_recurring=True,
    )
    await _call(
        "record_transaction",
        type="expense",
        amount="200.00",
        currency="COP",
        occurred_on="2026-07-02",
        description="hosting",
        category="cogs",
        is_recurring=True,
    )

    listed = await _call("list_transactions")
    assert len(listed["transactions"]) == 2

    totals = await _call("get_totals", group_by="category")
    by_category = {t["category"]: t["amount"] for t in totals["totals"]}
    assert by_category["subscription"] == "1000.00"
    assert by_category["cogs"] == "200.00"

    projections = await _call("get_projections", months_ahead=2)
    assert projections["assumptions"]["recurring_income"] == "1000.00"
    assert projections["assumptions"]["recurring_expense"] == "200.00"

    digest = await _call("get_digest")
    assert digest["status"] == "ok"
    assert len(digest["totals_by_category"]) == 2


async def test_update_transaction_persists_change() -> None:
    created = await _call(
        "record_transaction",
        type="expense",
        amount="50.00",
        occurred_on="2026-07-17",
        description="AWS bill",
        category="cogs",
    )
    updated = await _call(
        "update_transaction", transaction_id=created["transaction_id"], amount="75.00"
    )
    assert updated["status"] == "ok"

    listed = await _call("list_transactions")
    row = next(t for t in listed["transactions"] if t["id"] == created["transaction_id"])
    assert row["amount"] == "75.00"


async def test_update_transaction_unknown_id_returns_structured_error() -> None:
    result = await _call(
        "update_transaction",
        transaction_id="00000000-0000-0000-0000-000000000000",
        amount="1.00",
    )
    assert result["status"] == "error"
