import datetime
import os
import sqlite3
from dotenv import load_dotenv
import pytz
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# Load environment variables from a local .env file (if present)
load_dotenv()

# Configuration — Reads secrets securely from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID_ENV = os.getenv("CHAT_ID")
ADMIN_ID_ENV = os.getenv("ADMIN_ID")

# Ensure required credentials are present
if not BOT_TOKEN or not CHAT_ID_ENV or not ADMIN_ID_ENV:
    raise ValueError(
        "Missing required environment variables! Ensure BOT_TOKEN, CHAT_ID, and ADMIN_ID are set."
    )

CHAT_ID = int(CHAT_ID_ENV)
ADMIN_ID = int(ADMIN_ID_ENV)
TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Asia/Singapore"))
DB_FILE = os.getenv("DB_FILE", "bot_state.db")

POLL_OPTIONS = [
    "Camp AM",
    "Camp PM",
    "OOC AM",
    "OOC PM",
    "LL AM",
    "LL PM",
    "MC",
    "MA AM",
    "MA PM",
    "Others",
]


# Database Setup
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.commit()


def set_poll_id(message_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
            ("latest_poll_message_id", str(message_id)),
        )
        conn.commit()


def get_poll_id() -> int | None:
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM state WHERE key = 'latest_poll_message_id'"
        )
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] else None


# Error Handling
async def send_error_alert(
    context: ContextTypes.DEFAULT_TYPE, task_name: str, error: Exception
):
    error_msg = (
        f"⚠️ **Bot Alert**: Failure in `{task_name}`\n\n"
        f"**Error Details:**\n`{str(error)}`"
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID, text=error_msg, parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Failed to send error alert to admin: {e}")


# Core Bot Actions
async def execute_send_poll(context: ContextTypes.DEFAULT_TYPE):
    tomorrow = datetime.datetime.now(TIMEZONE) + datetime.timedelta(days=1)
    date_str = tomorrow.strftime("%d/%m/%y")
    question = f"Parade State for {date_str}"

    message = await context.bot.send_poll(
        chat_id=CHAT_ID,
        question=question,
        options=POLL_OPTIONS,
        is_anonymous=False,
        allows_multiple_answers=False,
    )
    set_poll_id(message.message_id)


async def execute_send_reminder(context: ContextTypes.DEFAULT_TYPE):
    reminder_text = (
        "📢 **Reminder**: Please remember to submit your Parade State for today if you haven't already!"
    )
    poll_id = get_poll_id()

    if poll_id:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=reminder_text,
            reply_to_message_id=poll_id,
            parse_mode="Markdown",
        )
    else:
        await context.bot.send_message(
            chat_id=CHAT_ID, text=reminder_text, parse_mode="Markdown"
        )


# Scheduled Tasks
async def send_night_poll(context: ContextTypes.DEFAULT_TYPE):
    try:
        await execute_send_poll(context)
    except Exception as e:
        await send_error_alert(context, "send_night_poll", e)


async def send_morning_reminder(context: ContextTypes.DEFAULT_TYPE):
    try:
        await execute_send_reminder(context)
    except Exception as e:
        await send_error_alert(context, "send_morning_reminder", e)


# Manual Commands
async def manual_poll_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        await execute_send_poll(context)
        await update.message.reply_text("✅ Poll created successfully.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to create poll: {e}")


async def manual_reminder_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        await execute_send_reminder(context)
        await update.message.reply_text("✅ Reminder sent successfully.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send reminder: {e}")


def main():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    job_queue = app.job_queue

    # Register Manual Commands
    app.add_handler(CommandHandler("pollnow", manual_poll_command))
    app.add_handler(CommandHandler("remindnow", manual_reminder_command))

    # Daily Schedule (8:00 PM Poll, 8:00 AM Reminder)
    job_queue.run_daily(
        send_night_poll,
        time=datetime.time(hour=20, minute=0, second=0, tzinfo=TIMEZONE),
    )
    job_queue.run_daily(
        send_morning_reminder,
        time=datetime.time(hour=8, minute=0, second=0, tzinfo=TIMEZONE),
    )

    print("Bot is up and running safely!")
    app.run_polling()


if __name__ == "__main__":
    main()