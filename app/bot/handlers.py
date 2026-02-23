"""Telegram bot command and message handlers."""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timedelta

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from app.bot.formatting import (
    format_summary,
    format_transaction_confirmation,
    format_transaction_details,
    format_transaction_list,
)
from app.config import Settings
from app.db.models import Transaction, TransactionType, User, Workspace
from app.db.repository import Repository
from app.llm.parser import parse_transaction
from app.llm.qa import ask_question
from app.services.csv_export import generate_csv_bytes, make_csv_filename
from app.services.currency import convert_amount
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)
user_logger = logging.getLogger("app.user_activity")


# ---------------------------------------------------------------------------
# Logging middleware — runs for every incoming update (group=-1)
# ---------------------------------------------------------------------------

async def _log_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log every user interaction (commands, messages, callbacks)."""
    tg_user = update.effective_user
    uid = tg_user.id if tg_user else "?"
    username = f"@{tg_user.username}" if tg_user and tg_user.username else str(uid)

    if update.message and update.message.text:
        user_logger.info("[msg] user=%s (id=%s)  text=%r", username, uid, update.message.text)
    elif update.callback_query:
        user_logger.info("[callback] user=%s (id=%s)  data=%r", username, uid, update.callback_query.data)
    elif update.edited_message and update.edited_message.text:
        user_logger.info("[edit] user=%s (id=%s)  text=%r", username, uid, update.edited_message.text)
    else:
        user_logger.info("[update] user=%s (id=%s)  type=%s", username, uid, type(update).__name__)


# ---------------------------------------------------------------------------
# Conversation states for onboarding
# ---------------------------------------------------------------------------
CHOOSE_ACTION, ENTER_HASH, ENTER_NAME, ENTER_CURRENCY, ENTER_INITIAL_AMOUNT = range(5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_repo(context: ContextTypes.DEFAULT_TYPE) -> Repository:
    """Retrieve the Repository instance from bot_data."""
    return context.bot_data["repo"]


def _get_settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data["settings"]


def _get_notifier(context: ContextTypes.DEFAULT_TYPE) -> NotificationService:
    return context.bot_data["notifier"]


async def _other_workspace_users(
    repo: Repository, workspace_id_hash: str,
) -> list[int]:
    """Return all user IDs in the workspace."""
    names = await repo.get_workspace_user_names(workspace_id_hash)
    return list(names.keys())


async def _ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[User, Workspace] | None:
    """Return (User, Workspace) if onboarded, otherwise prompt to /start."""
    repo = _get_repo(context)
    user = await repo.get_user(update.effective_user.id)
    if not user or not user.workspace_id_hash:
        await update.message.reply_text("\u26a0\ufe0f Please run /start to set up your account first.")
        return None
    ws = await repo.get_workspace(user.workspace_id_hash)
    if not ws:
        await update.message.reply_text("\u26a0\ufe0f Workspace not found. Please run /start again.")
        return None
    return user, ws


# ---------------------------------------------------------------------------
# /start — onboarding conversation
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: ask for the user's display name first."""
    await update.message.reply_text(
        "👋 *Welcome to Finance Tracker!*\n\n"
        "Please enter your *display name*:",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ENTER_NAME


async def name_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the name, then ask whether to create or join a workspace."""
    context.user_data["display_name"] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("🆕 Create new database", callback_data="create")],
        [InlineKeyboardButton("🔗 Connect to existing", callback_data="connect")],
    ]
    await update.message.reply_text(
        f"Nice to meet you, *{context.user_data['display_name']}*! 🎉\n\n"
        "Now choose an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )
    return CHOOSE_ACTION


async def action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the create/connect button press."""
    query = update.callback_query
    await query.answer()

    if query.data == "create":
        await query.edit_message_text(
            "💱 Enter the workspace *currency* (e.g. USD, EUR, ILS):",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ENTER_CURRENCY

    # connect
    await query.edit_message_text("🔗 Enter the *database ID (hash)* you'd like to join:")
    return ENTER_HASH


async def hash_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate the workspace hash, save user and finish."""
    repo = _get_repo(context)
    hash_value = update.message.text.strip()
    workspace = await repo.get_workspace(hash_value)
    if not workspace:
        await update.message.reply_text("❌ Database not found. Try again or use /start.")
        return ENTER_HASH

    user = User(
        telegram_user_id=update.effective_user.id,
        name=context.user_data["display_name"],
        workspace_id_hash=hash_value,
    )
    await repo.upsert_user(user)

    await update.message.reply_text(
        f"🎉 All set, *{user.name}*!\n\n"
        f"Workspace: `{hash_value}`\n"
        f"Currency: `{workspace.default_currency}`",
        parse_mode=ParseMode.MARKDOWN,
    )
    await _send_help(update.effective_chat.id, context)
    return ConversationHandler.END


async def currency_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store currency, ask for initial balance."""
    context.user_data["currency"] = update.message.text.strip().upper()
    await update.message.reply_text(
        "💰 Enter your *initial balance* (current amount you have).\n"
        "Type `0` if you want to start from zero:",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ENTER_INITIAL_AMOUNT


async def initial_amount_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finish create-workspace onboarding: save workspace, user, and initial balance."""
    raw = update.message.text.strip().replace(",", "")
    try:
        initial_amount = float(raw)
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a valid number:")
        return ENTER_INITIAL_AMOUNT

    repo = _get_repo(context)
    currency = context.user_data["currency"]

    # Create the workspace with the chosen currency
    workspace = await repo.create_workspace(currency=currency)
    ws_hash = workspace.id_hash

    # Save user
    user = User(
        telegram_user_id=update.effective_user.id,
        name=context.user_data["display_name"],
        workspace_id_hash=ws_hash,
    )
    await repo.upsert_user(user)

    # Record initial balance as a transaction (if != 0)
    if initial_amount != 0:
        tx_type = TransactionType.INCOME if initial_amount > 0 else TransactionType.EXPENSE
        tx = Transaction(
            workspace_id_hash=ws_hash,
            user_id=user.telegram_user_id,
            type=tx_type,
            category="initial balance",
            amount=abs(initial_amount),
            currency=currency,
            description="Starting balance",
            raw_text=f"Initial balance: {initial_amount} {currency}",
        )
        await repo.add_transaction(tx)

    await update.message.reply_text(
        f"🎉 All set, *{user.name}*!\n\n"
        f"🔑 Database ID: `{ws_hash}`\n"
        f"Share this ID with others so they can join.\n\n"
        f"💱 Currency: `{currency}`\n"
        f"💰 Initial balance: `{initial_amount:,.2f} {currency}`",
        parse_mode=ParseMode.MARKDOWN,
    )
    await _send_help(update.effective_chat.id, context)
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the onboarding conversation."""
    await update.message.reply_text("❌ Setup cancelled. Use /start to try again.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

HELP_TEXT = (
    "📖 *What can this bot do?*\n\n"
    "*💬 Record a transaction*\n"
    "Just type a message in natural language:\n"
    "  • _Coffee 12.5_\n"
    "  • _Got salary 15000_\n"
    "  • _Paid rent yesterday 4500 ILS_\n"
    "  • _Uber to office 38.20_\n\n"
    "The AI will extract the amount, category, date and currency automatically.\n\n"
    "*📋 Commands*\n"
    "/transactions — list all transactions\n"
    "/transactions `DATE` — single day (e.g. `2026-02-17`)\n"
    "/transactions `DATE1` `now` — from date to now\n"
    "/transactions `DATE1` `DATE2` — custom date range\n\n"
    "*📊 Summary*\n"
    "/summary — total income, expenses & net (all time)\n"
    "/summary `DATE` — single day\n"
    "/summary `DATE1` `now` — from date to now\n"
    "/summary `DATE1` `DATE2` — custom date range\n\n"
    "*🤖 Ask a question*\n"
    "/question `YOUR QUESTION`\n"
    "  • _How much did I spend on food last month?_\n"
    "  • _What are my top 5 expense categories?_\n"
    "  • _What is my net income this week?_\n\n"
    "*⚙️ Other*\n"
    "/start — create or join a workspace\n"
    "/change\\_currency — change default currency & convert all transactions\\n"
    "/help — show this message\n"
    "/cancel — cancel current setup"
)


HELP_KEYBOARD = ReplyKeyboardMarkup(
    [["📖 Help"]],
    resize_keyboard=True,
    is_persistent=True,
)


async def _send_help(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the help message with a persistent bottom button."""
    await context.bot.send_message(
        chat_id=chat_id,
        text=HELP_TEXT,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=HELP_KEYBOARD,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    await _send_help(update.effective_chat.id, context)


async def help_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the persistent '📖 Help' button tap."""
    await _send_help(update.effective_chat.id, context)


# ---------------------------------------------------------------------------
# Natural-language transaction handler
# ---------------------------------------------------------------------------

async def handle_transaction_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse a free-text message as a financial transaction."""
    result = await _ensure_user(update, context)
    if not result:
        return
    user, ws = result

    settings = _get_settings(context)
    repo = _get_repo(context)
    raw_text = update.message.text.strip()

    # Fetch existing categories so the LLM can reuse them
    # Exclude reserved "initial balance" to prevent misclassification
    existing_cats = [
        c for c in await repo.get_categories(user.workspace_id_hash)
        if c != "initial balance"
    ]

    try:
        parsed = await parse_transaction(
            raw_text,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            default_currency=ws.default_currency,
            existing_categories=existing_cats,
        )
    except Exception:
        logger.exception("LLM parsing failed for message: %s", raw_text)
        await update.message.reply_text("⚠️ Sorry, I couldn't understand that transaction. Please try again.")
        return

    # If the LLM decided this is not a transaction, suggest /question
    if not parsed.is_transaction:
        await update.message.reply_text(
            "🤔 That doesn't look like a transaction.\n"
            "If you want to ask a question, use:\n"
            "`/question your question here`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Resolve datetime
    try:
        ts = datetime.fromisoformat(parsed.datetime_str)
    except (ValueError, TypeError):
        ts = datetime.utcnow()

    # Auto-convert to user's default currency if needed
    original_currency = parsed.currency
    original_amount = parsed.amount
    amount = parsed.amount
    currency = parsed.currency

    if currency.upper() != ws.default_currency.upper():
        try:
            amount = await convert_amount(original_amount, currency, ws.default_currency)
            currency = ws.default_currency
        except Exception:
            logger.warning(
                "Currency conversion %s\u2192%s failed, keeping original",
                currency, ws.default_currency,
            )

    tx = Transaction(
        workspace_id_hash=user.workspace_id_hash,
        user_id=user.telegram_user_id,
        type=parsed.type,
        category=parsed.category,
        amount=amount,
        currency=currency,
        timestamp=ts,
        description=parsed.description,
        raw_text=raw_text,
    )

    tx_id = await repo.add_transaction(tx)
    tx.id = tx_id

    confirmation = format_transaction_confirmation(tx)
    if original_currency.upper() != currency.upper():
        confirmation += (
            f"\n  • Converted from: `{original_amount:,.2f} {original_currency}`"
        )

    await update.message.reply_text(
        confirmation,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_edit_keyboard(tx_id),
    )

    # Notify other workspace members
    notifier = _get_notifier(context)
    targets = await _other_workspace_users(repo, user.workspace_id_hash)
    await notifier.notify(
        tx_id=tx_id,
        actor_id=user.telegram_user_id,
        target_user_ids=targets,
        text=f"➕ *{user.name}* added:\n\n" + format_transaction_details(tx),
    )


# ---------------------------------------------------------------------------
# Edit transaction
# ---------------------------------------------------------------------------

_EDITABLE_FIELDS = [
    ("type", "🔄 Type"),
    ("category", "🏷 Category"),
    ("amount", "💵 Amount"),
    ("currency", "💱 Currency"),
    ("description", "📝 Description"),
]


def _edit_keyboard(tx_id: int) -> InlineKeyboardMarkup:
    """Return an InlineKeyboardMarkup with Edit and Remove buttons."""
    edit_cb = json.dumps({"a": "edit", "id": tx_id}, separators=(",", ":"))
    rm_cb = json.dumps({"a": "rm", "id": tx_id}, separators=(",", ":"))
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Edit", callback_data=edit_cb),
            InlineKeyboardButton("🗑 Remove", callback_data=rm_cb),
        ]
    ])


def _field_keyboard(tx_id: int) -> InlineKeyboardMarkup:
    """Return an InlineKeyboardMarkup with buttons for each editable field."""
    buttons = []
    for field, label in _EDITABLE_FIELDS:
        cb = json.dumps({"a": "ef", "id": tx_id, "f": field}, separators=(",", ":"))
        buttons.append([InlineKeyboardButton(label, callback_data=cb)])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data='{"a":"ecancel"}')])
    return InlineKeyboardMarkup(buttons)


async def edit_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show field-selection buttons when Edit is pressed."""
    query = update.callback_query
    await query.answer()
    payload = json.loads(query.data)
    tx_id = payload["id"]

    await query.edit_message_reply_markup(reply_markup=_field_keyboard(tx_id))


async def edit_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User chose which field to edit — ask for the new value (or toggle type)."""
    query = update.callback_query
    await query.answer()
    payload = json.loads(query.data)
    tx_id = payload["id"]
    field = payload["f"]

    repo = _get_repo(context)

    # Type has only two values — toggle immediately instead of asking
    if field == "type":
        tx = await repo.get_transaction(tx_id)
        if not tx:
            await query.edit_message_text("⚠️ Transaction not found.")
            return
        new_type = "income" if tx.type.value == "expense" else "expense"
        await repo.update_transaction(tx_id, "type", new_type)
        tx = await repo.get_transaction(tx_id)
        await query.edit_message_text(
            "✅ *Updated*\n\n" + format_transaction_confirmation(tx),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_edit_keyboard(tx_id),
        )
        # Notify workspace
        user = await repo.get_user(update.effective_user.id)
        if user:
            notifier = _get_notifier(context)
            targets = await _other_workspace_users(repo, tx.workspace_id_hash)
            await notifier.notify(
                tx_id=tx_id,
                actor_id=user.telegram_user_id,
                target_user_ids=targets,
                text=f"✏️ *{user.name}* edited:\n\n" + format_transaction_details(tx),
            )
        return

    label = next(lbl for fld, lbl in _EDITABLE_FIELDS if fld == field)

    # Store pending edit in user_data so the next text message finishes it
    context.user_data["pending_edit"] = {"tx_id": tx_id, "field": field}

    hint = ""
    if field == "amount":
        hint = " (number)"

    await query.edit_message_text(
        f"✏️ Editing *{label}*{hint}\n\nSend the new value:",
        parse_mode=ParseMode.MARKDOWN,
    )


async def edit_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel the field-selection menu — restore Edit / Remove buttons."""
    query = update.callback_query
    await query.answer("Cancelled")
    context.user_data.pop("pending_edit", None)

    # Try to extract tx_id from the original field-selection buttons
    # so we can restore the edit/remove keyboard.
    tx_id: int | None = None
    if query.message and query.message.reply_markup:
        for row in query.message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.callback_data:
                    try:
                        p = json.loads(btn.callback_data)
                        if "id" in p:
                            tx_id = p["id"]
                            break
                    except (json.JSONDecodeError, TypeError):
                        pass
            if tx_id is not None:
                break

    if tx_id is not None:
        await query.edit_message_reply_markup(reply_markup=_edit_keyboard(tx_id))
    else:
        await query.edit_message_reply_markup(reply_markup=None)


async def remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a transaction when the Remove button is pressed."""
    query = update.callback_query
    await query.answer()
    payload = json.loads(query.data)
    tx_id = payload["id"]

    repo = _get_repo(context)

    # Fetch tx details before deleting (for the notification)
    tx = await repo.get_transaction(tx_id)
    deleted = await repo.delete_transaction(tx_id)

    if deleted:
        await query.edit_message_text("🗑 Transaction removed.")
        # Notify workspace
        if tx:
            user = await repo.get_user(update.effective_user.id)
            if user:
                notifier = _get_notifier(context)
                targets = await _other_workspace_users(repo, tx.workspace_id_hash)
                await notifier.notify(
                    tx_id=tx_id,
                    actor_id=user.telegram_user_id,
                    target_user_ids=targets,
                    text=f"🗑 *{user.name}* removed:\n\n" + format_transaction_details(tx),
                )
    else:
        await query.edit_message_text("⚠️ Transaction not found.")


async def edit_value_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Receive the new value for a pending field edit, update DB, re-show confirmation."""
    pending = context.user_data.pop("pending_edit", None)
    if not pending:
        # No pending edit — fall through to the normal transaction handler
        return await handle_transaction_message(update, context)

    repo = _get_repo(context)
    tx_id = pending["tx_id"]
    field = pending["field"]
    raw_value = update.message.text.strip()

    # Validate & normalise
    if field == "amount":
        try:
            float(raw_value)
        except ValueError:
            await update.message.reply_text("⚠️ Amount must be a number. Try again:")
            context.user_data["pending_edit"] = pending  # re-set
            return
    elif field == "type":
        raw_value = raw_value.lower()
        if raw_value not in ("income", "expense"):
            await update.message.reply_text("⚠️ Type must be *income* or *expense*. Try again:",
                                            parse_mode=ParseMode.MARKDOWN)
            context.user_data["pending_edit"] = pending
            return
    elif field == "currency":
        raw_value = raw_value.upper()
    elif field == "category":
        raw_value = raw_value.lower()

    try:
        await repo.update_transaction(tx_id, field, raw_value)
    except Exception:
        logger.exception("Failed to update transaction %s field %s", tx_id, field)
        await update.message.reply_text("⚠️ Update failed. Please try again.")
        return

    tx = await repo.get_transaction(tx_id)
    if not tx:
        await update.message.reply_text("⚠️ Transaction not found.")
        return

    await update.message.reply_text(
        "✅ *Updated*\n\n" + format_transaction_confirmation(tx),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_edit_keyboard(tx_id),
    )

    # Notify workspace
    actor = await repo.get_user(update.effective_user.id)
    if actor:
        notifier = _get_notifier(context)
        targets = await _other_workspace_users(repo, tx.workspace_id_hash)
        await notifier.notify(
            tx_id=tx_id,
            actor_id=actor.telegram_user_id,
            target_user_ids=targets,
            text=f"✏️ *{actor.name}* edited:\n\n" + format_transaction_details(tx),
        )


# ---------------------------------------------------------------------------
# /transactions
# ---------------------------------------------------------------------------

def _parse_date(text: str) -> datetime | None:
    """Try to parse a date string in common formats."""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


async def transactions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List transactions with optional date filters."""
    result = await _ensure_user(update, context)
    if not result:
        return
    user, ws = result

    repo = _get_repo(context)
    args = context.args or []

    date_from: datetime | None = None
    date_to: datetime | None = None

    if len(args) == 1:
        # /transactions DATE1 → single day
        date_from = _parse_date(args[0])
        if date_from:
            date_to = date_from + timedelta(days=1, seconds=-1)
    elif len(args) == 2:
        date_from = _parse_date(args[0])
        if args[1].lower() == "now":
            date_to = datetime.utcnow()
        else:
            d2 = _parse_date(args[1])
            if d2:
                date_to = d2 + timedelta(days=1, seconds=-1)

    transactions = await repo.get_transactions(
        user.workspace_id_hash,
        date_from=date_from,
        date_to=date_to,
    )

    user_names = await repo.get_workspace_user_names(user.workspace_id_hash)
    text = format_transaction_list(transactions, user_names=user_names)

    # Add summary if filters are set
    if date_from or date_to:
        summary = await repo.summarize_transactions(
            user.workspace_id_hash,
            date_from=date_from,
            date_to=date_to,
            currency=ws.default_currency,
        )
        text += "\n" + format_summary(summary)

    # Build inline "Download CSV" button with date filters encoded
    cb_data = json.dumps(
        {
            "a": "csv",
            "f": date_from.isoformat() if date_from else None,
            "t": date_to.isoformat() if date_to else None,
        },
        separators=(",", ":"),
    )
    keyboard = [[InlineKeyboardButton("📥 Download CSV", callback_data=cb_data)]]

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ---------------------------------------------------------------------------
# /summary
# ---------------------------------------------------------------------------

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show income / expenses / net summary with optional date filters."""
    result = await _ensure_user(update, context)
    if not result:
        return
    user, ws = result

    repo = _get_repo(context)
    args = context.args or []

    date_from: datetime | None = None
    date_to: datetime | None = None

    if len(args) == 1:
        date_from = _parse_date(args[0])
        if date_from:
            date_to = date_from + timedelta(days=1, seconds=-1)
    elif len(args) == 2:
        date_from = _parse_date(args[0])
        if args[1].lower() == "now":
            date_to = datetime.utcnow()
        else:
            d2 = _parse_date(args[1])
            if d2:
                date_to = d2 + timedelta(days=1, seconds=-1)

    summary = await repo.summarize_transactions(
        user.workspace_id_hash,
        date_from=date_from,
        date_to=date_to,
        currency=ws.default_currency,
    )

    # Build header with date range info
    if date_from and date_to:
        header = (
            f"\U0001f4c5 *Period:* `{date_from.strftime('%Y-%m-%d')}` "
            f"\u2014 `{date_to.strftime('%Y-%m-%d')}`"
        )
    elif date_from:
        header = f"\U0001f4c5 *From:* `{date_from.strftime('%Y-%m-%d')}`"
    else:
        header = "\U0001f4c5 *All time*"

    text = header + "\n" + format_summary(summary)

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# CSV download callback
# ---------------------------------------------------------------------------

async def csv_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the 'Download CSV' inline button press."""
    query = update.callback_query
    await query.answer()

    result = await _ensure_user(update, context)
    if not result:
        return
    user, ws = result

    repo = _get_repo(context)

    # Decode date filters from callback_data
    try:
        payload = json.loads(query.data)
    except (json.JSONDecodeError, TypeError):
        await query.message.reply_text("⚠️ Invalid request.")
        return

    date_from = datetime.fromisoformat(payload["f"]) if payload.get("f") else None
    date_to = datetime.fromisoformat(payload["t"]) if payload.get("t") else None

    transactions = await repo.get_transactions(
        user.workspace_id_hash,
        date_from=date_from,
        date_to=date_to,
    )

    if not transactions:
        await query.message.reply_text("📭 No transactions to export.")
        return

    csv_bytes = generate_csv_bytes(transactions)
    filename = make_csv_filename(date_from=date_from, date_to=date_to)

    await query.message.reply_document(
        document=io.BytesIO(csv_bytes),
        filename=filename,
        caption=f"📥 Exported {len(transactions)} transactions.",
    )


# ---------------------------------------------------------------------------
# /change_currency
# ---------------------------------------------------------------------------

async def change_currency_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Change the workspace default currency and convert all existing transactions."""
    result = await _ensure_user(update, context)
    if not result:
        return
    user, ws = result

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/change_currency EUR`\n"
            "This will convert all your transactions to the new currency.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    new_currency = args[0].strip().upper()
    if new_currency == ws.default_currency:
        await update.message.reply_text(
            f"Your currency is already `{new_currency}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    repo = _get_repo(context)

    await update.message.reply_text(
        f"💱 Converting all transactions from `{ws.default_currency}` → `{new_currency}`…",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        count = await repo.convert_all_transactions(
            user.workspace_id_hash,
            new_currency,
            converter=convert_amount,
        )
    except Exception:
        logger.exception("Bulk currency conversion failed")
        await update.message.reply_text("⚠️ Conversion failed. Please try again.")
        return

    # Update workspace currency
    await repo.update_workspace_currency(user.workspace_id_hash, new_currency)

    await update.message.reply_text(
        f"✅ Done!\n\n"
        f"  • Default currency: `{new_currency}`\n"
        f"  • Transactions converted: `{count}`",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# /question
# ---------------------------------------------------------------------------

async def question_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answer a natural-language question about finances."""
    result = await _ensure_user(update, context)
    if not result:
        return
    user, ws = result

    question_text = " ".join(context.args) if context.args else ""
    if not question_text:
        await update.message.reply_text("Usage: /question How much did I spend on food?")
        return

    settings = _get_settings(context)
    repo = _get_repo(context)

    try:
        answer = await ask_question(
            question_text,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            repo=repo,
            workspace_id=user.workspace_id_hash,
            user_name=user.name,
            user_currency=ws.default_currency,
            user_id=user.telegram_user_id,
        )
    except Exception:
        logger.exception("Q&A failed for question: %s", question_text)
        answer = "⚠️ Sorry, I couldn't process that question."

    await update.message.reply_text(f"🤖 {answer}")


# ---------------------------------------------------------------------------
# Build the Telegram Application
# ---------------------------------------------------------------------------

def create_bot_app(settings: Settings, repo: Repository) -> Application:
    """Configure and return the python-telegram-bot Application."""
    app = Application.builder().token(settings.telegram_bot_token).build()

    # Store shared resources
    app.bot_data["repo"] = repo
    app.bot_data["settings"] = settings
    app.bot_data["notifier"] = NotificationService(app.bot)

    # Logging middleware — logs every incoming update
    app.add_handler(TypeHandler(Update, _log_update), group=-1)

    # Onboarding conversation
    onboarding = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            CHOOSE_ACTION: [CallbackQueryHandler(action_chosen)],
            ENTER_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, hash_entered)],
            ENTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_entered)],
            ENTER_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, currency_entered)],
            ENTER_INITIAL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, initial_amount_entered)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )
    app.add_handler(onboarding)

    # Commands
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("transactions", transactions_command))
    app.add_handler(CommandHandler("summary", summary_command))
    app.add_handler(CommandHandler("question", question_command))
    app.add_handler(CommandHandler("change_currency", change_currency_command))

    # Persistent "📖 Help" keyboard button
    app.add_handler(
        MessageHandler(filters.Regex(r"^📖\s*Help$"), help_button_handler)
    )

    # CSV download callback
    app.add_handler(CallbackQueryHandler(csv_download_callback, pattern=r'^\{"a":"csv"'))

    # Edit transaction callbacks
    app.add_handler(CallbackQueryHandler(edit_button_callback, pattern=r'^\{"a":"edit"'))
    app.add_handler(CallbackQueryHandler(edit_field_callback, pattern=r'^\{"a":"ef"'))
    app.add_handler(CallbackQueryHandler(edit_cancel_callback, pattern=r'^\{"a":"ecancel"'))
    app.add_handler(CallbackQueryHandler(remove_callback, pattern=r'^\{"a":"rm"'))

    # Default: edit value handler (checks for pending edit, else falls through
    # to handle_transaction_message)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value_handler))

    return app
