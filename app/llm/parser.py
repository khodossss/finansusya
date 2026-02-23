"""LLM-powered transaction parser using LangChain + OpenAI structured output."""

from __future__ import annotations

from datetime import datetime

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.db.models import ParsedTransaction

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a financial transaction parser. The user sends short natural-language
messages describing a personal finance event (income or expense).

First decide: is the message actually a financial transaction?
- If it is a question, greeting, request, or anything that is NOT a concrete
  financial transaction, set is_transaction = false and leave the other fields
  at their defaults.
- If it IS a transaction, set is_transaction = true and extract the fields below.

Fields to extract (when is_transaction is true):
- type: "income" or "expense"
- amount: numeric value (always positive)
- currency: ISO currency code. Use the user's default currency if not mentioned.
- category: a short lowercase label. If one of the existing categories listed
  below is a good semantic match, reuse it to avoid duplicates (e.g. prefer
  "groceries" over "grocery stores"). However, if none of the existing
  categories fit the transaction, create a new descriptive category freely.
- datetime_str: ISO-8601 date-time string. **Always** resolve relative time
  references like "yesterday", "today", "last Monday", "2 days ago",
  "this morning" etc. relative to the current datetime provided below.
  If no date or time is mentioned at all, use the current datetime.
  Examples (assuming current datetime is 2026-02-21T14:30:00):
    "yesterday" → "2026-02-20T14:30:00"
    "last Monday" → "2026-02-16T12:00:00"
    "2 days ago" → "2026-02-19T14:30:00"
    (no date mentioned) → "2026-02-21T14:30:00"
- description: a clean, human-readable summary of the transaction in a few words.

Current datetime (UTC): {current_datetime}
User's default currency: {default_currency}
Existing categories: {existing_categories}
"""


def build_parser_chain(api_key: str, model: str = "gpt-4o-mini"):
    """Return a LangChain runnable that parses text → ParsedTransaction."""
    llm = ChatOpenAI(
        api_key=api_key,  # type: ignore[arg-type]
        model=model,
        temperature=0,
    )

    structured_llm = llm.with_structured_output(ParsedTransaction)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM_PROMPT),
            ("human", "{user_message}"),
        ]
    )

    return prompt | structured_llm


async def parse_transaction(
    user_message: str,
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    default_currency: str = "USD",
    existing_categories: list[str] | None = None,
) -> ParsedTransaction:
    """Parse a single user message into a structured transaction."""
    chain = build_parser_chain(api_key, model)
    cats = ", ".join(existing_categories) if existing_categories else "(none yet)"
    result = await chain.ainvoke(
        {
            "user_message": user_message,
            "current_datetime": datetime.utcnow().isoformat(),
            "default_currency": default_currency,
            "existing_categories": cats,
        }
    )
    return result  # type: ignore[return-value]
