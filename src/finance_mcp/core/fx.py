"""USD -> COP conversion at the official daily TRM ("Tasa Representativa
del Mercado", Colombia's Banco de la República reference rate, mirrored
on datos.gov.co) — applied when a transaction is *recorded* in USD, so
every transaction in this system ends up in one currency.

This matters beyond convenience: core.projections/core.reporting sum
``amount_minor`` across a currency's rows without ever converting
between currencies. A USD row left unconverted next to COP rows would
silently corrupt runway/MRR/forecast math (dollars and pesos summed as
if they were the same unit). Converting at the door removes that
failure mode entirely rather than requiring every caller to remember it.
"""

import dataclasses
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import httpx

from finance_mcp.core.logging import get_logger
from finance_mcp.core.validation import ValidTransaction

logger = get_logger(__name__)

TRM_ENDPOINT = "https://www.datos.gov.co/resource/32sa-8pi3.json"
TARGET_CURRENCY = "USD"


class FxRateUnavailable(Exception):
    """The TRM for a given date couldn't be fetched — callers must
    surface this to the user, never guess a rate or fall back to a
    stale one."""


def get_usd_cop_rate(on_date: date, *, timeout_seconds: float = 10.0) -> Decimal:
    """The TRM (COP per 1 USD) in effect on ``on_date``. The published
    rate stays valid across weekends/holidays, so this queries for the
    record whose validity range covers the date rather than an exact
    match."""
    iso = on_date.isoformat()
    where = f"vigenciadesde<='{iso}T00:00:00.000' AND vigenciahasta>='{iso}T00:00:00.000'"
    try:
        response = httpx.get(
            TRM_ENDPOINT, params={"$where": where, "$limit": 1}, timeout=timeout_seconds
        )
        response.raise_for_status()
        rows = response.json()
    except httpx.HTTPError as exc:
        raise FxRateUnavailable(f"could not reach the TRM service: {exc}") from exc

    if not rows:
        raise FxRateUnavailable(f"no TRM published covering {iso}")
    return Decimal(rows[0]["valor"])


def convert_usd_to_cop(amount_minor_usd: int, rate: Decimal) -> int:
    """USD minor units (cents) -> COP minor units, at ``rate`` COP per
    USD dollar."""
    cop = (Decimal(amount_minor_usd) / 100) * rate
    return int((cop * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def convert_to_cop(tx: ValidTransaction) -> ValidTransaction:
    """Returns ``tx`` unchanged unless its currency is USD, in which
    case it returns a copy converted to COP at the TRM of
    ``tx.occurred_on``. Raises FxRateUnavailable rather than silently
    leaving the transaction in USD."""
    if tx.currency != TARGET_CURRENCY:
        return tx
    rate = get_usd_cop_rate(tx.occurred_on)
    converted = dataclasses.replace(
        tx, amount_minor=convert_usd_to_cop(tx.amount_minor, rate), currency="COP"
    )
    logger.info(
        "fx.converted_usd_to_cop",
        occurred_on=tx.occurred_on.isoformat(),
        rate=str(rate),
        usd_minor=tx.amount_minor,
        cop_minor=converted.amount_minor,
    )
    return converted
