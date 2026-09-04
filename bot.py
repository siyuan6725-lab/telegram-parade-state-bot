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

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Asia/Singapore"))
DB_FILE = os.getenv("DB_FILE", "bot_state.db")

POLL_OPTIONS = [
    "Camp AM", "Camp PM", "OOC AM", "OOC PM",
    "LL AM", "LL PM", "MC", "MA AM"
]

# Database Setup
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS members (user_id INTEGER PRIMARY KEY, username TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS todays_votes (user_id INTEGER PRIMARY KEY)")
        conn.commit()

def save_member(user_id: int, username: str):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO members (user_id, username) VALUES (?, ?)", (user_id, username or "Unknown"))
        conn.commit()

def record_vote(user_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO todays_votes (user_id) VALUES (?)", (user_id,))
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

# Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_member(user.id, user.username)
    await update.message.reply_text(f"👋 Hi {user.first_name}! You are registered for Parade State reminders.")

async def track_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tracks when a user casts or updates a vote."""
    answer = update.poll_answer
    record_vote(answer.user.id)

# Core Scheduled Tasks
async def auto_send_morning_poll(context: ContextTypes.DEFAULT_TYPE):
    clear_daily_votes()
    tomorrow = datetime.datetime.now(TIMEZONE) + datetime.timedelta(days=1)
    date_str = tomorrow.strftime("%d/%m/%y")
    
    await context.bot.send_poll(
        chat_id=CHAT_ID,
        question=f"Parade State for {date_str}",
        options=POLL_OPTIONS,
        is_anonymous=False,
        allows_multiple_answers=True,
    )

async def auto_send_dm_to_non_voters(context: ContextTypes.DEFAULT_TYPE):
    non_voter_ids = get_non_voters()
    reminder_text = "📢 **Parade State Reminder**: You haven't submitted your vote for today's poll yet. Please vote in the group chat!"

    for user_id in non_voter_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=reminder_text, parse_mode="Markdown")
        except Exception as e:
            print(f"Could not send DM to {user_id}: {e}")

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    job_queue = app.job_queue

    # Register Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(PollAnswerHandler(track_poll_answer))

    # Daily Automatic Schedule (Asia/Singapore)
    # 1. Automatic Poll creation at 7:00 AM
    job_queue.run_daily(
        auto_send_morning_poll,
        time=datetime.time(hour=7, minute=0, second=0, tzinfo=TIMEZONE)
    )
    # 2. Direct message reminders to non-voters at 7:01 AM
    job_queue.run_daily(
        auto_send_dm_to_non_voters,
        time=datetime.time(hour=7, minute=1, second=0, tzinfo=TIMEZONE)
    )

    app.run_polling()

if __name__ == "__main__":
    main()