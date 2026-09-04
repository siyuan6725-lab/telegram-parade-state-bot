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
    PollAnswerHandler,
)

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
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
]


# Database Management
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS members (user_id INTEGER PRIMARY KEY, username TEXT)"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS todays_votes (user_id INTEGER PRIMARY KEY)"
        )
        conn.commit()


def save_member(user_id: int, username: str):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO members (user_id, username) VALUES (?, ?)",
            (user_id, username or "Unknown"),
        )
        conn.commit()


def record_vote(user_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO todays_votes (user_id) VALUES (?)",
            (user_id,),
        )
        conn.commit()


def clear_daily_votes():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM todays_votes")
        conn.commit()


def get_non_voters() -> list[int]:
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT m.user_id FROM members m 
            LEFT JOIN todays_votes v ON m.user_id = v.user_id 
            WHERE v.user_id IS NULL
        """)
        return [row[0] for row in cursor.fetchall()]


def set_last_poll_date(date_str: str):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO state (key, value) VALUES ('last_poll_date', ?)",
            (date_str,),
        )
        conn.commit()


def get_last_poll_date() -> str | None:
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM state WHERE key = 'last_poll_date'")
        row = cursor.fetchone()
        return row[0] if row else None


# Event Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registers group members into DB when they DM /start to the bot."""
    user = update.effective_user
    save_member(user.id, user.username)
    await update.message.reply_text(
        f"👋 Hi {user.first_name}! You are registered for Parade State direct message reminders."
    )


async def track_poll_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Tracks votes as users submit them on the poll."""
    answer = update.poll_answer
    record_vote(answer.user.id)


async def execute_poll_creation(context: ContextTypes.DEFAULT_TYPE):
    """Sends the daily poll and locks duplicate postings for 24h."""
    now = datetime.datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")

    clear_daily_votes()
    date_str = now.strftime("%d/%m/%y")

    await context.bot.send_poll(
        chat_id=CHAT_ID,
        question=f"Parade State for {date_str}",
        options=POLL_OPTIONS,
        is_anonymous=False,
        allows_multiple_answers=True,
    )
    set_last_poll_date(today_str)


# Scheduled Core Tasks
async def auto_send_morning_poll(context: ContextTypes.DEFAULT_TYPE):
    """Runs automatically at 07:00 AM SGT."""
    now = datetime.datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")

    if get_last_poll_date() == today_str:
        return

    await execute_poll_creation(context)


async def auto_send_dm_to_non_voters(context: ContextTypes.DEFAULT_TYPE):
    """Runs automatically at 07:01 AM SGT to DM remaining non-voters."""
    non_voter_ids = get_non_voters()
    reminder_text = "📢 **Parade State Reminder**: You haven't submitted your status for today's poll yet. Please vote in the group chat!"

    for user_id in non_voter_ids:
        try:
            await context.bot.send_message(
                chat_id=user_id, text=reminder_text, parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Could not send DM to {user_id}: {e}")


# Manual Overrides
async def manual_poll_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_user.id != ADMIN_ID:
        return

    now = datetime.datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")

    if get_last_poll_date() == today_str:
        await update.message.reply_text(
            "⚠️ Poll has already been created for today."
        )
        return

    await execute_poll_creation(context)
    await update.message.reply_text("✅ Poll created manually.")


def main():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    job_queue = app.job_queue

    # Register Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("pollnow", manual_poll_command))
    app.add_handler(PollAnswerHandler(track_poll_answer))

    # Daily Schedule (Singapore Time)
    # 1. Post Poll automatically at 7:00 AM
    job_queue.run_daily(
        auto_send_morning_poll,
        time=datetime.time(hour=7, minute=0, second=0, tzinfo=TIMEZONE),
    )
    # 2. Send private DM reminders to non-voters at 7:01 AM
    job_queue.run_daily(
        auto_send_dm_to_non_voters,
        time=datetime.time(hour=7, minute=1, second=0, tzinfo=TIMEZONE),
    )

    print("Bot is running on Termux (Asia/Singapore)...")
    app.run_polling()


if __name__ == "__main__":
    main()