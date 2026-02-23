"""Tests for the currency conversion service."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.services.currency import (
    convert_amount,
    get_exchange_rate,
    clear_rate_cache,
    _fetch_frankfurter,
    _fetch_exchangerate_api,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure each test starts with a clean rate cache."""
    clear_rate_cache()
    yield
    clear_rate_cache()


def _mock_provider(rate: float | None):
    """Return an AsyncMock provider that returns a fixed rate."""
    return AsyncMock(return_value=rate)


class TestGetExchangeRate:
    async def test_same_currency_returns_one(self):
        rate = await get_exchange_rate("USD", "USD")
        assert rate == 1.0

    async def test_case_insensitive_same(self):
        rate = await get_exchange_rate("usd", "USD")
        assert rate == 1.0

    async def test_fetches_rate_from_first_provider(self):
        with patch(
            "app.services.currency._PROVIDERS",
            [_mock_provider(0.85), _mock_provider(0.90)],
        ):
            rate = await get_exchange_rate("USD", "EUR")
        assert rate == 0.85

    async def test_falls_back_to_second_provider(self):
        with patch(
            "app.services.currency._PROVIDERS",
            [_mock_provider(None), _mock_provider(5.2)],
        ):
            rate = await get_exchange_rate("ILS", "RUB")
        assert rate == 5.2

    async def test_caches_result(self):
        provider = _mock_provider(3.65)
        with patch("app.services.currency._PROVIDERS", [provider]):
            r1 = await get_exchange_rate("USD", "ILS")
            r2 = await get_exchange_rate("USD", "ILS")

        assert r1 == r2 == 3.65
        # Only called once thanks to cache
        assert provider.await_count == 1

    async def test_caches_reverse_direction(self):
        provider = _mock_provider(4.0)
        with patch("app.services.currency._PROVIDERS", [provider]):
            await get_exchange_rate("USD", "ILS")
            reverse = await get_exchange_rate("ILS", "USD")

        assert reverse == pytest.approx(0.25)
        assert provider.await_count == 1  # no second call

    async def test_raises_when_all_providers_fail(self):
        with patch(
            "app.services.currency._PROVIDERS",
            [_mock_provider(None), _mock_provider(None)],
        ):
            with pytest.raises(ValueError, match="No provider returned a rate"):
                await get_exchange_rate("USD", "XYZ")


class TestConvertAmount:
    async def test_same_currency(self):
        result = await convert_amount(100.0, "USD", "USD")
        assert result == 100.0

    async def test_converts_using_rate(self):
        with patch(
            "app.services.currency.get_exchange_rate",
            new_callable=AsyncMock,
            return_value=3.5,
        ):
            result = await convert_amount(100.0, "USD", "ILS")
        assert result == 350.0

    async def test_rounds_to_two_decimals(self):
        with patch(
            "app.services.currency.get_exchange_rate",
            new_callable=AsyncMock,
            return_value=3.333333,
        ):
            result = await convert_amount(10.0, "EUR", "ILS")
        assert result == 33.33
