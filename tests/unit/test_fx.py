from datetime import date
from decimal import Decimal

import httpx
import pytest

from caudal.core import fx
from caudal.core.models import TransactionType
from caudal.core.validation import ValidTransaction


def test_convert_usd_to_cop_rounds_to_nearest_cent() -> None:
    assert fx.convert_usd_to_cop(1046, Decimal("3830.02")) == 4006201


def test_convert_to_cop_leaves_non_usd_currency_untouched() -> None:
    tx = ValidTransaction(
        type=TransactionType.expense,
        amount_minor=100000,
        currency="COP",
        occurred_on=date(2026, 7, 18),
        description="already pesos",
        category="cogs",
    )
    assert fx.convert_to_cop(tx) is tx


def test_convert_to_cop_converts_usd_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, params: dict, timeout: float) -> httpx.Response:
        assert "2026-07-18" in params["$where"]
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=[{"valor": "3262.58"}], request=request)

    monkeypatch.setattr(httpx, "get", fake_get)

    tx = ValidTransaction(
        type=TransactionType.expense,
        amount_minor=2000,
        currency="USD",
        occurred_on=date(2026, 7, 18),
        description="Resend",
        category="cogs",
    )
    converted = fx.convert_to_cop(tx)

    assert converted.currency == "COP"
    assert converted.amount_minor == fx.convert_usd_to_cop(2000, Decimal("3262.58"))
    assert converted.description == tx.description
    assert converted.category == tx.category


def test_get_usd_cop_rate_raises_when_no_rate_published(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, params: dict, timeout: float) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=[], request=request)

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(fx.FxRateUnavailable):
        fx.get_usd_cop_rate(date(2026, 7, 18))


def test_get_usd_cop_rate_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, params: dict, timeout: float) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(500, request=request)

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(fx.FxRateUnavailable):
        fx.get_usd_cop_rate(date(2026, 7, 18))


def test_convert_to_cop_raises_when_rate_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, params: dict, timeout: float) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=[], request=request)

    monkeypatch.setattr(httpx, "get", fake_get)

    tx = ValidTransaction(
        type=TransactionType.expense,
        amount_minor=2000,
        currency="USD",
        occurred_on=date(2026, 7, 18),
        description="Resend",
        category="cogs",
    )
    with pytest.raises(fx.FxRateUnavailable):
        fx.convert_to_cop(tx)
