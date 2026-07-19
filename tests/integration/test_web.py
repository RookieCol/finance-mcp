"""Integration tests for the internal UI, driven through FastAPI's
TestClient (real HTTP request/response cycle, real Postgres) rather than
calling route functions directly.
"""

import re

import httpx
import pytest
from fastapi.testclient import TestClient

from .conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.usefixtures("web_env")]


@pytest.fixture
def client() -> TestClient:
    from caudal.web.app import app

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
            "currency": "COP",
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

    from caudal.core import alerts, db

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

    from caudal.mcp_server.server import mcp

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


def test_new_transaction_in_usd_is_auto_converted_to_cop(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_get(url: str, params: dict, timeout: float) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=[{"valor": "4000.00"}], request=request)

    monkeypatch.setattr(httpx, "get", fake_get)

    response = client.post(
        "/transactions/new",
        data={
            "type": "expense",
            "amount": "10.00",
            "currency": "USD",
            "occurred_on": "2026-07-18",
            "description": "fx auto-convert test",
            "category": "cogs",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    listing = client.get("/transactions")
    assert "fx auto-convert test" in listing.text
    assert "COP" in listing.text
    assert "40,000.00" in listing.text


def test_new_transaction_in_usd_shows_error_when_rate_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_get(url: str, params: dict, timeout: float) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=[], request=request)

    monkeypatch.setattr(httpx, "get", fake_get)

    response = client.post(
        "/transactions/new",
        data={
            "type": "expense",
            "amount": "10.00",
            "currency": "USD",
            "occurred_on": "2026-07-18",
            "description": "fx unavailable test",
            "category": "cogs",
        },
    )
    assert response.status_code == 422
    assert "TRM" in response.text or "rate" in response.text.lower()

    listing = client.get("/transactions")
    assert "fx unavailable test" not in listing.text


def test_static_css_served(client: TestClient) -> None:
    response = client.get("/static/app.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


def test_projections_page_renders_with_no_data(client: TestClient) -> None:
    response = client.get("/projections")
    assert response.status_code == 200
    assert "Assumptions" in response.text


def test_projections_page_renders_with_data(client: TestClient) -> None:
    client.post(
        "/transactions/new",
        data={
            "type": "income",
            "amount": "500.00",
            "currency": "USD",
            "occurred_on": "2026-07-01",
            "description": "recurring plan",
            "category": "subscription",
            "is_recurring": "true",
        },
        follow_redirects=False,
    )
    response = client.get("/projections")
    assert response.status_code == 200
    assert "Assumptions" in response.text


def test_reports_page_renders_and_filters(client: TestClient) -> None:
    client.post(
        "/transactions/new",
        data={
            "type": "expense",
            "amount": "30.00",
            "currency": "USD",
            "occurred_on": "2026-07-05",
            "description": "reports fixture",
            "category": "cogs",
        },
        follow_redirects=False,
    )

    response = client.get("/reports")
    assert response.status_code == 200
    assert "cogs" in response.text

    filtered = client.get("/reports", params={"date_from": "2026-07-01", "date_to": "2026-07-31"})
    assert filtered.status_code == 200
    assert "cogs" in filtered.text

    invalid = client.get("/reports", params={"date_from": "not-a-date"})
    assert invalid.status_code == 200


def test_budget_toggle_active(client: TestClient) -> None:
    client.post(
        "/budgets",
        data={"category": "marketing", "monthly_limit": "500.00", "currency": "USD"},
        follow_redirects=False,
    )
    listing = client.get("/budgets")
    budget_id = _extract_budget_id(listing.text)

    toggle_response = client.post(f"/budgets/{budget_id}/toggle", follow_redirects=False)
    assert toggle_response.status_code == 303

    listing_after = client.get("/budgets")
    assert "inactive" in listing_after.text


def test_budget_edit_limit(client: TestClient) -> None:
    client.post(
        "/budgets",
        data={"category": "marketing", "monthly_limit": "500.00", "currency": "USD"},
        follow_redirects=False,
    )
    listing = client.get("/budgets")
    budget_id = _extract_budget_id(listing.text)

    edit_response = client.post(
        f"/budgets/{budget_id}/edit",
        data={"monthly_limit": "750.00"},
        follow_redirects=False,
    )
    assert edit_response.status_code == 303

    listing_after = client.get("/budgets")
    assert "750.00" in listing_after.text


def test_alert_payload_is_human_readable(client: TestClient) -> None:
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
            "description": "over budget for payload test",
            "category": "marketing",
        },
        follow_redirects=False,
    )

    from caudal.core import alerts, db

    with db.session_scope() as session:
        alerts.evaluate_alerts(session)

    response = client.get("/alerts")
    assert "spent" in response.text
    assert "marketing" in response.text


def _extract_transaction_id(html: str) -> str:
    match = re.search(r"/transactions/([0-9a-f-]{36})/edit", html)
    assert match is not None, "no transaction edit link found in listing"
    return match.group(1)


def _extract_budget_id(html: str) -> str:
    match = re.search(r"/budgets/([0-9a-f-]{36})/edit", html)
    assert match is not None, "no budget edit form found in listing"
    return match.group(1)
