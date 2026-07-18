"""Integration tests for the internal UI, driven through FastAPI's
TestClient (real HTTP request/response cycle, real Postgres) rather than
calling route functions directly.
"""

import re

import pytest
from fastapi.testclient import TestClient

from .conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.usefixtures("web_env")]


@pytest.fixture
def client() -> TestClient:
    from finance_mcp.web.app import app

    with TestClient(app) as c:
        yield c


def test_healthz_reports_ok_once_db_is_up(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_metrics_endpoint_serves_prometheus_exposition(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


def test_dashboard_renders_with_no_data(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text


def test_create_transaction_round_trip(client: TestClient) -> None:
    response = client.post(
        "/transactions/new",
        data={
            "type": "expense",
            "amount": "42.50",
            "currency": "USD",
            "occurred_on": "2026-07-17",
            "description": "Domain renewal",
            "category": "cogs",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    listing = client.get("/transactions")
    assert "Domain renewal" in listing.text
    assert "42.50" in listing.text


def test_create_transaction_invalid_submission_shows_errors_and_does_not_write(
    client: TestClient,
) -> None:
    response = client.post(
        "/transactions/new",
        data={
            "type": "expense",
            "amount": "not-a-number",
            "currency": "USD",
            "occurred_on": "2026-07-17",
            "description": "bad amount",
            "category": "cogs",
        },
    )
    assert response.status_code == 422
    assert "amount" in response.text.lower()

    listing = client.get("/transactions")
    assert "bad amount" not in listing.text


def test_edit_transaction_round_trip(client: TestClient) -> None:
    client.post(
        "/transactions/new",
        data={
            "type": "expense",
            "amount": "10.00",
            "currency": "USD",
            "occurred_on": "2026-07-17",
            "description": "to edit",
            "category": "cogs",
        },
        follow_redirects=False,
    )
    listing = client.get("/transactions")
    tx_id = _extract_transaction_id(listing.text)

    edit_response = client.post(
        f"/transactions/{tx_id}/edit",
        data={
            "type": "expense",
            "amount": "99.99",
            "currency": "USD",
            "occurred_on": "2026-07-17",
            "description": "edited",
            "category": "cogs",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code == 303

    listing_after = client.get("/transactions")
    assert "edited" in listing_after.text
    assert "99.99" in listing_after.text


def test_delete_transaction_removes_it_from_listing(client: TestClient) -> None:
    client.post(
        "/transactions/new",
        data={
            "type": "expense",
            "amount": "5.00",
            "currency": "USD",
            "occurred_on": "2026-07-17",
            "description": "to delete",
            "category": "cogs",
        },
        follow_redirects=False,
    )
    listing = client.get("/transactions")
    tx_id = _extract_transaction_id(listing.text)

    delete_response = client.post(f"/transactions/{tx_id}/delete", follow_redirects=False)
    assert delete_response.status_code == 303

    listing_after = client.get("/transactions")
    assert "to delete" not in listing_after.text


def test_budgets_page_create_and_list(client: TestClient) -> None:
    response = client.post(
        "/budgets",
        data={"category": "marketing", "monthly_limit": "1000.00", "currency": "USD"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    listing = client.get("/budgets")
    assert "marketing" in listing.text
    assert "1000.00" in listing.text


def test_alerts_page_renders_and_acknowledge_flow(client: TestClient) -> None:
    client.post(
        "/budgets",
        data={"category": "marketing", "monthly_limit": "10.00", "currency": "USD"},
        follow_redirects=False,
    )
    client.post(
        "/transactions/new",
        data={
            "type": "expense",
            "amount": "20.00",
            "currency": "USD",
            "occurred_on": "2026-07-17",
            "description": "over budget",
            "category": "marketing",
        },
        follow_redirects=False,
    )

    from finance_mcp.core import alerts, db

    with db.session_scope() as session:
        alerts.evaluate_alerts(session)

    response = client.get("/alerts")
    assert "budget_overrun" in response.text

    alert_match = re.search(r"/alerts/([0-9a-f-]{36})/acknowledge", response.text)
    assert alert_match is not None
    alert_row_id = alert_match.group(1)
    ack_response = client.post(f"/alerts/{alert_row_id}/acknowledge", follow_redirects=False)
    assert ack_response.status_code == 303


def test_shared_storage_transaction_created_via_mcp_visible_in_ui(client: TestClient) -> None:
    """Sanity check that the MCP path and the UI path really do share the
    same storage — a transaction created through the MCP tool must show
    up in the UI without any special-casing.
    """
    import asyncio

    from finance_mcp.mcp_server.server import mcp

    # No extra setup needed: the FastAPI app's lifespan already called
    # db.init_engine() with the same DATABASE_URL this fixture set, so
    # the MCP tool below writes through the identical global engine.

    async def _create() -> None:
        await mcp.call_tool(
            "record_transaction",
            {
                "type": "income",
                "amount": "100.00",
                "occurred_on": "2026-07-17",
                "description": "via mcp",
                "category": "subscription",
            },
        )

    asyncio.run(_create())

    listing = client.get("/transactions")
    assert "via mcp" in listing.text


def _extract_transaction_id(html: str) -> str:
    match = re.search(r"/transactions/([0-9a-f-]{36})/edit", html)
    assert match is not None, "no transaction edit link found in listing"
    return match.group(1)
