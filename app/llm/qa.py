"""LLM Q&A agent that can query the finance database using tools."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.db.repository import Repository

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_QA_SYSTEM_PROMPT = """\
You are a helpful financial assistant for a personal finance Telegram bot.
The user will ask natural-language questions about their finances.

You have access to a tool called `query_finance_db` that runs a **read-only**
SQL SELECT against the user's SQLite finance database.

The database has one relevant table:

    transactions (
        id                INTEGER PRIMARY KEY,
        workspace_id_hash TEXT,
        user_id           INTEGER,
        type              TEXT   -- 'income' or 'expense',
        category          TEXT,
        amount            REAL,
        currency          TEXT,
        timestamp         TEXT   -- ISO-8601,
        description       TEXT,
        raw_text          TEXT,
        created_at        TEXT
    )

    users (
        telegram_user_id  INTEGER PRIMARY KEY,
        name              TEXT,
        default_currency  TEXT,
        workspace_id_hash TEXT
    )

User context:
- Name: {user_name}
- Default currency: {user_currency}
- Telegram user ID: {user_id}

Rules:
1. ALWAYS filter by workspace_id_hash = '{workspace_id}'.
2. Only generate SELECT statements — never INSERT, UPDATE, DELETE, DROP, etc.
3. Keep result sets small: use LIMIT, aggregation, or WHERE clauses.
4. After receiving query results, summarize them in plain, friendly English.
5. Use the user's default currency ({user_currency}) when presenting monetary
   amounts. If transactions are in different currencies, mention each currency.
6. The current date/time is {current_datetime}.
"""


# ---------------------------------------------------------------------------
# Tool factory — creates a tool bound to a specific repo instance
# ---------------------------------------------------------------------------

def _make_query_tool(repo: Repository, workspace_id: str):
    """Return a LangChain tool that executes read-only SQL on the workspace."""

    @tool
    async def query_finance_db(sql: str) -> str:
        """Execute a read-only SQL SELECT on the finance database.

        Args:
            sql: A SELECT query. Must filter by the current workspace.
        """
        try:
            rows = await repo.execute_readonly_sql(sql)
            if not rows:
                return "No results found."
            # Format as a readable table-like string
            lines: list[str] = []
            for row in rows[:50]:  # safety cap
                lines.append(" | ".join(f"{k}={v}" for k, v in row.items()))
            return "\n".join(lines)
        except PermissionError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"SQL error: {exc}"

    return query_finance_db


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def ask_question(
    question: str,
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    repo: Repository,
    workspace_id: str,
    user_name: str = "",
    user_currency: str = "USD",
    user_id: int = 0,
) -> str:
    """Ask a natural-language question about the user's finances."""
    from datetime import datetime

    query_tool = _make_query_tool(repo, workspace_id)

    llm = ChatOpenAI(
        api_key=api_key,  # type: ignore[arg-type]
        model=model,
        temperature=0,
    ).bind_tools([query_tool])

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                _QA_SYSTEM_PROMPT.format(
                    workspace_id=workspace_id,
                    current_datetime=datetime.utcnow().isoformat(),
                    user_name=user_name,
                    user_currency=user_currency,
                    user_id=user_id,
                ),
            ),
            ("human", "{question}"),
            MessagesPlaceholder("agent_scratchpad", optional=True),
        ]
    )

    # Simple agent loop (tool → LLM → tool → … → final answer)
    messages = await prompt.ainvoke({"question": question})
    response = await llm.ainvoke(messages)

    # If the LLM wants to call a tool, iterate
    iterations = 0
    all_messages = list(messages.to_messages()) + [response]

    while response.tool_calls and iterations < 5:
        for tc in response.tool_calls:
            tool_result = await query_tool.ainvoke(tc["args"])
            from langchain_core.messages import ToolMessage

            all_messages.append(
                ToolMessage(content=str(tool_result), tool_call_id=tc["id"])
            )
        response = await llm.ainvoke(all_messages)
        all_messages.append(response)
        iterations += 1

    return response.content or "I couldn't find an answer."
