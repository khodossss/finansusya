# Telegram Personal Finance Tracker Bot

A Telegram bot that helps individuals or small groups track income and expenses using natural language. Users share a single "finance database" via a generated hash. Transactions are parsed by an LLM (GPT-4o-mini) and stored in SQLite. Supports transaction listing with flexible date filters and an LLM-powered Q&A mode that can query the database.

---

## Features

| Feature | Description |
|---------|-------------|
| 🗣 **Natural-language input** | Type _"Coffee 12.5"_ or _"Got salary 12,000"_ — the LLM extracts type, amount, currency, category & date |
| 👥 **Shared workspaces** | Create a workspace hash and share it; multiple users write to the same ledger |
| 📋 **Transaction listing** | `/transactions`, `/transactions 2026-02-01`, `/transactions 2026-01-01 now` |
| 🤖 **Q&A over your data** | `/question How much did we spend on food last month?` — LLM generates SQL, runs it, summarises |
| ⚡ **Webhook-based** | FastAPI server receives Telegram updates via webhook for low-latency responses |

---

## Project Structure

```
tg_finans/
├── app/
│   ├── __init__.py
│   ├── __main__.py          # uvicorn entry-point
│   ├── config.py            # Settings dataclass (from .env)
│   ├── server.py            # FastAPI app + webhook route
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── handlers.py      # Telegram command & message handlers
│   │   └── formatting.py    # Pretty message formatting
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py        # Pydantic domain models
│   │   └── repository.py    # Async SQLite data-access layer
│   └── llm/
│       ├── __init__.py
│       ├── parser.py        # LangChain structured-output parser
│       └── qa.py            # LangChain tool-calling Q&A agent
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_repository.py
│   ├── test_formatting.py
│   ├── test_parser.py
│   ├── test_qa.py
│   ├── test_handlers.py
│   └── test_server.py
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

---

## Tech Stack

* **Python 3.9+**
* **python-telegram-bot** — Telegram Bot API
* **FastAPI + Uvicorn** — Webhook server
* **SQLite** (via **aiosqlite**) — Persistent storage
* **OpenAI GPT-4o-mini** — Transaction parsing & Q&A
* **LangChain** — Structured output & tool-calling agent
* **Pydantic** — Data validation
* **pytest + pytest-asyncio** — Testing

---

## Quick Start

### 1. Clone & install

```bash
git clone <repo-url> && cd tg_finans
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in:
#   TELEGRAM_BOT_TOKEN=<your token from @BotFather>
#   OPENAI_API_KEY=sk-<your key>
#   WEBHOOK_URL=https://your-domain.com   (for production)
```

### 3. Run

```bash
# Start the FastAPI webhook server
python -m app
```

The server starts on `http://0.0.0.0:8000`. For local development you can use **ngrok** to expose the webhook:

```bash
ngrok http 8000
# Then set WEBHOOK_URL in .env to the ngrok https URL
```

### 4. Run tests

```bash
pytest -v              # run all 60 tests
pytest --cov=app -v    # with coverage report
```

---

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Create or join a workspace, set name & currency |
| `/transactions` | List all transactions in the workspace |
| `/transactions DATE` | Transactions on a specific date + daily totals |
| `/transactions DATE1 now` | Transactions from DATE1 to now + totals |
| `/transactions DATE1 DATE2` | Transactions in a date range + totals |
| `/question QUESTION` | Ask a natural-language question about your finances |
| `/cancel` | Cancel the current onboarding flow |

Any non-command message is automatically parsed as a transaction.

---

## SQLite Schema

```sql
workspaces (id_hash TEXT PK, created_at TEXT)
users      (telegram_user_id INT PK, name TEXT, default_currency TEXT, workspace_id_hash TEXT FK)
transactions (id INT PK, workspace_id_hash TEXT FK, user_id INT FK,
              type TEXT, category TEXT, amount REAL, currency TEXT,
              timestamp TEXT, description TEXT, raw_text TEXT, created_at TEXT)
```

---

## How It Works

1. **Onboarding** — `/start` creates or connects to a workspace; user provides name & currency.
2. **Transaction parsing** — Free-text messages are sent to GPT-4o-mini via LangChain's `with_structured_output`, which returns a `ParsedTransaction` (type, amount, currency, category, datetime, description).
3. **Storage** — The parsed transaction is saved to SQLite scoped to the workspace.
4. **Listing** — `/transactions` fetches from SQLite with optional date filters and computes summaries.
5. **Q&A** — `/question` runs a LangChain agent loop: the LLM generates SQL → the tool executes read-only SELECT → the LLM summarises results in natural language.

---

## License

MIT
