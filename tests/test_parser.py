"""Tests for the LLM parser module (mocked, no real API calls)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import ParsedTransaction, TransactionType
from app.llm.parser import build_parser_chain, parse_transaction


class TestBuildParserChain:
    def test_returns_runnable(self):
        chain = build_parser_chain(api_key="sk-test")
        # Should be a LangChain Runnable (pipe)
        assert hasattr(chain, "ainvoke")


class TestParseTransaction:
    """Test parse_transaction with a mocked LLM response."""

    @pytest.fixture
    def mock_parsed(self) -> ParsedTransaction:
        return ParsedTransaction(
            type=TransactionType.EXPENSE,
            amount=12.50,
            currency="USD",
            category="food",
            datetime_str="2026-02-17T10:00:00",
            description="Coffee",
        )

    async def test_parse_returns_parsed_transaction(self, mock_parsed):
        with patch("app.llm.parser.build_parser_chain") as mock_build:
            mock_chain = AsyncMock()
            mock_chain.ainvoke.return_value = mock_parsed
            mock_build.return_value = mock_chain

            result = await parse_transaction(
                "Coffee 12.50",
                api_key="sk-test",
                default_currency="USD",
            )

            assert result.type == TransactionType.EXPENSE
            assert result.amount == 12.50
            assert result.currency == "USD"
            assert result.category == "food"
            mock_chain.ainvoke.assert_awaited_once()

    async def test_passes_currency_to_chain(self, mock_parsed):
        with patch("app.llm.parser.build_parser_chain") as mock_build:
            mock_chain = AsyncMock()
            mock_chain.ainvoke.return_value = mock_parsed
            mock_build.return_value = mock_chain

            await parse_transaction(
                "test", api_key="sk-test", default_currency="ILS"
            )

            call_args = mock_chain.ainvoke.call_args[0][0]
            assert call_args["default_currency"] == "ILS"

    async def test_passes_existing_categories(self, mock_parsed):
        with patch("app.llm.parser.build_parser_chain") as mock_build:
            mock_chain = AsyncMock()
            mock_chain.ainvoke.return_value = mock_parsed
            mock_build.return_value = mock_chain

            await parse_transaction(
                "test",
                api_key="sk-test",
                existing_categories=["food", "transport", "rent"],
            )

            call_args = mock_chain.ainvoke.call_args[0][0]
            assert call_args["existing_categories"] == "food, transport, rent"

    async def test_no_existing_categories(self, mock_parsed):
        with patch("app.llm.parser.build_parser_chain") as mock_build:
            mock_chain = AsyncMock()
            mock_chain.ainvoke.return_value = mock_parsed
            mock_build.return_value = mock_chain

            await parse_transaction(
                "test", api_key="sk-test"
            )

            call_args = mock_chain.ainvoke.call_args[0][0]
            assert call_args["existing_categories"] == "(none yet)"
