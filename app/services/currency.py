"""Currency conversion service with multiple free API fallbacks."""

from __future__ import annotations

import logging
from typing import Dict

import httpx

logger = logging.getLogger(__name__)

# In-memory cache: (from_cur, to_cur) → rate
_rate_cache: Dict[tuple, float] = {}


async def _fetch_frankfurter(
    client: httpx.AsyncClient, from_cur: str, to_cur: str,
) -> float | None:
    """Try frankfurter.app (ECB-based, no key). Missing RUB & some others."""
    try:
        resp = await client.get(
            "https://api.frankfurter.app/latest",
            params={"from": from_cur, "to": to_cur},
        )
        resp.raise_for_status()
        rate = resp.json().get("rates", {}).get(to_cur)
        if rate is not None:
            return float(rate)
    except Exception:
        logger.debug("frankfurter.app failed for %s→%s", from_cur, to_cur)
    return None


async def _fetch_exchangerate_api(
    client: httpx.AsyncClient, from_cur: str, to_cur: str,
) -> float | None:
    """Try open.er-api.com (free, no key, supports 150+ currencies incl. RUB)."""
    try:
        resp = await client.get(
            f"https://open.er-api.com/v6/latest/{from_cur}",
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") == "success":
            rate = data.get("rates", {}).get(to_cur)
            if rate is not None:
                return float(rate)
    except Exception:
        logger.debug("open.er-api.com failed for %s→%s", from_cur, to_cur)
    return None


# Ordered list of providers — first success wins
_PROVIDERS = [_fetch_frankfurter, _fetch_exchangerate_api]


async def get_exchange_rate(from_currency: str, to_currency: str) -> float:
    """Return the exchange rate from *from_currency* to *to_currency*.

    Tries multiple free APIs in order until one succeeds.
    Caches results in memory for the lifetime of the process.

    Returns 1.0 if the currencies are the same.
    Raises ``ValueError`` if no provider can resolve the pair.
    """
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return 1.0

    cache_key = (from_currency, to_currency)
    if cache_key in _rate_cache:
        return _rate_cache[cache_key]

    rate: float | None = None
    async with httpx.AsyncClient(timeout=10) as client:
        for provider in _PROVIDERS:
            rate = await provider(client, from_currency, to_currency)
            if rate is not None:
                break

    if rate is None:
        raise ValueError(
            f"Cannot convert {from_currency} → {to_currency}. "
            f"No provider returned a rate."
        )

    # Cache both directions
    _rate_cache[cache_key] = rate
    if rate != 0:
        _rate_cache[(to_currency, from_currency)] = round(1.0 / rate, 10)

    logger.info("Exchange rate %s → %s = %.6f", from_currency, to_currency, rate)
    return rate


async def convert_amount(
    amount: float,
    from_currency: str,
    to_currency: str,
) -> float:
    """Convert *amount* from one currency to another."""
    rate = await get_exchange_rate(from_currency, to_currency)
    return round(amount * rate, 2)


def clear_rate_cache() -> None:
    """Clear the in-memory rate cache (useful for tests)."""
    _rate_cache.clear()
