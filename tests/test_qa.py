"""Tests for the LLM Q&A module (mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.db.repository import Repository


class TestQueryTool:
    """Test the read-only SQL tool used by the QA agent."""

    async def test_readonly_select(self, repo: Repository):
        ws = await repo.create_workspace()
        rows = await repo.execute_readonly_sql(
            "SELECT COUNT(*) as cnt FROM workspaces WHERE id_hash = ?",
            (ws.id_hash,),
        )
        assert rows[0]["cnt"] == 1

    async def test_readonly_rejects_writes(self, repo: Repository):
        with pytest.raises(PermissionError, match="SELECT"):
            await repo.execute_readonly_sql("INSERT INTO workspaces VALUES ('x','y')")


class TestAskQuestion:
    """Test ask_question with fully mocked LLM."""

    async def test_returns_string_answer(self, repo: Repository):
        from unittest.mock import MagicMock

        ws = await repo.create_workspace()

        # Mock the entire ChatOpenAI and its response
        with patch("app.llm.qa.ChatOpenAI") as MockLLM:
            mock_response = MagicMock()
            mock_response.content = "You spent $150 on food last month."
            mock_response.tool_calls = []

            # bind_tools returns a sync MagicMock that has an async ainvoke
            mock_bound = MagicMock()
            mock_bound.ainvoke = AsyncMock(return_value=mock_response)

            # ChatOpenAI() returns a MagicMock whose .bind_tools() returns mock_bound
            mock_llm_instance = MagicMock()
            mock_llm_instance.bind_tools.return_value = mock_bound
            MockLLM.return_value = mock_llm_instance

            from app.llm.qa import ask_question

            answer = await ask_question(
                "How much on food?",
                api_key="sk-test",
                repo=repo,
                workspace_id=ws.id_hash,
            )

            assert isinstance(answer, str)
            assert "150" in answer
