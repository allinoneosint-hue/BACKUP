import asyncio
import html
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse, parse_qs

from aiohttp import web
import httpx
from telegram import (
    BotCommand,
    ChatMember,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    MenuButtonCommands,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError, Conflict
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    ChatMemberHandler,
    filters,
)

# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "8762229764:AAG6Zeh7DPZ7Z-UrDE17DZF75d9Gxhin9d0")

ADMIN_ID_1 = os.getenv("ADMIN_ID_1", "8925611507")
ADMIN_ID_2 = os.getenv("ADMIN_ID_2", "8221567311")

AUDIT_LOG_CHANNEL_ID = os.getenv("AUDIT_LOG_CHANNEL_ID", "-1004345195932")

BRAND = "OBSIDIAN TRACE"
DB_FILE = "bot.db"
REQUEST_TIMEOUT = 25.0
MAX_MESSAGE_LENGTH = 3900
USERS_PER_PAGE = 10

DEFAULT_PRIVATE_LIMIT = int(os.getenv("DEFAULT_PRIVATE_LIMIT", "3"))
DEFAULT_GROUP_LIMIT = int(os.getenv("DEFAULT_GROUP_LIMIT", "4"))
DEFAULT_REFERRAL_BONUS = 1
DEFAULT_FREEZE_MINUTES = 5

OWNER_CONTACTS = "@pulkitinfobot, @KRUTIK_CYBER_DEVELOPER5"

RESTRICTED_QUERY_NUMBERS = {
    "6354013541",
    "9313565791",
    "9978463026",
    "8679678741",
}

RESTRICTED_TG_IDS = {
    "6653985765",
    "8051539455",
    "7272787842",
    "8221567311",
}

# Production concurrency & limits
SEMAPHORE = asyncio.Semaphore(50)
HTTP_CLIENT: Optional[httpx.AsyncClient] = None

USER_SPAM_MAP = {}
USER_FREEZE_MAP = {}
ADMIN_STATE = {}

# ============================================================
# EXTERNAL APIS CONFIG
# ============================================================

NUMBER_API_PRIMARY = "https://api.osintxc.com/num"
NUMBER_API_URL = NUMBER_API_PRIMARY
NUMBER_API_KEY = "PULKIT"
NUMBER_API_BACKUP = ""

VEHICLE_API_PRIMARY = "http://rajfflivebot.onrender.com/pub/rajfflive/vnum"
VEHICLE_API_URL = VEHICLE_API_PRIMARY
VEHICLE_API_KEY = "RAJBOTSOFC"
VEHICLE_API_BACKUP = "https://vehicleinfo-byrack.vercel.app/api?search="

ADHAR_API_URL = "https://api.osintxc.com/aadhaar"
ADHAR_API_KEY = "PULKIT"
ADHAR_API_BACKUP = "https://reuters-memorabilia-insulin-disclose.trycloudflare.com/aadhaar"

TG_API_URL = "https://luffy-telegram-bot.onrender.com"
TG_TO_NUM_PRIMARY = TG_API_URL
TG_TO_NUM_API_KEY = "felix99"
TG_TO_NUM_BACKUP = ""

GMAIL_PRIMARY = "https://api.osintxc.com/email"
GMAIL_KEY = "PULKIT"
GMAIL_BACKUP = ""
GMAIL_BACKUP_ALT = ""

TRUECALLER_API_URL = "https://rack-72au.onrender.com/truecaller"
PINCODE_API_URL = "https://rack-pincodeapi.vercel.app/api"
IFSC_API_URL = "https://vercei-kappa.vercel.app/ifsc"
IP_API_URL = "https://ip-dwy8.onrender.com/api/rackipapi"
WEATHER_API_BASE_URL = "https://rack-weather.vercel.app/api/weather"
GST_API_URL = "https://rack-gstinfo.vercel.app/all-search"
FAMILY_API_URL = "https://sahilxher.madewith.me/api/family"

INSTA_API_URL = "http://rajfflivebot.onrender.com/pub/rajinfoapi/insta"
INSTA_API_KEY = "78c8c14351ac39a8757db8d3c382bac2ce3c457f6d501f46"

FF_API_URL = "https://ffinfo-id-info.raadbhaiff.workers.dev/ffinfo"
FF_API_KEY = ""

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

# ============================================================
# LOGGING SETUP
# ============================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("OBSIDIAN_TRACE")

# ============================================================
# TIME HELPERS
# ============================================================

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def iso_now() -> str:
    return now_utc().isoformat()

def today_key() -> str:
    return now_utc().date().isoformat()

def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None

# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute("PRAGMA mmap_size=268435456;")
    conn.execute("PRAGMA cache_size=-32000;")
    return conn

def column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)

def add_column_if_missing(conn, table: str, column: str, definition: str):
    if not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def init_db():
    conn = db_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_banned INTEGER DEFAULT 0,
                is_unlimited INTEGER DEFAULT 0,
                custom_private_limit INTEGER DEFAULT -1,
                custom_group_limit INTEGER DEFAULT -1,
                one_day_credits INTEGER DEFAULT 0,
                plan_id INTEGER,
                plan_name TEXT,
                plan_started_at TEXT,
                plan_expires_at TEXT,
                plan_total_uses INTEGER DEFAULT 0,
                plan_used_uses INTEGER DEFAULT 0,
                daily_private_used INTEGER DEFAULT 0,
                daily_group_used INTEGER DEFAULT 0,
                referral_credits INTEGER DEFAULT 0,
                referred_by INTEGER,
                daily_date TEXT,
                total_searches INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                days INTEGER NOT NULL,
                uses INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracked_groups (
                group_id INTEGER PRIMARY KEY,
                group_title TEXT,
                total_searches INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                last_active TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS force_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                invite_link TEXT NOT NULL
            )
            """
        )

        add_column_if_missing(conn, "users", "is_unlimited", "INTEGER DEFAULT 0")
        add_column_if_missing(conn, "users", "custom_private_limit", "INTEGER DEFAULT -1")
        add_column_if_missing(conn, "users", "custom_group_limit", "INTEGER DEFAULT -1")
        add_column_if_missing(conn, "users", "one_day_credits", "INTEGER DEFAULT 0")
        add_column_if_missing(conn, "tracked_groups", "is_banned", "INTEGER DEFAULT 0")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_banned ON users(is_banned);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_daily_date ON users(daily_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracked_searches ON tracked_groups(total_searches DESC);")

        defaults = {
            "bot_enabled": "1",
            "force_join_enabled": "1",
            "private_limit": str(DEFAULT_PRIVATE_LIMIT),
            "group_limit": str(DEFAULT_GROUP_LIMIT),
            "referral_bonus": str(DEFAULT_REFERRAL_BONUS),
            "freeze_minutes": str(DEFAULT_FREEZE_MINUTES),
            "audit_log_channel": str(AUDIT_LOG_CHANNEL_ID),
            "admin_1": str(ADMIN_ID_1),
            "admin_2": str(ADMIN_ID_2),
            "welcome_text": "",
            "welcome_media_id": "",
            "welcome_media_type": "",
            "api_num": "1",
            "api_vehicle": "1",
            "api_adh": "1",
            "api_tg": "1",
            "api_gm": "1",
            "api_tc": "1",
            "api_pin": "1",
            "api_ifsc": "1",
            "api_ip": "1",
            "api_weather": "1",
            "api_gst": "1",
            "api_family": "1",
            "api_insta": "1",
            "api_ff": "1",
            "api_url_tg": TG_API_URL,
            "api_key_tg": TG_TO_NUM_API_KEY,
            "api_backup_url_tg": "",
        }

        for key, value in defaults.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO settings (key, value)
                VALUES (?, ?)
                """,
                (key, value),
            )

        conn.commit()
    finally:
        conn.close()

# ============================================================
# SETTINGS ENGINE
# ============================================================

def get_setting(key: str, default: str = "") -> str:
    conn = db_connection()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()

def set_setting(key: str, value: str):
    conn = db_connection()
    try:
        conn.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )
        conn.commit()
    finally:
        conn.close()

API_DEFAULTS = {
    "num": (NUMBER_API_URL, NUMBER_API_KEY),
    "vehicle": (VEHICLE_API_URL, VEHICLE_API_KEY),
    "adh": (ADHAR_API_URL, ADHAR_API_KEY),
    "tg": (TG_API_URL, TG_TO_NUM_API_KEY),
    "gm": (GMAIL_PRIMARY, GMAIL_KEY),
    "tc": (TRUECALLER_API_URL, ""),
    "pin": (PINCODE_API_URL, ""),
    "ifsc": (IFSC_API_URL, ""),
    "ip": (IP_API_URL, ""),
    "weather": (WEATHER_API_BASE_URL, ""),
    "gst": (GST_API_URL, ""),
    "family": (FAMILY_API_URL, ""),
    "insta": (INSTA_API_URL, INSTA_API_KEY),
    "ff": (FF_API_URL, FF_API_KEY),
}

API_BACKUP_DEFAULTS = {
    "num": (NUMBER_API_BACKUP, ""),
    "vehicle": (VEHICLE_API_BACKUP, VEHICLE_API_KEY),
    "adh": (ADHAR_API_BACKUP, ADHAR_API_KEY),
    "tg": ("", ""),
    "gm": (GMAIL_BACKUP, GMAIL_KEY),
    "tc": ("", ""),
    "pin": ("", ""),
    "ifsc": ("", ""),
    "ip": ("", ""),
    "weather": ("", ""),
    "gst": ("", ""),
    "family": ("", ""),
    "insta": ("", ""),
    "ff": ("", ""),
}

def api_config(name: str) -> tuple[str, str]:
    default_url, default_key = API_DEFAULTS.get(name, ("", ""))
    return get_setting(f"api_url_{name}", default_url), get_setting(f"api_key_{name}", default_key)

def api_backup_config(name: str) -> tuple[str, str]:
    default_url, default_key = API_BACKUP_DEFAULTS.get(name, ("", ""))
    return get_setting(f"api_backup_url_{name}", default_url), get_setting(f"api_backup_key_{name}", default_key)

def get_int_setting(key: str, default: int) -> int:
    try:
        return int(get_setting(key, str(default)))
    except Exception:
        return default

def bot_enabled() -> bool:
    return get_setting("bot_enabled", "1") == "1"

def force_join_active() -> bool:
    return get_setting("force_join_enabled", "1") == "1"

def api_is_active(api_name: str) -> bool:
    return get_setting(f"api_{api_name}", "1") == "1"

def toggle_api_status(api_name: str) -> bool:
    new_val = "0" if api_is_active(api_name) else "1"
    set_setting(f"api_{api_name}", new_val)
    return new_val == "1"

def get_private_limit() -> int:
    return get_int_setting("private_limit", DEFAULT_PRIVATE_LIMIT)

def get_group_limit() -> int:
    return get_int_setting("group_limit", DEFAULT_GROUP_LIMIT)

def get_referral_bonus() -> int:
    return get_int_setting("referral_bonus", DEFAULT_REFERRAL_BONUS)

def get_freeze_minutes() -> int:
    return get_int_setting("freeze_minutes", DEFAULT_FREEZE_MINUTES)

def get_audit_channel() -> int:
    return get_int_setting("audit_log_channel", int(AUDIT_LOG_CHANNEL_ID) if str(AUDIT_LOG_CHANNEL_ID).lstrip("-").isdigit() else 0)

# ============================================================
# AUDIT LOGGING
# ============================================================

async def send_audit_log(context: ContextTypes.DEFAULT_TYPE, log_text: str):
    log_ch = get_audit_channel()
    if not log_ch or log_ch == 0:
        return
    try:
        await context.bot.send_message(
            chat_id=log_ch,
            text=log_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logger.warning("Audit forward log error: %s", exc)

def dispatch_audit_log(context: ContextTypes.DEFAULT_TYPE, log_text: str):
    asyncio.create_task(send_audit_log(context, log_text))

# ============================================================
# ADMIN AUTHENTICATION
# ============================================================

def get_admin_ids() -> set[int]:
    ids = set()
    try:
        adm1 = get_int_setting("admin_1", int(ADMIN_ID_1))
        if adm1:
            ids.add(adm1)
    except Exception:
        pass
    try:
        adm2 = get_int_setting("admin_2", int(ADMIN_ID_2))
        if adm2:
            ids.add(adm2)
    except Exception:
        pass
    return ids

def is_admin(user_id: int) -> bool:
    return user_id in get_admin_ids()

async def require_admin(update: Update) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not is_admin(user.id):
        if update.message:
            await update.message.reply_text("❌ Unauthorized access.")
        return False
    if chat and chat.type != "private":
        if update.message:
            await update.message.reply_text("🔒 Admin panel operates exclusively in private chat.")
        return False
    await asyncio.to_thread(ensure_user, user)
    return True

# ============================================================
# ANTI-FLOOD & MEMORY MAINTENANCE
# ============================================================

def check_spam_and_freeze(user_id: int) -> tuple[bool, int]:
    if is_admin(user_id):
        return False, 0

    now_t = now_utc()

    if user_id in USER_FREEZE_MAP:
        unfreeze_time = USER_FREEZE_MAP[user_id]
        if now_t < unfreeze_time:
            rem_seconds = int((unfreeze_time - now_t).total_seconds())
            rem_mins = max(1, rem_seconds // 60)
            return True, rem_mins
        else:
            del USER_FREEZE_MAP[user_id]
            USER_SPAM_MAP.pop(user_id, None)

    history = USER_SPAM_MAP.get(user_id, [])
    cutoff = now_t - timedelta(seconds=10)
    history = [t for t in history if t > cutoff]
    history.append(now_t)
    USER_SPAM_MAP[user_id] = history

    if len(history) > 8:
        freeze_mins = get_freeze_minutes()
        USER_FREEZE_MAP[user_id] = now_t + timedelta(minutes=freeze_mins)
        return True, freeze_mins

    return False, 0

async def memory_garbage_collector():
    while True:
        try:
            await asyncio.sleep(600)
            now_t = now_utc()
            cutoff = now_t - timedelta(minutes=15)
            
            expired_spam = [uid for uid, times in list(USER_SPAM_MAP.items()) if not times or times[-1] < cutoff]
            for uid in expired_spam:
                USER_SPAM_MAP.pop(uid, None)
                
            expired_freeze = [uid for uid, unfreeze in list(USER_FREEZE_MAP.items()) if unfreeze < now_t]
            for uid in expired_freeze:
                USER_FREEZE_MAP.pop(uid, None)
        except Exception as exc:
            logger.warning("Garbage collector loop caught: %s", exc)

# ============================================================
# USER & GROUP TRACKING
# ============================================================

def ensure_user(user, referrer_id: Optional[int] = None) -> tuple[bool, Optional[int]]:
    if not user:
        return False, None
    conn = db_connection()
    awarded_referrer = None
    try:
        row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user.id,)).fetchone()
        cur_iso = iso_now()

        if row is None:
            valid_referrer = None
            if referrer_id and referrer_id != user.id:
                ref_user = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,)).fetchone()
                if ref_user:
                    valid_referrer = referrer_id

            conn.execute(
                """
                INSERT INTO users (
                    user_id, username, first_name, last_name,
                    daily_private_used, daily_group_used, referral_credits,
                    referred_by, daily_date, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 0, 0, 0, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    user.username,
                    user.first_name,
                    user.last_name,
                    valid_referrer,
                    today_key(),
                    cur_iso,
                    cur_iso,
                ),
            )

            if valid_referrer:
                bonus = get_referral_bonus()
                conn.execute(
                    """
                    UPDATE users
                    SET referral_credits = referral_credits + ?,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (bonus, cur_iso, valid_referrer),
                )
                awarded_referrer = valid_referrer

            conn.commit()
            return True, awarded_referrer
        else:
            conn.execute(
                """
                UPDATE users
                SET username = ?, first_name = ?, last_name = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (user.username, user.first_name, user.last_name, cur_iso, user.id),
            )
            conn.commit()
            return False, None
    finally:
        conn.close()

def get_user(user_id: int):
    conn = db_connection()
    try:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    finally:
        conn.close()

def reset_daily_usage_if_needed(user_id: int):
    today = today_key()
    conn = db_connection()
    try:
        row = conn.execute("SELECT daily_date FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row and row["daily_date"] != today:
            conn.execute(
                """
                UPDATE users
                SET daily_private_used = 0,
                    daily_group_used = 0,
                    one_day_credits = 0,
                    daily_date = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (today, iso_now(), user_id),
            )
            conn.commit()
    finally:
        conn.close()

def record_group_activity(chat):
    if not chat or chat.type not in ("group", "supergroup"):
        return
    conn = db_connection()
    try:
        conn.execute(
            """
            INSERT INTO tracked_groups (group_id, group_title, total_searches, is_banned, last_active)
            VALUES (?, ?, 1, 0, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                group_title = excluded.group_title,
                total_searches = total_searches + 1,
                last_active = excluded.last_active
            """,
            (chat.id, chat.title or "Untitled Group", iso_now()),
        )
        conn.commit()
    finally:
        conn.close()

def is_group_banned(group_id: int) -> bool:
    conn = db_connection()
    try:
        row = conn.execute("SELECT is_banned FROM tracked_groups WHERE group_id = ?", (group_id,)).fetchone()
        return bool(row and row["is_banned"] == 1)
    finally:
        conn.close()

def set_group_ban_status(group_id: int, banned: int):
    conn = db_connection()
    try:
        conn.execute("UPDATE tracked_groups SET is_banned = ? WHERE group_id = ?", (banned, group_id))
        conn.commit()
    finally:
        conn.close()

async def track_bot_added_to_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    if chat.type not in ("group", "supergroup"):
        return
    new_member = result.new_chat_member
    if new_member.user.id == context.bot.id:
        if new_member.status in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR):
            await asyncio.to_thread(record_group_activity, chat)

# ============================================================
# CHANNELS VERIFICATION
# ============================================================

def get_force_channels() -> list[sqlite3.Row]:
    conn = db_connection()
    try:
        return conn.execute("SELECT * FROM force_channels ORDER BY id ASC").fetchall()
    finally:
        conn.close()

def add_force_channel(username: str, invite_link: str) -> bool:
    username = str(username).strip()
    invite_link = str(invite_link).strip()
    if username and not username.startswith("@") and not username.lstrip("-").isdigit():
        username = f"@{username}"
    conn = db_connection()
    try:
        conn.execute("INSERT INTO force_channels (username, invite_link) VALUES (?, ?)", (username, invite_link))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_force_channel(channel_id: int):
    conn = db_connection()
    try:
        conn.execute("DELETE FROM force_channels WHERE id = ?", (channel_id,))
        conn.commit()
    finally:
        conn.close()

def build_verification_keyboard():
    channels = get_force_channels()
    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(f"📢 Join {ch['username']}", url=ch["invite_link"])])
    buttons.append([InlineKeyboardButton("⚡ Verify / Refresh ⚡", callback_data="check_channels")])
    return InlineKeyboardMarkup(buttons)

async def check_single_member(bot, chat_id: str, user_id: int) -> bool:
    try:
        target = str(chat_id or "").strip()
        if not target:
            return False
        if target.startswith(("https://t.me/", "http://t.me/")):
            path = urlparse(target).path.strip("/")
            if not path or path.startswith("+") or path.startswith("joinchat/"):
                return False
            target = path.split("/", 1)[0]
        if target.lstrip("-").isdigit():
            target = int(target)
        elif not target.startswith("@"):
            target = "@" + target

        chat = await bot.get_chat(chat_id=target)
        member = await bot.get_chat_member(chat_id=chat.id, user_id=user_id)
        status = getattr(member, "status", "")
        status_value = str(getattr(status, "value", status)).lower()
        if status_value in ("left", "kicked", "banned"):
            return False
        if status_value == "restricted":
            return bool(getattr(member, "is_member", False))
        return status_value in ("creator", "administrator", "member")
    except Exception as exc:
        logger.warning("Verification check failure on channel %r for user %s: %s", chat_id, user_id, exc)
        return False

async def is_user_verified(bot, user_id: int) -> bool:
    if is_admin(user_id) or not force_join_active():
        return True
    channels = await asyncio.to_thread(get_force_channels)
    if not channels:
        return True
    tasks = [check_single_member(bot, ch["username"], user_id) for ch in channels]
    results = await asyncio.gather(*tasks)
    return all(results)

# ============================================================
# PLANS MANAGEMENT
# ============================================================

def get_plan(plan_id: int):
    conn = db_connection()
    try:
        return conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    finally:
        conn.close()

def list_plans():
    conn = db_connection()
    try:
        return conn.execute("SELECT * FROM plans ORDER BY id ASC").fetchall()
    finally:
        conn.close()

def create_plan(name: str, days: int, uses: int):
    conn = db_connection()
    try:
        cur = conn.execute("INSERT INTO plans (name, days, uses, created_at) VALUES (?, ?, ?, ?)", (name, days, uses, iso_now()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()

def delete_plan(plan_id: int):
    conn = db_connection()
    try:
        conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        conn.commit()
    finally:
        conn.close()

def assign_plan(user_id: int, plan_id: int):
    plan = get_plan(plan_id)
    if not plan:
        return False, "Plan not found."
    start_time = now_utc()
    expire_time = start_time + timedelta(days=plan["days"])
    conn = db_connection()
    try:
        conn.execute(
            """
            UPDATE users
            SET plan_id = ?, plan_name = ?, plan_started_at = ?,
                plan_expires_at = ?, plan_total_uses = ?, plan_used_uses = 0,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                plan["id"],
                plan["name"],
                start_time.isoformat(),
                expire_time.isoformat(),
                plan["uses"],
                iso_now(),
                user_id,
            ),
        )
        conn.commit()
        return True, f"Plan <code>{html.escape(plan['name'])}</code> assigned."
    finally:
        conn.close()

def revoke_plan(user_id: int):
    conn = db_connection()
    try:
        conn.execute(
            """
            UPDATE users
            SET plan_id = NULL, plan_name = NULL, plan_started_at = NULL,
                plan_expires_at = NULL, plan_total_uses = 0, plan_used_uses = 0,
                updated_at = ?
            WHERE user_id = ?
            """,
            (iso_now(), user_id),
        )
        conn.commit()
    finally:
        conn.close()

def plan_is_active(user_row) -> bool:
    if not user_row or not user_row["plan_id"]:
        return False
    expires = parse_iso(user_row["plan_expires_at"])
    if not expires or expires <= now_utc():
        return False
    if user_row["plan_total_uses"] <= user_row["plan_used_uses"]:
        return False
    return True

# ============================================================
# FORMATTERS
# ============================================================

def make_bar(current: int, total: int, length: int = 8) -> str:
    if total <= 0:
        return "■" * length
    fraction = min(max(current / total, 0.0), 1.0)
    filled = int(fraction * length)
    return "■" * filled + "□" * (length - filled)

def format_status_card(row, user) -> str:
    p_lim = row["custom_private_limit"] if row["custom_private_limit"] >= 0 else get_private_limit()
    g_lim = row["custom_group_limit"] if row["custom_group_limit"] >= 0 else get_group_limit()
    p_used = row["daily_private_used"]
    g_used = row["daily_group_used"]
    p_bar = make_bar(p_used, p_lim) if p_lim > 0 else "■" * 8
    g_bar = make_bar(g_used, g_lim) if g_lim > 0 else "■" * 8
    plan_title, plan_quota, plan_expiry = "None (Free Tier)", "N/A", "N/A"
    if row["is_unlimited"]:
        plan_title, plan_quota, plan_expiry = "⚡ LOHAVAT MASTER MATRIX", "Unlimited", "Lifetime"
    elif row["plan_id"]:
        plan_title = row["plan_name"] or "Active Plan"
        rem_plan = max(0, row["plan_total_uses"] - row["plan_used_uses"])
        plan_quota = f"{rem_plan} / {row['plan_total_uses']}"
        exp = parse_iso(row["plan_expires_at"])
        plan_expiry = exp.strftime("%d %b %Y, %H:%M UTC") if exp else "Unknown"
    return (
        f"⌬ <b>{BRAND}.OSINT</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"⟡ <b>ACCOUNT RECORD</b> / {user.id}\n"
        f"┌─ <b>OPERATIVE DATA</b> ──\n"
        f"│ Name    / {html.escape(user.first_name or 'User')}\n"
        f"│ ID      / <code>{user.id}</code>\n"
        f"│ Blocked / {'YES' if row['is_banned'] else 'NO'}\n"
        f"└─────────────────\n\n"
        f"⟡ <b>QUOTA METRICS</b>\n"
        f"│ Private / <code>[{p_bar}]</code> {p_used}/{p_lim if p_lim > 0 else '∞'}\n"
        f"│ Group   / <code>[{g_bar}]</code> {g_used}/{g_lim if g_lim > 0 else '∞'}\n"
        f"│ Credits / <code>{row['one_day_credits']}</code>\n"
        f"│ Referrals / <code>{row['referral_credits']}</code>\n"
        f"│ Searches / <code>{row['total_searches']}</code>\n\n"
        f"⟡ <b>SUBSCRIPTION</b>\n"
        f"│ Plan    / {html.escape(plan_title)}\n"
        f"│ Quota   / {plan_quota}\n"
        f"│ Expires / {plan_expiry}\n"
        f"━━━━━━━━━━━━━━━━━━\n⌬ <b>END_SIGNAL</b>"
    )

def format_result_card(data_content: str) -> str:
    return (
        f"⌬ <b>{BRAND}.OSINT</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"⟡ <b>RECORD</b>      / 001\n"
        f"⟡ <b>QUERY</b>       / INTEL RESPONSE\n\n"
        f"┌─ <b>DATA OUTPUT</b> ─────\n"
        f"<pre>{html.escape(data_content)}</pre>"
        f"└─────────────────\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⌬ <b>END_SIGNAL</b> · {html.escape(BRAND)}"
    )

async def check_search_access(update: Update, context: ContextTypes.DEFAULT_TYPE, api_cmd: str) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return False

    if chat.type in ("group", "supergroup"):
        if await asyncio.to_thread(is_group_banned, chat.id):
            if update.message:
                await update.message.reply_text("⛔ <b>Group Suspended:</b> Blacklisted terminal node.", parse_mode=ParseMode.HTML)
            return False

    await asyncio.to_thread(ensure_user, user)
    await asyncio.to_thread(reset_daily_usage_if_needed, user.id)
    await asyncio.to_thread(record_group_activity, chat)

    is_frozen, rem_mins = check_spam_and_freeze(user.id)
    if is_frozen:
        if update.message:
            await update.message.reply_text(
                f"┌───「 <b>⚠️ SYSTEM LOCK ENGAGED</b> 」───\n"
                f"│ Excessive query requests detected!\n"
                f"│ Terminal frozen for <b>{rem_mins} minute(s)</b>.\n"
                f"└──────────────────────────────────────",
                parse_mode=ParseMode.HTML,
            )
        return False

    if is_admin(user.id):
        return True

    row = await asyncio.to_thread(get_user, user.id)
    if not row:
        return False

    if row["is_banned"]:
        if update.message:
            await update.message.reply_text("🚫 <b>Access Revoked:</b> You are permanently blacklisted.", parse_mode=ParseMode.HTML)
        return False

    if not bot_enabled():
        if update.message:
            await update.message.reply_text("🔴 <b>System Offline:</b> Terminal is under maintenance.", parse_mode=ParseMode.HTML)
        return False

    if not api_is_active(api_cmd):
        if update.message:
            await update.message.reply_text(f"⚠️ <b>Service Suspended:</b> Protocol <code>/{api_cmd}</code> is offline.", parse_mode=ParseMode.HTML)
        return False

    verified = await is_user_verified(context.bot, user.id)
    if not verified:
        reply_markup = build_verification_keyboard()
        if update.message:
            await update.message.reply_text(
                "🔒 <b>Mandatory Channel Verification Required!</b>\n\n"
                "Join our official channels below and tap <b>Verify / Refresh</b>:",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        return False

    if row["is_unlimited"]:
        return True

    is_private = (chat.type == "private")
    limit = row["custom_private_limit"] if (is_private and row["custom_private_limit"] >= 0) else (get_private_limit() if is_private else get_group_limit())
    if not is_private and row["custom_group_limit"] >= 0:
        limit = row["custom_group_limit"]

    used = row["daily_private_used"] if is_private else row["daily_group_used"]

    if limit == 0 or used < limit:
        return True

    if row["one_day_credits"] > 0:
        return True

    if row["referral_credits"] > 0:
        return True

    if plan_is_active(row):
        return True

    if update.message:
        await update.message.reply_text(
            f"┌───「 <b>⛔ QUOTA EXHAUSTED</b> 」───\n"
            f"│ Daily limit reached!\n"
            f"│ Contact owners to upgrade access:\n"
            f"├───「 <b>👑 CONTACT</b> 」───\n"
            f"│ ⚡ <b>{OWNER_CONTACTS}</b>\n"
            f"└──────────────────────────────────",
            parse_mode=ParseMode.HTML,
        )
    return False

def consume_search(user_id: int, is_private: bool):
    if is_admin(user_id):
        return

    reset_daily_usage_if_needed(user_id)
    conn = db_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return

        cur_iso = iso_now()
        limit = row["custom_private_limit"] if (is_private and row["custom_private_limit"] >= 0) else (get_private_limit() if is_private else get_group_limit())
        if not is_private and row["custom_group_limit"] >= 0:
            limit = row["custom_group_limit"]

        used = row["daily_private_used"] if is_private else row["daily_group_used"]

        if limit == 0 or used < limit:
            col = "daily_private_used" if is_private else "daily_group_used"
            conn.execute(
                f"""
                UPDATE users
                SET {col} = {col} + 1,
                    total_searches = total_searches + 1,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (cur_iso, user_id),
            )
        elif row["one_day_credits"] > 0:
            conn.execute(
                """
                UPDATE users
                SET one_day_credits = one_day_credits - 1,
                    total_searches = total_searches + 1,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (cur_iso, user_id),
            )
        elif row["referral_credits"] > 0:
            conn.execute(
                """
                UPDATE users
                SET referral_credits = referral_credits - 1,
                    total_searches = total_searches + 1,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (cur_iso, user_id),
            )
        else:
            conn.execute(
                """
                UPDATE users
                SET plan_used_uses = plan_used_uses + 1,
                    total_searches = total_searches + 1,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (cur_iso, user_id),
            )
        conn.commit()
    finally:
        conn.close()

# ============================================================
# RESPONSE SANITIZATION
# ============================================================

REPLACEMENT_TARGET = "@pulkitinfobot,@KRUTIK_CYBER_DEVELOPER5BOT"
SENSITIVE_REPLACEMENTS = [
    "@pulkitinfobot,@KRUTIK_CYBER_DEVELOPER5",
    "@BackemdHub",
    "CREDIT / INFO Owner: @shiva_158 Free API: @Osintinfooobot Free API ke liye Channel Join karein: https://t.me/osintinfoooo For Any Kind of API: @shiva_158",
    "@Osintinfooobot",
    "https://t.me/osintinfoooo",
    "@shiva_158",
    "@YeuIin",
    "@kihoerack",
    "@ftgamer2",
    "@RAJFFLIVE",
    "https://t.me/+QUg-JvyJizkxMzA1",
    "@RAJFFLIVEBOT",
    "@rajfflivebot",
    "@rajfflive",
    "@flirts_x",
    "🙏 जय माता दी 🙏",
    "rto_clone_v1",
    "@code_Xen",
    "Code Xen",
]

def sanitize_response(text: str) -> str:
    if not text:
        return text
    for old_val in SENSITIVE_REPLACEMENTS:
        text = re.sub(re.escape(old_val), REPLACEMENT_TARGET, text, flags=re.IGNORECASE)
    return text

def is_empty_payload(data) -> bool:
    if data is None:
        return True
    if isinstance(data, (dict, list)) and len(data) == 0:
        return True
    if isinstance(data, str):
        cleaned = data.strip().lower()
        if cleaned in ("", "null", "none", "{}", "[]", "not found", "no data found", "record not found", "error"):
            return True
    if isinstance(data, dict):
        if data.get("found") is False:
            return True
        if data.get("count") == 0:
            return True
        if "result" in data and is_empty_payload(data.get("result")):
            return True
        if "data" in data and is_empty_payload(data.get("data")):
            return True
        if data.get("status") in (False, "failed", "error"):
            return True
    return False

def format_json_response(raw_text: str) -> str:
    cleaned = sanitize_response(raw_text.strip())
    if not cleaned or is_empty_payload(cleaned):
        return "NOT FOUND"
    try:
        data = json.loads(cleaned)
        if is_empty_payload(data):
            return "NOT FOUND"
        return sanitize_response(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        return sanitize_response(cleaned)

async def send_result(update: Update, result: str):
    if not update.message:
        return
    display_result = "❌ NOT FOUND" if result == "NOT FOUND" else result
    card = format_result_card(display_result)
    if len(card) <= MAX_MESSAGE_LENGTH:
        try:
            await update.message.reply_text(card, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return
        except Exception:
            pass

    chunks = []
    start_pos = 0
    while start_pos < len(result):
        end_pos = min(start_pos + 3500, len(result))
        chunks.append(result[start_pos:end_pos])
        start_pos = end_pos
    for idx, c in enumerate(chunks, 1):
        await update.message.reply_text(
            f"<b>[PART {idx}/{len(chunks)}]</b>\n<pre>{html.escape(c)}</pre>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

# ============================================================
# DISPATCHER
# ============================================================

async def fetch_endpoint(url: str, params: dict) -> tuple[Optional[str], Optional[dict], str]:
    global HTTP_CLIENT
    async with SEMAPHORE:
        try:
            if HTTP_CLIENT is None or HTTP_CLIENT.is_closed:
                HTTP_CLIENT = httpx.AsyncClient(
                    timeout=REQUEST_TIMEOUT,
                    headers=BROWSER_HEADERS,
                    follow_redirects=True,
                    limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
                )
            resp = await HTTP_CLIENT.get(url, params=params if params else None)
            if resp.status_code in (404, 400, 422, 500, 502, 503):
                return None, None, f"HTTP_{resp.status_code}"
            resp.raise_for_status()
            raw = resp.text.strip()
            if not raw or is_empty_payload(raw):
                return None, None, "EMPTY"
            try:
                parsed = json.loads(raw)
                if is_empty_payload(parsed):
                    return None, None, "EMPTY_JSON"
                return raw, parsed, "SUCCESS"
            except Exception:
                return raw, None, "RAW_SUCCESS"
        except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException):
            return None, None, "TIMEOUT_OR_FAULT"
        except Exception:
            return None, None, "FAULT"

def public_vehicle_fields(data):
    if isinstance(data, list):
        return [public_vehicle_fields(item) for item in data]
    if not isinstance(data, dict):
        return data
    private_terms = (
        "owner", "father", "address", "mobile", "phone", "contact",
        "aadhaar", "aadhar", "email", "dob", "birth", "financer",
        "insurancecompany", "policy", "nominee", "personname",
    )
    result = {}
    for key, value in data.items():
        normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
        if any(term in normalized for term in private_terms):
            continue
        if isinstance(value, (dict, list)):
            filtered = public_vehicle_fields(value)
            if filtered not in ({}, []):
                result[key] = filtered
        else:
            result[key] = value
    return result

async def execute_api_search(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, params: dict, cmd_name: str, target_val: str):
    user = update.effective_user
    chat = update.effective_chat
    searching_msg = None

    if update.message:
        try:
            searching_msg = await update.message.reply_text("⚙️ <code>Decrypting Lohavat Nodes... querying ⏳</code>", parse_mode=ParseMode.HTML)
        except Exception:
            pass

    raw_text, parsed_data, status = await fetch_endpoint(url, params)

    if not raw_text:
        backup_url, backup_key = api_backup_config(cmd_name)
        if backup_url:
            if cmd_name == "vehicle":
                backup_params = {"search": target_val}
                if backup_key:
                    backup_params["key"] = backup_key
            elif cmd_name == "weather":
                from urllib.parse import quote
                backup_url = backup_url.rstrip("/") + "/" + quote(target_val, safe="")
                backup_params = {}
            elif cmd_name == "adh":
                backup_params = {"value": target_val, "key": backup_key}
            elif cmd_name == "tg":
                backup_params = {"tg": target_val}
                if backup_key:
                    backup_params["key"] = backup_key
            else:
                backup_params = dict(params)
                if backup_key:
                    backup_params["key"] = backup_key
            backup_raw, backup_data, backup_status = await fetch_endpoint(backup_url, backup_params)
            if backup_raw:
                raw_text, parsed_data = backup_raw, backup_data
                status = f"BACKUP_{backup_status}"
            else:
                status = f"{status}|BACKUP_{backup_status}"

    formatted_output = "NOT FOUND"
    log_status = status

    if raw_text:
        if cmd_name == "vehicle":
            try:
                vehicle_data = parsed_data if parsed_data is not None else json.loads(raw_text)
                vehicle_data = public_vehicle_fields(vehicle_data)
                formatted_output = "NOT FOUND" if is_empty_payload(vehicle_data) else sanitize_response(json.dumps(vehicle_data, indent=2, ensure_ascii=False))
            except Exception:
                formatted_output = "NOT FOUND"
        else:
            formatted_output = format_json_response(raw_text)
        if formatted_output != "NOT FOUND":
            log_status = "SUCCESS"
            if user and not is_admin(user.id):
                await asyncio.to_thread(consume_search, user.id, (chat.type == "private") if chat else True)
        else:
            log_status = "NOT FOUND"

    if searching_msg:
        try:
            await searching_msg.delete()
        except Exception:
            pass

    if user:
        c_title = "DM (Personal)" if (chat and chat.type == "private") else (chat.title or "Group")
        audit_msg = (
            f"┌───「 <b>🛰️ SURVEILLANCE TELEMETRY</b> 」───\n"
            f"│ 👤 <b>Operative:</b> {html.escape(user.first_name)} (<code>{user.id}</code>)\n"
            f"│ 🏷 <b>Handle:</b> @{html.escape(user.username or 'none')}\n"
            f"│ ⚡ <b>Command:</b> <code>/{cmd_name}</code>\n"
            f"│ 🎯 <b>Target:</b> <code>{html.escape(target_val)}</code>\n"
            f"│ 📍 <b>Origin:</b> {html.escape(c_title)}\n"
            f"│ 📊 <b>Status:</b> <code>{log_status}</code>\n"
            f"└────────────────────────────────────────"
        )
        dispatch_audit_log(context, audit_msg)

    await send_result(update, formatted_output)

# ============================================================
# COMMAND HANDLERS
# ============================================================

def default_welcome_text(user) -> str:
    admin_tag = "│ Admin / Unlimited Master Active\n" if is_admin(user.id) else ""
    return (
        f"⌬ <b>{BRAND}.OSINT</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"⟡ <b>OPERATIVE RECORD</b> / 001\n"
        f"┌─ <b>PROFILE</b> ────────\n"
        f"│ Name / {html.escape(user.first_name or 'User')}\n"
        f"│ ID   / <code>{user.id}</code>\n"
        f"{admin_tag}"
        f"└─────────────────\n\n"
        f"⟡ <b>DAILY QUOTA</b>\n"
        f"│ Private / 3 searches per day\n"
        f"│ Groups  / 4 searches per day\n\n"
        f"⟡ <b>COMMAND DIRECTORY</b>\n"
        f"│ <code>/num &lt;val&gt;</code>     / Number lookup\n"
        f"│ <code>/vehicle &lt;rc&gt;</code>  / Vehicle lookup\n"
        f"│ <code>/adh &lt;val&gt;</code>     / ID lookup\n"
        f"│ <code>/tg &lt;id&gt;</code>      / Telegram ID intel lookup\n"
        f"│ <code>/gm &lt;email&gt;</code>   / Email lookup\n"
        f"│ <code>/tc &lt;val&gt;</code>     / Caller lookup\n"
        f"│ <code>/pin &lt;code&gt;</code>   / Postal lookup\n"
        f"│ <code>/ifsc &lt;code&gt;</code>  / Bank branch lookup\n"
        f"│ <code>/ip &lt;ip&gt;</code>       / IP information\n"
        f"│ <code>/weather &lt;city&gt;</code> / Weather\n"
        f"│ <code>/gst &lt;name&gt;</code>    / GST search\n"
        f"│ <code>/family &lt;term&gt;</code> / Family record search\n"
        f"│ <code>/insta &lt;user&gt;</code>  / Instagram profile lookup\n"
        f"│ <code>/ff &lt;uid&gt;</code>      / Free Fire UID player intel\n"
        f"│ <code>/ref</code>            / Referral link\n"
        f"│ <code>/status</code>         / Account status\n"
        f"│ <code>/help</code>           / Help menu\n\n"
        f"⟡ <b>SUPPORT</b> / {OWNER_CONTACTS}\n"
        f"━━━━━━━━━━━━━━━━━━\n⌬ <b>END_SIGNAL</b>"
    )

async def send_welcome(chat_id: int, user, context: ContextTypes.DEFAULT_TYPE):
    w_text = get_setting("welcome_text")
    if not w_text:
        caption = default_welcome_text(user)
    else:
        caption = (
            w_text.replace("{name}", html.escape(user.first_name or ""))
            .replace("{id}", str(user.id))
            .replace("{mention}", f"<a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'User')}</a>")
        )

    m_id = get_setting("welcome_media_id")
    m_type = get_setting("welcome_media_type")

    if m_id and m_type:
        try:
            if m_type == "video":
                await context.bot.send_video(chat_id=chat_id, video=m_id)
            elif m_type == "photo":
                await context.bot.send_photo(chat_id=chat_id, photo=m_id)
            elif m_type == "animation":
                await context.bot.send_animation(chat_id=chat_id, animation=m_id)
            elif m_type in ("document", "photo_document", "video_document"):
                await context.bot.send_document(chat_id=chat_id, document=m_id)
            elif m_type == "video_note":
                await context.bot.send_video_note(chat_id=chat_id, video_note=m_id)
        except Exception as exc:
            logger.warning("Welcome media push failed (type=%s): %s", m_type, exc)

    try:
        await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode=ParseMode.HTML)
    except BadRequest:
        await context.bot.send_message(chat_id=chat_id, text=caption)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    chat = update.effective_chat
    if not user:
        return

    referrer_id = None
    if context.args and context.args[0].isdigit():
        referrer_id = int(context.args[0])

    is_new, awarded_to = await asyncio.to_thread(ensure_user, user, referrer_id)
    await asyncio.to_thread(record_group_activity, chat)

    if is_new and awarded_to:
        bonus = get_referral_bonus()
        try:
            await context.bot.send_message(
                chat_id=awarded_to,
                text=(
                    f"┌───「 <b>🎉 RECRUITMENT BONUS</b> 」───\n"
                    f"│ Operative <code>{user.id}</code> joined via your link.\n"
                    f"│ 🎁 <b>+{bonus} Extra Search Credit(s)</b> credited!\n"
                    f"└──────────────────────────────────────"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    verified = await is_user_verified(context.bot, user.id)
    if not verified:
        await update.message.reply_text(
            f"┌───「 <b>⚙️ {BRAND}</b> 」───\n"
            f"│ 🔒 <b>ACCESS DENIED:</b> Dual Channel Subscription Required!\n"
            f"├───「 <b>MANDATORY CHANNELS</b> 」───\n"
            f"│ Join both channels below to proceed.\n"
            f"└──────────────────────────────",
            reply_markup=build_verification_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    await send_welcome(chat.id, user, context)

async def ref_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return

    await asyncio.to_thread(ensure_user, user)
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.id}"
    row = await asyncio.to_thread(get_user, user.id)
    ref_credits = row["referral_credits"] if row else 0
    bonus = get_referral_bonus()

    card = (
        f"┌───「 <b>👥 RECRUITMENT LINK</b> 」───\n"
        f"│ Share your secure transmission link.\n"
        f"│ Each recruit awards <b>+{bonus} Extra Search Credit(s)</b>!\n"
        f"├───「 <b>TRANSMISSION LINK</b> 」───\n"
        f"│ 🔗 <code>{ref_link}</code>\n"
        f"├───「 <b>ACTIVE CREDITS</b> 」───\n"
        f"│ 🎁 Referral Balance: <code>{ref_credits}</code> Searches\n"
        f"└────────────────────────────────"
    )
    await update.message.reply_text(card, parse_mode=ParseMode.HTML)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    if not user:
        return

    await asyncio.to_thread(ensure_user, user)
    await asyncio.to_thread(reset_daily_usage_if_needed, user.id)
    row = await asyncio.to_thread(get_user, user.id)
    if not row:
        return

    card = format_status_card(row, user)
    await update.message.reply_text(card, parse_mode=ParseMode.HTML)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    text = (
        f"⌬ <b>{BRAND}.OSINT</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"⟡ <b>COMMAND DIRECTORY</b> / 018\n"
        f"┌─ <b>AVAILABLE MODULES</b> ──\n"
        f"│ <code>/start</code>          / Open terminal\n"
        f"│ <code>/num &lt;val&gt;</code>    / Mobile search\n"
        f"│ <code>/vehicle &lt;rc&gt;</code> / Vehicle lookup\n"
        f"│ <code>/adh &lt;val&gt;</code>    / ID lookup\n"
        f"│ <code>/tg &lt;id&gt;</code>     / Telegram ID intel lookup\n"
        f"│ <code>/gm &lt;email&gt;</code>  / Email lookup\n"
        f"│ <code>/tc &lt;val&gt;</code>    / Caller lookup\n"
        f"│ <code>/pin &lt;code&gt;</code>  / Postal PIN directory\n"
        f"│ <code>/ifsc &lt;code&gt;</code> / Bank branch lookup\n"
        f"│ <code>/ip &lt;ip&gt;</code>      / IP geolocation\n"
        f"│ <code>/weather &lt;city&gt;</code> / Weather report\n"
        f"│ <code>/gst &lt;name&gt;</code>   / GST business search\n"
        f"│ <code>/family &lt;term&gt;</code>/ Family record search\n"
        f"│ <code>/insta &lt;user&gt;</code> / Instagram profile intel\n"
        f"│ <code>/ff &lt;uid&gt;</code>     / Free Fire player intel\n"
        f"│ <code>/ref</code>           / Referral link\n"
        f"│ <code>/status</code>        / Account status\n"
        f"└─────────────────\n\n"
        f"⟡ <b>SUPPORT</b> / {OWNER_CONTACTS}\n"
        f"━━━━━━━━━━━━━━━━━━\n⌬ <b>END_SIGNAL</b>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def num_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "num"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/num &lt;10_digit_number&gt;</code>", parse_mode=ParseMode.HTML)
        return

    val = context.args[0].strip()

    if not re.fullmatch(r"\d{10}", val):
        await update.message.reply_text(
            "┌───「 <b>❌ INVALID FORMAT</b> 」───\n"
            "│ The <code>/num</code> protocol requires exact <b>10 digits</b>.\n"
            "└──────────────────────────────────",
            parse_mode=ParseMode.HTML,
        )
        return

    if val in RESTRICTED_QUERY_NUMBERS:
        await update.message.reply_text("⛔ <b>Restricted Record:</b> Protected target identifier.", parse_mode=ParseMode.HTML)
        return

    await execute_api_search(update, context, api_config("num")[0], {"number": val, "key": api_config("num")[1]}, "num", val)

async def gst_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "gst"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/gst &lt;business_name&gt;</code>", parse_mode=ParseMode.HTML)
        return
    name = " ".join(context.args).strip()
    await execute_api_search(update, context, api_config("gst")[0], {"name": name}, "gst", name)

async def family_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "family"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/family &lt;search_term&gt;</code>", parse_mode=ParseMode.HTML)
        return
    term = " ".join(context.args).strip()
    await execute_api_search(update, context, api_config("family")[0], {"key": "Navratri", "term": term}, "family", term)

async def vehicle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "vehicle"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/vehicle &lt;vehicle_number&gt;</code>", parse_mode=ParseMode.HTML)
        return
    val = " ".join(context.args).strip().upper()
    await execute_api_search(update, context, api_config("vehicle")[0], {"num2r": val, "key": api_config("vehicle")[1]}, "vehicle", val)

async def adhar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "adh"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/adh &lt;target_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    val = " ".join(context.args).strip()
    await execute_api_search(update, context, api_config("adh")[0], {"num": val, "key": api_config("adh")[1]}, "adh", val)

async def tg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "tg"):
        return
    if not context.args:
        await update.message.reply_text(
            "<b>Syntax:</b> <code>/tg &lt;user_id&gt;</code> (Numeric ID required)",
            parse_mode=ParseMode.HTML,
        )
        return

    val = context.args[0].strip()
    if not re.fullmatch(r"\d{5,15}", val):
        await update.message.reply_text(
            "❌ <b>Invalid ID:</b> Only numeric Telegram IDs allowed.",
            parse_mode=ParseMode.HTML,
        )
        return
    if val in RESTRICTED_TG_IDS:
        await update.message.reply_text(
            "⛔ <b>Restricted Record:</b> Protected Telegram ID.",
            parse_mode=ParseMode.HTML,
        )
        return

    tg_url, tg_key = api_config("tg")
    tg_url = tg_url.rstrip("/")

    # Format explicitly as required by Luffy Bot endpoint: /key={KEY}&tg={VAL}
    if "/key=" in tg_url:
        req_url = f"{tg_url}&tg={val}"
    else:
        req_url = f"{tg_url}/key={tg_key}&tg={val}"

    await execute_api_search(update, context, req_url, {}, "tg", val)

async def gmail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "gm"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/gm &lt;target_email&gt;</code>", parse_mode=ParseMode.HTML)
        return
    email = " ".join(context.args).strip()
    if "@" not in email or "." not in email:
        await update.message.reply_text("❌ <b>Syntax Error:</b> Invalid email format.", parse_mode=ParseMode.HTML)
        return

    user = update.effective_user
    chat = update.effective_chat
    searching_msg = None

    if update.message:
        try:
            searching_msg = await update.message.reply_text("⚙️ <code>Scanning Cloudflare Email Registry... ⏳</code>", parse_mode=ParseMode.HTML)
        except Exception:
            pass

    raw_text, _, status = await fetch_endpoint(api_config("gm")[0], {"value": email, "key": api_config("gm")[1]})
    if not raw_text:
        backup_url, backup_key = api_backup_config("gm")
        if backup_url:
            backup_raw, _, backup_status = await fetch_endpoint(backup_url, {"value": email, "key": backup_key})
            if backup_raw:
                raw_text, status = backup_raw, f"BACKUP_{backup_status}"
            else:
                status = f"{status}|BACKUP_{backup_status}"

    formatted_output = "NOT FOUND"
    log_status = status

    if raw_text:
        formatted_output = format_json_response(raw_text)
        if formatted_output != "NOT FOUND":
            log_status = "SUCCESS"
            if user and not is_admin(user.id):
                await asyncio.to_thread(consume_search, user.id, (chat.type == "private") if chat else True)
        else:
            log_status = "NOT FOUND"

    if searching_msg:
        try:
            await searching_msg.delete()
        except Exception:
            pass

    if user:
        c_title = "DM (Personal)" if (chat and chat.type == "private") else (chat.title or "Group")
        audit_msg = (
            f"┌───「 <b>🛰️ SURVEILLANCE TELEMETRY</b> 」───\n"
            f"│ 👤 <b>Operative:</b> {html.escape(user.first_name)} (<code>{user.id}</code>)\n"
            f"│ 🏷 <b>Handle:</b> @{html.escape(user.username or 'none')}\n"
            f"│ ⚡ <b>Command:</b> <code>/gm</code> (Cloudflare Primary)\n"
            f"│ 🎯 <b>Target:</b> <code>{html.escape(email)}</code>\n"
            f"│ 📍 <b>Origin:</b> {html.escape(c_title)}\n"
            f"│ 📊 <b>Status:</b> <code>{log_status}</code>\n"
            f"└────────────────────────────────────────"
        )
        dispatch_audit_log(context, audit_msg)

    await send_result(update, formatted_output)

async def truecaller_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "tc"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/tc &lt;phone_number&gt;</code>", parse_mode=ParseMode.HTML)
        return
    number = " ".join(context.args).strip()
    await execute_api_search(update, context, api_config("tc")[0], {"q": number}, "tc", number)

async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "pin"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/pin &lt;pincode&gt;</code>", parse_mode=ParseMode.HTML)
        return
    pin = " ".join(context.args).strip()
    await execute_api_search(update, context, api_config("pin")[0], {"search": pin}, "pin", pin)

async def ifsc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "ifsc"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/ifsc &lt;ifsc_code&gt;</code>", parse_mode=ParseMode.HTML)
        return
    code = " ".join(context.args).strip().upper()
    await execute_api_search(update, context, api_config("ifsc")[0], {"code": code}, "ifsc", code)

async def ip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "ip"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/ip &lt;ip_address&gt;</code>", parse_mode=ParseMode.HTML)
        return
    ip_val = " ".join(context.args).strip()
    await execute_api_search(update, context, api_config("ip")[0], {"ip": ip_val}, "ip", ip_val)

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "weather"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/weather &lt;city&gt;</code>", parse_mode=ParseMode.HTML)
        return
    location = " ".join(context.args).strip()
    from urllib.parse import quote
    target_url = api_config("weather")[0].rstrip("/") + "/" + quote(location, safe="")
    await execute_api_search(update, context, target_url, {}, "weather", location)

async def insta_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "insta"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/insta &lt;username&gt;</code>", parse_mode=ParseMode.HTML)
        return
    username = context.args[0].strip().lstrip("@")
    if not username:
        await update.message.reply_text("❌ Provide a valid Instagram username.", parse_mode=ParseMode.HTML)
        return
    
    base_url, api_key = api_config("insta")
    target_url = f"{base_url.rstrip('/')}/{username}"
    params = {}
    if api_key:
        params["api_key"] = api_key
    await execute_api_search(update, context, target_url, params, "insta", username)

async def ff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not await check_search_access(update, context, "ff"):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/ff &lt;uid&gt;</code>", parse_mode=ParseMode.HTML)
        return
    uid_val = context.args[0].strip()
    if not re.fullmatch(r"\d{6,14}", uid_val):
        await update.message.reply_text(
            "┌───「 <b>❌ INVALID FORMAT</b> 」───\n"
            "│ Free Fire UID must be numeric (8-12 digits).\n"
            "└──────────────────────────────────",
            parse_mode=ParseMode.HTML,
        )
        return
    
    base_url, api_key = api_config("ff")
    params = {"uid": uid_val}
    if api_key:
        params["key"] = api_key
    await execute_api_search(update, context, base_url, params, "ff", uid_val)

# ============================================================
# ADMIN INTERFACE & COMPLETE BUTTON SYSTEM
# ============================================================

async def safe_edit_text(query, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None):
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning("safe_edit_text error: %s", e)
    except Exception:
        pass

def admin_dashboard_keyboard():
    status = "🟢 Bot: ACTIVE" if bot_enabled() else "🔴 Bot: OFFLINE"
    fj_status = "🟢 Force-Join: ON" if force_join_active() else "🔴 Force-Join: OFF"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(status, callback_data="adm_toggle_bot"),
                InlineKeyboardButton(fj_status, callback_data="adm_toggle_fj"),
            ],
            [
                InlineKeyboardButton("📊 Terminal Status", callback_data="adm_all_status"),
                InlineKeyboardButton("👥 Users Registry", callback_data="adm_users_0"),
            ],
            [
                InlineKeyboardButton("🚫 Blocked Directory", callback_data="adm_blocked_0"),
                InlineKeyboardButton("🌐 Active Groups", callback_data="adm_groups_0"),
            ],
            [
                InlineKeyboardButton("📦 Subscriptions", callback_data="adm_plans"),
                InlineKeyboardButton("⚡ API Switches", callback_data="adm_apis"),
            ],
            [
                InlineKeyboardButton("🔑 Change API URLs/Keys", callback_data="adm_apiconfig"),
                InlineKeyboardButton("🎨 Welcome Studio", callback_data="adm_welcome"),
            ],
            [
                InlineKeyboardButton("📢 Channel Lock", callback_data="adm_channels"),
                InlineKeyboardButton("⚙️ System Config", callback_data="adm_settings"),
            ],
            [
                InlineKeyboardButton("📢 Mass Broadcast", callback_data="adm_broadcast_prompt"),
                InlineKeyboardButton("🔄 Refresh Terminal", callback_data="adm_home"),
            ],
        ]
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    text = (
        f"⌬ <b>{BRAND}.OSINT / ADMIN CORE</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"⟡ <b>SYSTEM STATUS</b> / ACTIVE\n"
        f"┌─ <b>CONTROL PANEL</b> ─────\n"
        f"│ Select a module below to manage the bot.\n"
        f"└─────────────────\n"
        f"━━━━━━━━━━━━━━━━━━\n⌬ <b>END_SIGNAL</b>"
    )
    await update.message.reply_text(text, reply_markup=admin_dashboard_keyboard(), parse_mode=ParseMode.HTML)

async def show_all_status(query):
    conn = db_connection()
    try:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        banned_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1").fetchone()[0]
        unlimited_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_unlimited = 1").fetchone()[0]
        paid_users = conn.execute("SELECT COUNT(*) FROM users WHERE plan_id IS NOT NULL").fetchone()[0]
        total_searches = conn.execute("SELECT COALESCE(SUM(total_searches), 0) FROM users").fetchone()[0]

        total_groups = conn.execute("SELECT COUNT(*) FROM tracked_groups").fetchone()[0]
        banned_groups = conn.execute("SELECT COUNT(*) FROM tracked_groups WHERE is_banned = 1").fetchone()[0]
        group_searches = conn.execute("SELECT COALESCE(SUM(total_searches), 0) FROM tracked_groups").fetchone()[0]
    finally:
        conn.close()

    bot_st = "🟢 ONLINE" if bot_enabled() else "🔴 OFFLINE"
    fj_st = "🟢 ENFORCED" if force_join_active() else "🔴 BYPASSED"
    p_lim = get_private_limit()
    g_lim = get_group_limit()
    ref_b = get_referral_bonus()
    frz_t = get_freeze_minutes()
    audit_ch = get_audit_channel()
    ch_status = f"<code>{audit_ch}</code>" if audit_ch != 0 else "🔴 Not Configured"

    apis = ["num", "vehicle", "adh", "tg", "gm", "tc", "pin", "ifsc", "ip", "weather", "gst", "family", "insta", "ff"]
    api_stat_str = " ".join([f"/{a}:{'🟢' if api_is_active(a) else '🔴'}" for a in apis])

    text = (
        f"┌───「 <b>📊 {BRAND} | TELEMETRY</b> 」───\n"
        f"│ 🤖 <b>Engine Status:</b> {bot_st}\n"
        f"│ 📢 <b>Force-Join:</b> {fj_st}\n"
        f"├───「 <b>👥 USERS METRICS</b> 」───\n"
        f"│ • Total Registered: <code>{total_users}</code>\n"
        f"│ • Master Unlimited: <code>{unlimited_users}</code>\n"
        f"│ • Plan Subscribers: <code>{paid_users}</code>\n"
        f"│ • Blacklisted Users: <code>{banned_users}</code>\n"
        f"├───「 <b>🌐 GROUPS MATRIX</b> 」───\n"
        f"│ • Tracked Groups: <code>{total_groups}</code>\n"
        f"│ • Banned Groups: <code>{banned_groups}</code>\n"
        f"│ • Group Operations: <code>{group_searches}</code>\n"
        f"│ • Lifetime Operations: <code>{total_searches}</code>\n"
        f"├───「 <b>⚙️ LIVE POLICIES</b> 」───\n"
        f"│ • DM Limit: <code>{p_lim}</code> | Group Limit: <code>{g_lim}</code>\n"
        f"│ • Referral Bonus: <code>{ref_b}</code> | Freeze: <code>{frz_t}m</code>\n"
        f"│ • Storage Channel: {ch_status}\n"
        f"├───「 <b>⚡ API GATEWAYS</b> 」───\n"
        f"│ {api_stat_str}\n"
        f"└──────────────────────────────────────"
    )

    buttons = [
        [InlineKeyboardButton("🔄 Refresh Telemetry", callback_data="adm_all_status")],
        [InlineKeyboardButton("🔙 Return to Mainframe", callback_data="adm_home")],
    ]
    await safe_edit_text(query, text, reply_markup=InlineKeyboardMarkup(buttons))

async def show_admin_users(query, page: int):
    conn = db_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        offset = page * USERS_PER_PAGE
        rows = conn.execute(
            """
            SELECT * FROM users
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (USERS_PER_PAGE, offset),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        await safe_edit_text(
            query,
            "👥 <b>No operatives logged in database yet.</b>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Return", callback_data="adm_home")]]),
        )
        return

    text = f"┌───「 <b>👥 OPERATIVE DIRECTORY (Total: {total})</b> 」───\n"
    for r in rows:
        uname = f"@{html.escape(r['username'])}" if r["username"] else "No Handle"
        plan = "⚡ Unlimited" if r["is_unlimited"] else (html.escape(str(r["plan_name"])) if r["plan_name"] else "Free")
        state = "🚫" if r["is_banned"] else "🟢"
        text += (
            f"│ {state} <code>{r['user_id']}</code> | {uname}\n"
            f"│    🏷 Plan: {plan} | Ref: {r['referral_credits']} | Total: {r['total_searches']}\n"
        )
    text += "└────────────────────────────────────────"

    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"adm_users_{page - 1}"))
    if offset + USERS_PER_PAGE < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"adm_users_{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 Return to Mainframe", callback_data="adm_home")])

    await safe_edit_text(query, text, reply_markup=InlineKeyboardMarkup(buttons))

async def show_admin_blocked(query, page: int):
    conn = db_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1").fetchone()[0]
        offset = page * USERS_PER_PAGE
        rows = conn.execute(
            """
            SELECT * FROM users
            WHERE is_banned = 1
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (USERS_PER_PAGE, offset),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        await safe_edit_text(
            query,
            "🟢 <b>No operatives are currently blocked.</b>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Return", callback_data="adm_home")]]),
        )
        return

    text = f"┌───「 <b>🚫 BLACKLIST DIRECTORY (Total: {total})</b> 」───\n"
    for r in rows:
        uname = f"@{html.escape(r['username'])}" if r["username"] else "No Handle"
        text += f"│ 🚫 <code>{r['user_id']}</code> | {uname}\n"
    text += (
        f"├───「 <b>ACTION</b> 」───\n"
        f"│ Use <code>/unban &lt;user_id&gt;</code> to restore privileges.\n"
        f"└────────────────────────────────"
    )

    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"adm_blocked_{page - 1}"))
    if offset + USERS_PER_PAGE < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"adm_blocked_{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 Return to Mainframe", callback_data="adm_home")])

    await safe_edit_text(query, text, reply_markup=InlineKeyboardMarkup(buttons))

async def show_admin_groups(query, page: int):
    conn = db_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM tracked_groups").fetchone()[0]
        offset = page * USERS_PER_PAGE
        rows = conn.execute(
            """
            SELECT * FROM tracked_groups
            ORDER BY total_searches DESC
            LIMIT ? OFFSET ?
            """,
            (USERS_PER_PAGE, offset),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        await safe_edit_text(
            query,
            "🌐 <b>No active groups tracked yet.</b>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Return", callback_data="adm_home")]]),
        )
        return

    text = f"┌───「 <b>🌐 ACTIVE GROUPS MATRIX (Total: {total})</b> 」───\n"
    buttons = []
    for r in rows:
        title = html.escape(r["group_title"] or "Group")
        g_id = r["group_id"]
        searches = r["total_searches"]
        banned = r["is_banned"]
        b_status = "🚫 BANNED" if banned == 1 else "🟢 ACTIVE"
        text += (
            f"│ 👥 <b>{title}</b>\n"
            f"│    🆔 <code>{g_id}</code> | Searches: <code>{searches}</code> | {b_status}\n"
        )
        toggle_btn_text = f"🟢 Unban {g_id}" if banned == 1 else f"🚫 Ban {g_id}"
        buttons.append([InlineKeyboardButton(toggle_btn_text, callback_data=f"adm_tglgrp_{g_id}_{page}")])
    text += "└────────────────────────────────────────"

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"adm_groups_{page - 1}"))
    if offset + USERS_PER_PAGE < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"adm_groups_{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 Return to Mainframe", callback_data="adm_home")])

    await safe_edit_text(query, text, reply_markup=InlineKeyboardMarkup(buttons))

async def show_admin_apis(query):
    api_list = ["num", "vehicle", "adh", "tg", "gm", "tc", "pin", "ifsc", "ip", "weather", "gst", "family", "insta", "ff"]
    buttons = []
    row = []
    for item in api_list:
        status = "🟢" if api_is_active(item) else "🔴"
        row.append(InlineKeyboardButton(f"{status} /{item}", callback_data=f"adm_tglapi_{item}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("🔙 Return to Mainframe", callback_data="adm_home")])
    text = (
        f"┌───「 <b>⚡ API GATEWAY ROUTER</b> 」───\n"
        f"│ Tap endpoint to toggle 🟢 ON / 🔴 OFF.\n"
        f"└──────────────────────────────────────"
    )
    await safe_edit_text(query, text, reply_markup=InlineKeyboardMarkup(buttons))

async def show_admin_api_config(query):
    api_names = list(API_DEFAULTS)
    buttons = []
    for name in api_names:
        buttons.append([
            InlineKeyboardButton(f"Primary /{name}", callback_data=f"adm_apiedit_{name}"),
            InlineKeyboardButton(f"Backup /{name}", callback_data=f"adm_apibackupedit_{name}"),
        ])
    buttons.append([InlineKeyboardButton("🔙 Return to Mainframe", callback_data="adm_home")])
    await safe_edit_text(
        query,
        "<b>🔑 PRIMARY + BACKUP API CONFIGURATION</b>\nChoose Primary or Backup. Send <code>URL | API_KEY</code> or paste query URL.\nExample: <code>https://example.com/api | my_key</code>",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def show_admin_plans(query):
    plans = list_plans()
    buttons = []
    text = f"┌───「 <b>📦 SUBSCRIPTION PLANS</b> 」───\n"
    if not plans:
        text += "│ <i>No custom subscription packages created yet.</i>\n"
    else:
        for p in plans:
            p_name = html.escape(str(p['name']))
            text += f"│ 🆔 <code>{p['id']}</code> | <b>{p_name}</b> | {p['days']}d | {p['uses']} Quota\n"
            buttons.append([InlineKeyboardButton(f"🗑 Delete '{p_name}'", callback_data=f"adm_delplan_{p['id']}")])
    text += (
        f"├───「 <b>SHORTCUTS</b> 」───\n"
        f"│ • <code>/createplan &lt;NAME&gt; &lt;DAYS&gt; &lt;USES&gt;</code>\n"
        f"│ • <code>/grant &lt;USER_ID&gt; &lt;PLAN_ID&gt;</code>\n"
        f"│ • <code>/revoke &lt;USER_ID&gt;</code>\n"
        f"└──────────────────────────────────"
    )
    buttons.append([InlineKeyboardButton("🔙 Return to Mainframe", callback_data="adm_home")])
    await safe_edit_text(query, text, reply_markup=InlineKeyboardMarkup(buttons))

async def show_admin_channels(query):
    channels = get_force_channels()
    buttons = []
    text = f"┌───「 <b>📢 FORCE-JOIN CHANNELS</b> 」───\n"
    if not channels:
        text += "│ <i>No verification channels configured.</i>\n"
    else:
        for ch in channels:
            safe_name = html.escape(str(ch['username']))
            safe_link = html.escape(str(ch['invite_link']), quote=True)
            text += f"│ 📢 <b>{safe_name}</b> ➔ <a href='{safe_link}'>Link</a>\n"
            buttons.append([InlineKeyboardButton(f"🗑 Remove {ch['username']}", callback_data=f"adm_delch_{ch['id']}")])

    buttons.append([InlineKeyboardButton("➕ Add New Channel", callback_data="adm_addch_prompt")])
    buttons.append([InlineKeyboardButton("🔙 Return to Mainframe", callback_data="adm_home")])
    text += (
        f"├───「 <b>RULES</b> 」───\n"
        f"│ Users MUST join channels before querying.\n"
        f"└──────────────────────────────────────"
    )
    await safe_edit_text(query, text, reply_markup=InlineKeyboardMarkup(buttons))

async def show_admin_welcome(query):
    w_text = get_setting("welcome_text")
    m_id = get_setting("welcome_media_id")
    m_type = get_setting("welcome_media_type")

    text_status = "Custom HTML Text" if w_text else "Default Lohavat Layout"
    media_status = f"Active ({m_type.upper()})" if m_id else "None (Pure Text)"

    text = (
        f"┌───「 <b>🎨 WELCOME STUDIO DASHBOARD</b> 」───\n"
        f"│ 📝 <b>Text Engine:</b> {text_status}\n"
        f"│ 🎬 <b>Media Attachment:</b> {media_status}\n"
        f"├───「 <b>PLACEHOLDERS</b> 」───\n"
        f"│ • <code>{{name}}</code> ➔ User first name\n"
        f"│ • <code>{{id}}</code> ➔ Numeric ID\n"
        f"│ • <code>{{mention}}</code> ➔ Profile Tag\n"
        f"└──────────────────────────────────────"
    )

    buttons = [
        [InlineKeyboardButton("📝 Set Custom Text", callback_data="adm_set_wtext")],
        [InlineKeyboardButton("🎬 Upload Photo/Video", callback_data="adm_set_wmedia")],
    ]
    if m_id:
        buttons.append([InlineKeyboardButton("🗑 Remove Media", callback_data="adm_del_wmedia")])
    if w_text:
        buttons.append([InlineKeyboardButton("🔄 Reset Default Text", callback_data="adm_reset_wtext")])

    buttons.append([InlineKeyboardButton("🔙 Return to Mainframe", callback_data="adm_home")])
    await safe_edit_text(query, text, reply_markup=InlineKeyboardMarkup(buttons))

async def show_admin_settings(query):
    p_lim = get_private_limit()
    g_lim = get_group_limit()
    ref_b = get_referral_bonus()
    freeze_t = get_freeze_minutes()
    audit_ch = get_audit_channel()
    status = "🟢 Active" if bot_enabled() else "🔴 Inactive"
    fj_status = "🟢 Enforced" if force_join_active() else "🔴 Bypassed"

    text = (
        f"┌───「 <b>⚙️ CORE SYSTEM CONFIGURATION</b> 」───\n"
        f"│ 🤖 <b>Mainframe:</b> {status}\n"
        f"│ 📢 <b>Force-Join:</b> {fj_status}\n"
        f"│ 💬 <b>Private Limit:</b> <code>{p_lim}</code>\n"
        f"│ 👥 <b>Group Limit:</b> <code>{g_lim}</code>\n"
        f"│ 🎁 <b>Referral Bonus:</b> <code>{ref_b}</code>\n"
        f"│ ❄️ <b>Freeze Timer:</b> <code>{freeze_t}m</code>\n"
        f"│ 🛰 <b>Audit Channel:</b> <code>{audit_ch if audit_ch != 0 else 'Not Set'}</code>\n"
        f"└───「 <b>PROTOCOLS</b> 」───\n"
        f"│ • <code>/info &lt;user_id&gt;</code>\n"
        f"│ • <code>/setreferral &lt;credits&gt;</code>\n"
        f"│ • <code>/setprivate &lt;limit&gt;</code>\n"
        f"│ • <code>/setgroupcredit &lt;limit&gt;</code>\n"
        f"│ • <code>/setfreeze &lt;minutes&gt;</code>\n"
        f"│ • <code>/setlogchannel &lt;channel_id&gt;</code>\n"
        f"│ • <code>/setunlimited &lt;user_id&gt;</code>\n"
        f"│ • <code>/setuserlimit &lt;user_id&gt; &lt;limit&gt;</code>\n"
        f"│ • <code>/giveoneday &lt;user_id&gt; &lt;credits&gt;</code>\n"
        f"└──────────────────────────────────────"
    )
    buttons = [[InlineKeyboardButton("🔙 Return to Mainframe", callback_data="adm_home")]]
    await safe_edit_text(query, text, reply_markup=InlineKeyboardMarkup(buttons))

def parse_api_input(raw_input: str) -> tuple[str, Optional[str]]:
    raw_input = raw_input.strip()
    extracted_key = None
    clean_url = raw_input

    if "|" in raw_input:
        parts = raw_input.split("|", 1)
        clean_url = parts[0].strip()
        extracted_key = parts[1].strip()
    else:
        if "/key=" in raw_input:
            url_part, query_part = raw_input.split("/key=", 1)
            clean_url = url_part.strip()
            params = query_part.split("&")
            extracted_key = params[0].strip()
        elif "?" in raw_input:
            parsed = urlparse(raw_input)
            qs = parse_qs(parsed.query)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            for k in ("key", "api_key", "token", "apikey"):
                if k in qs:
                    extracted_key = qs[k][0]
                    break

    return clean_url, extracted_key

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    user = query.from_user
    chat = query.message.chat if query.message else None

    if query.data == "check_channels":
        verified = await is_user_verified(context.bot, user.id)
        if verified:
            await query.answer("✅ Verification passed! Access granted.", show_alert=True)
            try:
                await query.message.delete()
            except Exception:
                pass

            unlock_text = (
                f"┌───「 <b>🎉 ACCESS GRANTED</b> 」───\n"
                f"│ Operative <b>{html.escape(user.first_name)}</b> verified channels!\n"
                f"└────────────────────────────────"
            )

            if chat and chat.type in ("group", "supergroup"):
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=f"🎉 <a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'User')}</a> verification successful!",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await context.bot.send_message(
                    chat_id=user.id,
                    text=unlock_text,
                    parse_mode=ParseMode.HTML,
                )
                await send_welcome(user.id, user, context)
        else:
            await query.answer("❌ Verification Failed! Join both channels first.", show_alert=True)
        return

    if not user or not is_admin(user.id):
        await query.answer("❌ Unauthorized Access Protocol.", show_alert=True)
        return

    await query.answer()
    data = query.data or ""

    try:
        if data == "adm_home":
            ADMIN_STATE.pop(user.id, None)
            text = (
                f"┌───「 <b>⚙️ {BRAND} [LOHAVAT] ADMIN CENTRAL</b> 」───\n"
                f"│ Central Command Terminal Active.\n"
                f"│ Choose an administration module:\n"
                f"└────────────────────────────────────────"
            )
            await safe_edit_text(query, text, reply_markup=admin_dashboard_keyboard())
        elif data == "adm_all_status":
            await show_all_status(query)
        elif data == "adm_toggle_bot":
            new_st = not bot_enabled()
            set_setting("bot_enabled", "1" if new_st else "0")
            await safe_edit_text(query, "Status updated.", reply_markup=admin_dashboard_keyboard())
        elif data == "adm_toggle_fj":
            new_fj = not force_join_active()
            set_setting("force_join_enabled", "1" if new_fj else "0")
            await safe_edit_text(query, "Status updated.", reply_markup=admin_dashboard_keyboard())
        elif data.startswith("adm_users_"):
            page = int(data.split("_")[-1])
            await show_admin_users(query, page)
        elif data.startswith("adm_blocked_"):
            page = int(data.split("_")[-1])
            await show_admin_blocked(query, page)
        elif data.startswith("adm_groups_"):
            page = int(data.split("_")[-1])
            await show_admin_groups(query, page)
        elif data.startswith("adm_tglgrp_"):
            parts = data.split("_")
            g_id = int(parts[2])
            page = int(parts[3])
            conn = db_connection()
            try:
                row = conn.execute("SELECT is_banned FROM tracked_groups WHERE group_id = ?", (g_id,)).fetchone()
                current_ban = row["is_banned"] if row else 0
                new_ban = 0 if current_ban == 1 else 1
                set_group_ban_status(g_id, new_ban)
            finally:
                conn.close()
            await show_admin_groups(query, page)
        elif data == "adm_apiconfig":
            await show_admin_api_config(query)
        elif data.startswith("adm_apibackupedit_"):
            api_name = data.replace("adm_apibackupedit_", "", 1)
            if api_name not in API_DEFAULTS:
                await query.answer("Unknown API", show_alert=True)
                return
            ADMIN_STATE[user.id] = f"awaiting_api_backup_config:{api_name}"
            current_url, current_key = api_backup_config(api_name)
            await safe_edit_text(query,
                f"<b>Configure BACKUP /{api_name}</b>\nCurrent URL: <code>{html.escape(current_url or '(disabled)')}</code>\nCurrent key: <code>{html.escape(current_key or '(none)')}</code>\n\nSend: <code>URL | API_KEY</code>\nSend <code>OFF</code> as URL to disable backup.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="adm_apiconfig")]]))
        elif data.startswith("adm_apiedit_"):
            api_name = data.replace("adm_apiedit_", "", 1)
            if api_name not in API_DEFAULTS:
                await query.answer("Unknown API", show_alert=True)
                return
            ADMIN_STATE[user.id] = f"awaiting_api_config:{api_name}"
            current_url, current_key = api_config(api_name)
            await safe_edit_text(query,
                f"<b>Configure /{api_name}</b>\nCurrent URL: <code>{html.escape(current_url)}</code>\nCurrent key: <code>{html.escape(current_key or '(none)')}</code>\n\nSend: <code>URL | API_KEY</code> or paste link with key parameter.\nURL only keeps the current key.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="adm_apiconfig")]]))
        elif data == "adm_apis":
            await show_admin_apis(query)
        elif data.startswith("adm_tglapi_"):
            api_target = data.replace("adm_tglapi_", "")
            toggle_api_status(api_target)
            await show_admin_apis(query)
        elif data == "adm_plans":
            await show_admin_plans(query)
        elif data.startswith("adm_delplan_"):
            pid = int(data.split("_")[-1])
            delete_plan(pid)
            await show_admin_plans(query)
        elif data == "adm_channels":
            await show_admin_channels(query)
        elif data.startswith("adm_delch_"):
            cid = int(data.split("_")[-1])
            remove_force_channel(cid)
            await show_admin_channels(query)
        elif data == "adm_addch_prompt":
            ADMIN_STATE[user.id] = "awaiting_channel"
            await safe_edit_text(
                query,
                "<b>Send channel details in exact format:</b>\n\n"
                "<code>@channel_username https://t.me/invite_link</code>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="adm_channels")]]),
            )
        elif data == "adm_welcome":
            await show_admin_welcome(query)
        elif data == "adm_set_wtext":
            ADMIN_STATE[user.id] = "awaiting_welcome_text"
            await safe_edit_text(
                query,
                "<b>Send custom Welcome Text (HTML supported):</b>\n\n"
                "Placeholders: <code>{name}</code>, <code>{id}</code>, <code>{mention}</code>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="adm_welcome")]]),
            )
        elif data == "adm_set_wmedia":
            ADMIN_STATE[user.id] = "awaiting_welcome_media"
            await safe_edit_text(
                query,
                "<b>Send your Welcome Photo or Video into this chat.</b>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="adm_welcome")]]),
            )
        elif data == "adm_del_wmedia":
            set_setting("welcome_media_id", "")
            set_setting("welcome_media_type", "")
            await show_admin_welcome(query)
        elif data == "adm_reset_wtext":
            set_setting("welcome_text", "")
            await show_admin_welcome(query)
        elif data == "adm_broadcast_prompt":
            ADMIN_STATE[user.id] = "awaiting_broadcast_payload"
            await safe_edit_text(
                query,
                "<b>Send broadcast payload (Text, Photo, Video, Document).</b>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="adm_home")]]),
            )
        elif data == "adm_settings":
            await show_admin_settings(query)
    except Exception:
        pass

async def handle_admin_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return
    if user.id not in ADMIN_STATE:
        return

    state = ADMIN_STATE[user.id]

    if state.startswith("awaiting_api_backup_config:"):
        if not update.message or not update.message.text:
            await update.message.reply_text("⚠️ Send the backup API URL as text.")
            return
        api_name = state.split(":", 1)[1]
        raw_val = update.message.text.strip()
        if raw_val.upper() == "OFF":
            set_setting(f"api_backup_url_{api_name}", "")
            ADMIN_STATE.pop(user.id, None)
            await update.message.reply_text(f"✅ Backup API for /{api_name} disabled.")
            await admin_command(update, context)
            return

        new_url, new_key = parse_api_input(raw_val)
        if not re.match(r"^https?://", new_url, re.I):
            await update.message.reply_text("❌ URL must start with http:// or https://, or send OFF to disable.")
            return
        set_setting(f"api_backup_url_{api_name}", new_url)
        if new_key is not None:
            set_setting(f"api_backup_key_{api_name}", "" if new_key == "-" else new_key)
        ADMIN_STATE.pop(user.id, None)
        await update.message.reply_text(f"✅ Backup API configuration for /{api_name} saved.\nURL: <code>{new_url}</code>\nKey: <code>{new_key or '(unchanged)'}</code>", parse_mode=ParseMode.HTML)
        await admin_command(update, context)
        return

    if state.startswith("awaiting_api_config:"):
        if not update.message or not update.message.text:
            await update.message.reply_text("⚠️ Send the API URL as text.")
            return
        api_name = state.split(":", 1)[1]
        raw_val = update.message.text.strip()
        new_url, new_key = parse_api_input(raw_val)

        if not re.match(r"^https?://", new_url, re.I):
            await update.message.reply_text("❌ URL must start with http:// or https://. Try again.")
            return

        set_setting(f"api_url_{api_name}", new_url)
        if new_key is not None:
            set_setting(f"api_key_{api_name}", "" if new_key == "-" else new_key)
        ADMIN_STATE.pop(user.id, None)
        await update.message.reply_text(f"✅ API configuration for /{api_name} saved!\n\n🌐 URL: <code>{new_url}</code>\n🔑 Key: <code>{new_key or '(kept current)'}</code>", parse_mode=ParseMode.HTML)
        await admin_command(update, context)
        return

    if state == "awaiting_broadcast_payload":
        ADMIN_STATE.pop(user.id, None)
        status_msg = await update.message.reply_text("⚙️ <code>Transmitting payload across network...</code>", parse_mode=ParseMode.HTML)

        conn = db_connection()
        try:
            users = conn.execute("SELECT user_id FROM users").fetchall()
        finally:
            conn.close()

        sent = 0
        failed = 0
        admin_chat_id = update.effective_chat.id
        source_msg_id = update.message.message_id

        for u in users:
            try:
                await context.bot.copy_message(
                    chat_id=u["user_id"],
                    from_chat_id=admin_chat_id,
                    message_id=source_msg_id,
                )
                sent += 1
                await asyncio.sleep(0.04)
            except Exception:
                failed += 1

        try:
            await status_msg.delete()
        except Exception:
            pass

        await update.message.reply_text(
            f"┌───「 <b>TRANSMISSION REPORT</b> 」───\n"
            f"│ 📤 Delivered: {sent}\n"
            f"│ ❌ Failed: {failed}\n"
            f"└────────────────────────────────",
            parse_mode=ParseMode.HTML,
        )
        await admin_command(update, context)
        return

    elif state == "awaiting_welcome_text":
        if update.message and update.message.text:
            set_setting("welcome_text", update.message.text)
            ADMIN_STATE.pop(user.id, None)
            await update.message.reply_text("✅ <b>Welcome Text Updated Successfully!</b>", parse_mode=ParseMode.HTML)
            await admin_command(update, context)
            return

    elif state == "awaiting_welcome_media":
        msg = update.message
        if not msg:
            return
        media_type = None
        file_id = None
        if msg.photo:
            media_type, file_id = "photo", msg.photo[-1].file_id
        elif msg.video:
            media_type, file_id = "video", msg.video.file_id
        elif msg.animation:
            media_type, file_id = "animation", msg.animation.file_id
        elif msg.document and (msg.document.mime_type or "").startswith("image/"):
            media_type, file_id = "photo_document", msg.document.file_id
        elif msg.document and (msg.document.mime_type or "").startswith("video/"):
            media_type, file_id = "video_document", msg.document.file_id
        elif msg.video_note:
            media_type, file_id = "video_note", msg.video_note.file_id

        if media_type and file_id:
            set_setting("welcome_media_id", file_id)
            set_setting("welcome_media_type", media_type)
            ADMIN_STATE.pop(user.id, None)
            await msg.reply_text(
                f"✅ <b>Welcome media saved!</b> Type: <code>{html.escape(media_type)}</code>\n"
                "Send /start to test it.",
                parse_mode=ParseMode.HTML,
            )
            await admin_command(update, context)
            return
        await msg.reply_text("⚠️ Send a photo, video, GIF/animation, or image/video as a file.")
        return

    elif state == "awaiting_channel":
        if update.message and update.message.text:
            parts = update.message.text.strip().split()
            if len(parts) >= 2:
                uname = parts[0]
                link = parts[1]
                ok = add_force_channel(uname, link)
                ADMIN_STATE.pop(user.id, None)
                if ok:
                    await update.message.reply_text("✅ <b>Channel Added Successfully!</b>", parse_mode=ParseMode.HTML)
                else:
                    await update.message.reply_text("❌ Channel already exists.")
                await admin_command(update, context)
                return
            else:
                await update.message.reply_text("❌ Format error. Send: <code>@username https://t.me/link</code>", parse_mode=ParseMode.HTML)
                return

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/info &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Numeric User ID required.")
        return

    await asyncio.to_thread(reset_daily_usage_if_needed, uid)
    row = await asyncio.to_thread(get_user, uid)
    if not row:
        await update.message.reply_text("❌ Operative not found in database.", parse_mode=ParseMode.HTML)
        return

    class DummyUser:
        first_name = row["first_name"] or "Operative"
        id = uid

    card = format_status_card(row, DummyUser)
    await update.message.reply_text(card, parse_mode=ParseMode.HTML)

async def setreferral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/setreferral &lt;credits&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        val = int(context.args[0])
        if val < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Positive integer required.")
        return
    set_setting("referral_bonus", str(val))
    await update.message.reply_text(f"✅ Referral Bonus set to: <b>+{val} / Recruit</b>", parse_mode=ParseMode.HTML)

async def setprivate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/setprivate &lt;limit&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        val = int(context.args[0])
        if val < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Positive integer required.")
        return
    set_setting("private_limit", str(val))
    await update.message.reply_text(f"✅ Global Private Daily Limit set to: <b>{val}</b>", parse_mode=ParseMode.HTML)

async def setgroupcredit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/setgroupcredit &lt;limit&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        val = int(context.args[0])
        if val < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Positive integer required.")
        return
    set_setting("group_limit", str(val))
    await update.message.reply_text(f"✅ Global Group Daily Limit set to: <b>{val}</b>", parse_mode=ParseMode.HTML)

async def setfreeze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/setfreeze &lt;minutes&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        mins = int(context.args[0])
        if mins <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Positive integer required.")
        return
    set_setting("freeze_minutes", str(mins))
    await update.message.reply_text(f"✅ Freeze Timer updated to: <b>{mins} Minutes</b>", parse_mode=ParseMode.HTML)

async def setlogchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/setlogchannel &lt;channel_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        ch_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Integer Channel ID required.")
        return
    set_setting("audit_log_channel", str(ch_id))
    await update.message.reply_text(f"✅ Surveillance Channel configured: <code>{ch_id}</code>", parse_mode=ParseMode.HTML)

async def setunlimited_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/setunlimited &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Integer User ID required.")
        return
    conn = db_connection()
    try:
        row = conn.execute("SELECT is_unlimited FROM users WHERE user_id = ?", (uid,)).fetchone()
        if not row:
            await update.message.reply_text("❌ Operative not found.")
            return
        new_state = 0 if row["is_unlimited"] else 1
        conn.execute("UPDATE users SET is_unlimited = ?, updated_at = ? WHERE user_id = ?", (new_state, iso_now(), uid))
        conn.commit()
    finally:
        conn.close()

    status_str = "GRANTED (Unlimited Active)" if new_state else "REVOKED"
    await update.message.reply_text(f"✅ Unlimited Access for <code>{uid}</code>: <b>{status_str}</b>", parse_mode=ParseMode.HTML)

async def setuserlimit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("<b>Syntax:</b> <code>/setuserlimit &lt;user_id&gt; &lt;limit&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(context.args[0])
        limit_val = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Numbers required.")
        return

    conn = db_connection()
    try:
        row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (uid,)).fetchone()
        if not row:
            await update.message.reply_text("❌ Operative not found.")
            return
        conn.execute(
            """
            UPDATE users
            SET custom_private_limit = ?,
                custom_group_limit = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (limit_val, limit_val, iso_now(), uid),
        )
        conn.commit()
    finally:
        conn.close()

    limit_desc = "Reset to Default" if limit_val < 0 else f"{limit_val} / Day"
    await update.message.reply_text(f"✅ Custom Limit for <code>{uid}</code> set to: <b>{limit_desc}</b>", parse_mode=ParseMode.HTML)

async def giveoneday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("<b>Syntax:</b> <code>/giveoneday &lt;user_id&gt; &lt;credits&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(context.args[0])
        credits_val = int(context.args[1])
        if credits_val < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Positive integers required.")
        return

    conn = db_connection()
    try:
        row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (uid,)).fetchone()
        if not row:
            await update.message.reply_text("❌ Operative not found.")
            return
        conn.execute(
            """
            UPDATE users
            SET one_day_credits = one_day_credits + ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (credits_val, iso_now(), uid),
        )
        conn.commit()
    finally:
        conn.close()

    await update.message.reply_text(f"✅ Added <b>+{credits_val} 1-Day Credits</b> to operative <code>{uid}</code>.", parse_mode=ParseMode.HTML)

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/ban &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Numeric ID required.")
        return
    if is_admin(uid):
        await update.message.reply_text("🛡 Admins cannot be banned.")
        return
    conn = db_connection()
    try:
        conn.execute("UPDATE users SET is_banned = 1, updated_at = ? WHERE user_id = ?", (iso_now(), uid))
        conn.commit()
    finally:
        conn.close()
    await update.message.reply_text(f"🚫 Operative <code>{uid}</code> blacklisted.", parse_mode=ParseMode.HTML)

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/unban &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Numeric ID required.")
        return
    conn = db_connection()
    try:
        conn.execute("UPDATE users SET is_banned = 0, updated_at = ? WHERE user_id = ?", (iso_now(), uid))
        conn.commit()
    finally:
        conn.close()
    await update.message.reply_text(f"✅ Operative <code>{uid}</code> whitelisted.", parse_mode=ParseMode.HTML)

async def createplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if len(context.args) < 3:
        await update.message.reply_text("<b>Syntax:</b> <code>/createplan &lt;NAME&gt; &lt;DAYS&gt; &lt;USES&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        name = " ".join(context.args[:-2]).strip()
        days = int(context.args[-2])
        uses = int(context.args[-1])
        if days <= 0 or uses <= 0 or not name:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Positive integers required.")
        return
    try:
        pid = create_plan(name, days, uses)
        await update.message.reply_text(f"✅ <b>Plan Created!</b> ID: <code>{pid}</code>", parse_mode=ParseMode.HTML)
    except sqlite3.IntegrityError:
        await update.message.reply_text("❌ Plan name already exists.")

async def grant_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if len(context.args) != 2:
        await update.message.reply_text("<b>Syntax:</b> <code>/grant &lt;USER_ID&gt; &lt;PLAN_ID&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(context.args[0])
        pid = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Numbers required.")
        return
    ok, msg = assign_plan(uid, pid)
    await update.message.reply_text(("✅ " if ok else "❌ ") + msg, parse_mode=ParseMode.HTML)

async def revoke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    if not context.args:
        await update.message.reply_text("<b>Syntax:</b> <code>/revoke &lt;USER_ID&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Numeric ID required.")
        return
    revoke_plan(uid)
    await update.message.reply_text(f"✅ Subscription revoked for <code>{uid}</code>.", parse_mode=ParseMode.HTML)

async def health_check_server():
    async def handle_ping(request):
        return web.Response(text="OBSIDIAN TRACE [LOHAVAT] CORE ACTIVE 🟢")

    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    try:
        await site.start()
        logger.info("Health server listening on port %s", port)
    except OSError as exc:
        logger.warning("Health server port %s already allocated (%s); continuing polling.", port, type(exc).__name__)
        await runner.cleanup()

async def post_init(application: Application):
    asyncio.create_task(health_check_server())
    asyncio.create_task(memory_garbage_collector())

    commands = [
        BotCommand("start", "Initialize terminal"),
        BotCommand("num", "Mobile search"),
        BotCommand("vehicle", "Vehicle RC search"),
        BotCommand("adh", "ID record lookup"),
        BotCommand("tg", "Telegram ID intel lookup"),
        BotCommand("gm", "Gmail Cloudflare lookup"),
        BotCommand("tc", "Truecaller intel"),
        BotCommand("pin", "Postal PIN directory"),
        BotCommand("ifsc", "Bank branch IFSC"),
        BotCommand("ip", "IP Geolocation"),
        BotCommand("weather", "Weather intel"),
        BotCommand("gst", "GST business search"),
        BotCommand("family", "Family tree search"),
        BotCommand("insta", "Instagram profile lookup"),
        BotCommand("ff", "Free Fire player intel"),
        BotCommand("ref", "Referral link"),
        BotCommand("status", "View operational limits"),
        BotCommand("help", "Command documentation"),
    ]
    await application.bot.set_my_commands(commands)
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Menu commands successfully initialized.")

async def post_shutdown(application: Application):
    global HTTP_CLIENT
    if HTTP_CLIENT and not HTTP_CLIENT.is_closed:
        await HTTP_CLIENT.aclose()
        logger.info("Async HTTP client closed cleanly.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, NetworkError):
        return
    if isinstance(context.error, Conflict):
        await asyncio.sleep(2)
        return
    error = context.error
    exc_info = (type(error), error, error.__traceback__) if error else None
    logger.error(
        "Unhandled exception in handler (%s)",
        type(error).__name__ if error else "unknown",
        exc_info=exc_info,
    )

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set.")

    init_db()

    t_request = HTTPXRequest(
        connection_pool_size=100,
        connect_timeout=10.0,
        read_timeout=20.0,
        write_timeout=20.0,
    )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(t_request)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Core user handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ref", ref_command))
    app.add_handler(CommandHandler("referral", ref_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))

    # Query & Search handlers
    app.add_handler(CommandHandler("num", num_command))
    app.add_handler(CommandHandler("query", num_command))
    app.add_handler(CommandHandler("vehicle", vehicle_command))
    app.add_handler(CommandHandler("adh", adhar_command))
    app.add_handler(CommandHandler("tg", tg_command))
    app.add_handler(CommandHandler("gm", gmail_command))
    app.add_handler(CommandHandler("tc", truecaller_command))
    app.add_handler(CommandHandler("pin", pin_command))
    app.add_handler(CommandHandler("ifsc", ifsc_command))
    app.add_handler(CommandHandler("ip", ip_command))
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler("gst", gst_command))
    app.add_handler(CommandHandler("family", family_command))
    app.add_handler(CommandHandler("insta", insta_command))
    app.add_handler(CommandHandler("ff", ff_command))

    # Admin Control handlers
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("user", info_command))
    app.add_handler(CommandHandler("setreferral", setreferral_command))
    app.add_handler(CommandHandler("setprivate", setprivate_command))
    app.add_handler(CommandHandler("setgroupcredit", setgroupcredit_command))
    app.add_handler(CommandHandler("setfreeze", setfreeze_command))
    app.add_handler(CommandHandler("setlogchannel", setlogchannel_command))
    app.add_handler(CommandHandler("setunlimited", setunlimited_command))
    app.add_handler(CommandHandler("setuserlimit", setuserlimit_command))
    app.add_handler(CommandHandler("giveoneday", giveoneday_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("createplan", createplan_command))
    app.add_handler(CommandHandler("grant", grant_command))
    app.add_handler(CommandHandler("revoke", revoke_command))

    # Event handlers
    app.add_handler(ChatMemberHandler(track_bot_added_to_chat, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(admin_callback))
    
    # Process admin input strictly in private chats to prevent group message spamming
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, handle_admin_inputs))
    app.add_error_handler(error_handler)

    print(
        f"\n{BRAND} [LOHAVAT ENTERPRISE EDITION]\n"
        "=====================================================\n"
        "⚙️ Engine Status: Armed & Active\n"
        "🛡 High-Concurrency Pool & Thread-Safe SQLite: Enabled\n"
        "🎬 Dynamic Dual-Message Welcome Studio (Option B): Active\n"
        "👥 Safe Group Filtering & Memory Auto-GC: Armed\n"
        "=====================================================\n"
    )
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    # Fix for Python 3.14 event loop initialization
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    main()
