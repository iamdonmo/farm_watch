"""
Farm Watch Enterprise Node
--------------------------
Community farm security platform with real-time alerts, peer verification,
direct messaging, and administrative oversight.

Admin access (not linked publicly):
  URL:      /dashboard
  Username: value of ADMIN_USERNAME env (default: chief)
  Password: value of ADMIN_PASSWORD env (default: securepassword123)
  Auth:     HTTP Basic Authentication
"""

import os
import hmac
import hashlib
import secrets
import time
import html
import json
import httpx
import asyncio
import aiosqlite
import shutil
import io
import qrcode
from urllib.parse import quote
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, Dict, List
from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, Form, Response, Depends, HTTPException, status, Cookie, File, UploadFile, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# SECURITY: All secrets MUST come from environment variables in production.
# Never commit real credentials. Rotate any keys that were previously hardcoded.
# ---------------------------------------------------------------------------
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@iamdonmo")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    print("WARNING: ADMIN_PASSWORD is not configured. Admin login is disabled.")

ADMIN_SECRET_HASH = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest() if ADMIN_PASSWORD else None
COOKIE_SIGNING_KEY = os.getenv("COOKIE_SECRET_KEY", "").encode() or secrets.token_bytes(32)
ADMIN_SESSION_TTL_SECONDS = 15 * 60

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "whatsapp:+14155238886")
SITE_URL = os.getenv("SITE_URL", "https://olode.com.ng")
ENABLE_DEMO_DATA = os.getenv("ENABLE_DEMO_DATA", "").strip().lower() in {"1", "true", "yes"}

if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
    print("WARNING: Twilio credentials not set. WhatsApp alerts will fail.")

DEFAULT_DB_FILE = "farm_watch.db"
DB_FILE = os.getenv("DB_FILE", DEFAULT_DB_FILE)
DEFAULT_MEDIA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_media")
MEDIA_DIR = os.path.abspath(os.getenv("MEDIA_DIR", DEFAULT_MEDIA_DIR))

os.makedirs(os.path.dirname(os.path.abspath(DB_FILE)), exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)
legacy_media_dir = os.path.abspath(DEFAULT_MEDIA_DIR)
if MEDIA_DIR != legacy_media_dir and os.path.isdir(legacy_media_dir):
    for media_filename in os.listdir(legacy_media_dir):
        source_path = os.path.join(legacy_media_dir, media_filename)
        destination_path = os.path.join(MEDIA_DIR, media_filename)
        if os.path.isfile(source_path) and not os.path.exists(destination_path):
            shutil.copy2(source_path, destination_path)

# Limit concurrent Twilio dispatches
DISPATCH_SEMAPHORE = asyncio.Semaphore(10)

CITY_AUTOFILL_MAP = {
    "osogbo": {"country": "Nigeria", "state": "Osun", "lga": "Osogbo", "area": "Ataoja Sector"},
    "ile-ife": {"country": "Nigeria", "state": "Osun", "lga": "Ile-Ife", "area": "Ife Central Town"},
    "ibadan": {"country": "Nigeria", "state": "Oyo", "lga": "Ibadan", "area": "Ido Farming Grid"},
    "ogbomoso": {"country": "Nigeria", "state": "Oyo", "lga": "Ogbomoso", "area": "Ogbomoso South Central"}
}

# Node status constants
STATUS_PENDING = "Pending"
STATUS_APPROVED = "Approved"
STATUS_REPORTED = "Reported"
RESTRICTED_STATUSES = {STATUS_PENDING, STATUS_REPORTED}

# Messaging safety limits
MAX_MESSAGE_LENGTH = 350
MAX_UPLOAD_SIZE = 15 * 1024 * 1024  # 15 MB
MAX_SOCIAL_IMAGE_UPLOAD_SIZE = 8 * 1024 * 1024
MAX_SOCIAL_IMAGE_PIXELS = 25_000_000
MAX_SOCIAL_IMAGE_STORAGE_SIZE = 650 * 1024
MAX_MESSAGES_PER_HOUR_TO_PEER = 8
MAX_MESSAGES_PER_DAY = 25
REPORTS_TO_AUTO_FLAG = 2

# Engagement / games
CHECKIN_XP = 5
AUTO_XP_PER_TICK = 1  # XP awarded every 20 seconds while on the page
SHOUTOUT_XP = 3
DART_WIN_XP = 15
HUNT_WIN_XP = 10
PRODUCT_POST_XP = 8
MAX_SHOUTOUT_LEN = 120
SHOUTOUT_CATEGORIES = ("Birthday", "Naming", "Wedding", "Harvest", "Thank You", "Other")
_SHOUTOUT_TEMPLATE_FAMILIES = (
    ("sunrise", "🌅", 30),
    ("garden", "🌺", 145),
    ("celebration", "🎉", 320),
    ("royal", "👑", 260),
    ("harvest", "🌾", 45),
    ("ocean", "💙", 190),
    ("love", "💐", 345),
    ("simple", "✨", 215),
)
SHOUTOUT_TEMPLATES = {
    f"{family}-{variant:02d}": (
        emoji,
        f"linear-gradient(135deg, hsl({(hue + (variant - 1) * 7) % 360} 72% 22%), "
        f"hsl({(hue + (variant - 1) * 7) % 360} 78% 48%), "
        f"hsl({(hue + (variant - 1) * 7) % 360} 90% 82%))",
    )
    for family, emoji, hue in _SHOUTOUT_TEMPLATE_FAMILIES
    for variant in range(1, 26)
}
MAX_PRODUCT_TITLE = 80
MAX_PRODUCT_DESC = 300
PRODUCT_CATEGORIES = ("Crops", "Livestock", "Tools", "Seeds", "Produce", "Other")
FAITH_PREFERENCES = (
    "Christian", "Muslim", "Traditionalist", "Atheist", "Spiritualist", "Private"
)
LIVESTOCK_TYPES = ("Dog", "Birds", "Cow", "Goats", "Chicken", "Exotic Pets")
DOG_SEX = ("Male", "Female")
COW_BREEDS = ("White Fulani", "Red Bororo", "Sokoto Gudali", "Muturu", "Ndama", "Holstein", "Other")

FARMING_TIPS = [
    "Water early morning or late evening to reduce evaporation.",
    "Mulch around crops to keep soil moist longer.",
    "Rotate crops each season to protect soil health.",
    "Check leaves weekly for pests — catch them early.",
    "Store seeds in a cool, dry place away from rats.",
    "After heavy rain, clear drains so roots do not rot.",
    "Plant windbreaks to protect young crops.",
    "Test soil moisture with your finger before watering.",
    "Share surplus seedlings with neighbours — stronger community.",
    "Keep farm tools clean to stop disease spreading.",
    "Mark your boundary clearly to avoid land disputes.",
    "Listen to weather alerts before spraying chemicals.",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    legacy_db_path = os.path.abspath(DEFAULT_DB_FILE)
    configured_db_path = os.path.abspath(DB_FILE)
    if configured_db_path != legacy_db_path and not os.path.exists(configured_db_path):
        if os.path.isfile(legacy_db_path):
            async with aiosqlite.connect(legacy_db_path) as source_db:
                async with aiosqlite.connect(configured_db_path) as persistent_db:
                    await source_db.backup(persistent_db)

    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS farmers (
                phone TEXT PRIMARY KEY, name TEXT, country TEXT, state TEXT, 
                city TEXT, lga TEXT, area TEXT, token TEXT, status TEXT, xp INTEGER DEFAULT 100,
                faith_preference TEXT NOT NULL DEFAULT 'Private',
                is_demo INTEGER NOT NULL DEFAULT 0,
                avatar_path TEXT
            );
        """)
        async with conn.execute("PRAGMA table_info(farmers)") as cursor:
            farmer_columns = {row[1] for row in await cursor.fetchall()}
        if "faith_preference" not in farmer_columns:
            await conn.execute(
                "ALTER TABLE farmers ADD COLUMN faith_preference TEXT NOT NULL DEFAULT 'Private'"
            )
        if "is_demo" not in farmer_columns:
            await conn.execute(
                "ALTER TABLE farmers ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0"
            )
        if "avatar_path" not in farmer_columns:
            await conn.execute("ALTER TABLE farmers ADD COLUMN avatar_path TEXT")
        await conn.execute("""
            UPDATE farmers
            SET is_demo = 1,
                name = CASE WHEN name LIKE 'DEMO: %' THEN name ELSE 'DEMO: ' || name END
            WHERE token = 'mock_token'
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                type TEXT, sender TEXT, lga TEXT, message TEXT, status TEXT, video_path TEXT
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, alert_id INTEGER, 
                author TEXT, text TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS direct_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                sender_phone TEXT,
                receiver_phone TEXT,
                body TEXT,
                seen INTEGER DEFAULT 0
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blocker_phone TEXT NOT NULL,
                blocked_phone TEXT NOT NULL,
                guard_status TEXT NOT NULL DEFAULT 'blocked',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(blocker_phone, blocked_phone)
            );
        """)
        async with conn.execute("PRAGMA table_info(blocked_nodes)") as cursor:
            blocked_node_columns = {row[1] for row in await cursor.fetchall()}
        if "guard_status" not in blocked_node_columns:
            await conn.execute(
                "ALTER TABLE blocked_nodes ADD COLUMN guard_status TEXT NOT NULL DEFAULT 'blocked'"
            )
        if "created_at" not in blocked_node_columns:
            await conn.execute("ALTER TABLE blocked_nodes ADD COLUMN created_at DATETIME")
            await conn.execute(
                "UPDATE blocked_nodes SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
            )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS farmer_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_phone TEXT NOT NULL,
                target_phone TEXT NOT NULL,
                reason TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(reporter_phone, target_phone, reason)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS message_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                reporter_phone TEXT NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(message_id, reporter_phone)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                farmer_phone TEXT,
                lga TEXT,
                moisture REAL,
                ph REAL,
                source TEXT DEFAULT 'manual'
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                farmer_phone TEXT NOT NULL,
                lga TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS shoutouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                farmer_phone TEXT NOT NULL,
                farmer_name TEXT,
                lga TEXT,
                message TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        async with conn.execute("PRAGMA table_info(shoutouts)") as cursor:
            shoutout_columns = {row[1] for row in await cursor.fetchall()}
        for column, definition in (
            ("category", "TEXT NOT NULL DEFAULT 'Other'"),
            ("recipient", "TEXT"),
            ("template_key", "TEXT NOT NULL DEFAULT 'garden'"),
            ("image_path", "TEXT"),
        ):
            if column not in shoutout_columns:
                await conn.execute(f"ALTER TABLE shoutouts ADD COLUMN {column} {definition}")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS statuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                author_phone TEXT NOT NULL,
                author_name TEXT,
                content TEXT NOT NULL,
                original_id INTEGER,
                image_path TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        async with conn.execute("PRAGMA table_info(statuses)") as cursor:
            status_columns = {row[1] for row in await cursor.fetchall()}
        if "image_path" not in status_columns:
            await conn.execute("ALTER TABLE statuses ADD COLUMN image_path TEXT")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS status_likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status_id INTEGER NOT NULL,
                user_phone TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(status_id, user_phone)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS status_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status_id INTEGER NOT NULL,
                author_phone TEXT NOT NULL,
                author_name TEXT,
                text TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS status_hides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status_id INTEGER NOT NULL,
                user_phone TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(status_id, user_phone)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS status_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status_id INTEGER NOT NULL,
                reporter_phone TEXT NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(status_id, reporter_phone)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                farmer_phone TEXT NOT NULL,
                game_name TEXT NOT NULL,
                score INTEGER DEFAULT 0,
                xp_earned INTEGER DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS farm_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                farmer_phone TEXT NOT NULL,
                farmer_name TEXT,
                lga TEXT,
                title TEXT NOT NULL,
                description TEXT,
                price TEXT,
                contact_phone TEXT,
                category TEXT DEFAULT 'General',
                status TEXT DEFAULT 'Active',
                photo_path TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        async with conn.execute("PRAGMA table_info(farm_products)") as cursor:
            farm_product_columns = {row[1] for row in await cursor.fetchall()}
        if "is_demo" not in farm_product_columns:
            await conn.execute(
                "ALTER TABLE farm_products ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0"
            )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS farm_product_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                farmer_phone TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_read INTEGER NOT NULL DEFAULT 0
            );
        """)
        try:
            await conn.execute("ALTER TABLE farmers ADD COLUMN password_hash TEXT;")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE alerts_log ADD COLUMN video_path TEXT;")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE farm_products ADD COLUMN photo_path TEXT;")
        except Exception:
            pass
        async with conn.execute("PRAGMA table_info(direct_messages)") as cursor:
            direct_message_columns = {row[1] for row in await cursor.fetchall()}
        if "seen" not in direct_message_columns:
            await conn.execute("ALTER TABLE direct_messages ADD COLUMN seen INTEGER DEFAULT 0;")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS friendships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requester_phone TEXT NOT NULL,
                receiver_phone TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(requester_phone, receiver_phone)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS trust_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                owner_phone TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS trust_group_members (
                group_id INTEGER NOT NULL,
                farmer_phone TEXT NOT NULL,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                whatsapp_enabled INTEGER NOT NULL DEFAULT 0,
                membership_status TEXT NOT NULL DEFAULT 'accepted',
                PRIMARY KEY (group_id, farmer_phone)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS family_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                lga TEXT NOT NULL,
                town TEXT NOT NULL,
                owner_phone TEXT NOT NULL,
                invite_code TEXT NOT NULL UNIQUE,
                meeting_room TEXT NOT NULL UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS family_group_members (
                group_id INTEGER NOT NULL,
                farmer_phone TEXT NOT NULL,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_id, farmer_phone)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS family_meeting_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                author_phone TEXT NOT NULL,
                author_name TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        async with conn.execute("PRAGMA table_info(trust_group_members)") as cursor:
            trust_member_columns = {row[1] for row in await cursor.fetchall()}
        if "whatsapp_enabled" not in trust_member_columns:
            await conn.execute(
                "ALTER TABLE trust_group_members ADD COLUMN whatsapp_enabled INTEGER NOT NULL DEFAULT 0"
            )
        if "membership_status" not in trust_member_columns:
            await conn.execute(
                "ALTER TABLE trust_group_members ADD COLUMN membership_status TEXT NOT NULL DEFAULT 'accepted'"
            )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS trust_trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                farmer_phone TEXT NOT NULL,
                destination TEXT NOT NULL,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                ended_at DATETIME
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS trust_trip_checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id INTEGER NOT NULL,
                farmer_phone TEXT NOT NULL,
                xp_awarded INTEGER NOT NULL DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS spotify_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                farmer_phone TEXT NOT NULL,
                title TEXT NOT NULL,
                embed_path TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS product_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                reporter_phone TEXT NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(product_id, reporter_phone)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS product_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                reviewer_phone TEXT NOT NULL,
                reviewer_name TEXT,
                rating INTEGER CHECK(rating >= 1 AND rating <= 5),
                comment TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(product_id, reviewer_phone)
            );
        """)
        await conn.commit()
    yield


app = FastAPI(title="Farm Watch Enterprise Node", version="5.2.1", lifespan=lifespan)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

@app.get("/product-photo/{filename}")
async def product_photo(filename: str):
    safe = os.path.basename(filename)
    path = os.path.join(MEDIA_DIR, safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Photo not found")
    from fastapi.responses import FileResponse
    return FileResponse(path)


def clean_phone(phone: str) -> str:
    """Strip all non-digit characters from a phone number."""
    return "".join(c for c in phone if c.isdigit())


def phone_aliases(phone: str) -> set[str]:
    cleaned = clean_phone(phone)
    aliases = {cleaned}
    if cleaned.startswith("0") and len(cleaned) == 11:
        aliases.add("234" + cleaned[1:])
    elif cleaned.startswith("234") and len(cleaned) == 13:
        aliases.add("0" + cleaned[3:])
    return aliases


async def guard_status(conn, phone_a: str, phone_b: str) -> Optional[str]:
    """Return the strongest active Guardroom restriction for a farmer pair."""
    aliases_a = phone_aliases(phone_a)
    aliases_b = phone_aliases(phone_b)
    placeholders_a = ",".join("?" for _ in aliases_a)
    placeholders_b = ",".join("?" for _ in aliases_b)
    async with conn.execute(
        f"""SELECT guard_status FROM blocked_nodes
           WHERE (blocker_phone IN ({placeholders_a}) AND blocked_phone IN ({placeholders_b}))
              OR (blocker_phone IN ({placeholders_b}) AND blocked_phone IN ({placeholders_a}))
           ORDER BY CASE guard_status WHEN 'expelled' THEN 0 ELSE 1 END
           LIMIT 1""",
        tuple(aliases_a) + tuple(aliases_b) + tuple(aliases_b) + tuple(aliases_a),
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


# Valid Nigerian mobile prefixes (local 11-digit and international 13-digit forms)
_VALID_LOCAL_PREFIXES = ("070", "080", "081", "090", "091")
_VALID_INTL_PREFIXES = ("23470", "23480", "23481", "23490", "23491")


def is_valid_nigerian_mobile(phone: str) -> bool:
    """
    Return True if the cleaned number is a valid Nigerian mobile format.
    Accepts:
      - 11 digits starting with 070 / 080 / 081 / 090 / 091
      - 13 digits starting with 23470 / 23480 / 23481 / 23490 / 23491
    """
    cleaned = clean_phone(phone)
    if len(cleaned) == 11 and cleaned.startswith(_VALID_LOCAL_PREFIXES):
        return True
    if len(cleaned) == 13 and cleaned.startswith(_VALID_INTL_PREFIXES):
        return True
    return False


def normalize_nigerian_mobile(phone: str) -> Optional[str]:
    """
    Clean and validate a Nigerian mobile number.
    Returns the cleaned digits if valid, otherwise None.
    """
    cleaned = clean_phone(phone)
    if is_valid_nigerian_mobile(cleaned):
        return cleaned
    return None


def sanitize(text: str) -> str:
    return html.escape(text.strip())


async def can_view_status(conn, status_id: int, viewer_phone: str) -> bool:
    async with conn.execute("""
        SELECT s.author_phone
        FROM statuses s
        JOIN farmers f ON f.phone = s.author_phone
        WHERE s.id = ? AND f.status = 'Approved'
    """, (status_id,)) as cursor:
        status = await cursor.fetchone()
    if not status:
        return False
    author_phone = status["author_phone"] if isinstance(status, aiosqlite.Row) else status[0]
    if author_phone == viewer_phone:
        return True
    if await guard_status(conn, viewer_phone, author_phone):
        return False
    async with conn.execute("""
        SELECT 1 FROM friendships
        WHERE status = 'accepted'
          AND ((requester_phone = ? AND receiver_phone = ?)
            OR (requester_phone = ? AND receiver_phone = ?))
    """, (viewer_phone, author_phone, author_phone, viewer_phone)) as cursor:
        return await cursor.fetchone() is not None


def render_status_card(status, comments, highlighted=False) -> str:
    author_phone = html.escape(str(status["author_phone"]), quote=True)
    author_name = html.escape(status["author_name"] or "")
    highlight_style = "outline:2px solid #34d399;" if highlighted else ""
    avatar_path = os.path.basename(str(status["avatar_path"] or "")) if "avatar_path" in status.keys() else ""
    avatar_html = (
        f'<img src="/media/{html.escape(avatar_path, quote=True)}" alt="" '
        'style="width:36px;height:36px;border-radius:50%;object-fit:cover;margin-right:9px;">'
        if avatar_path else ""
    )
    image_path = os.path.basename(str(status["image_path"] or "")) if "image_path" in status.keys() else ""
    image_html = (
        f'<img src="/media/{html.escape(image_path, quote=True)}" alt="Status photo" '
        'loading="lazy" style="display:block;width:100%;max-height:420px;object-fit:contain;'
        'border-radius:10px;margin:10px 0;background:#0f172a;">'
        if image_path else ""
    )
    author_link = (
        f'<a href="/portal/feed?active_tab=community&view_profile={author_phone}" '
        f'style="color:#f1f5f9; text-decoration:none;">{author_name}</a>'
    )
    comments_html = "".join(
        f'<div style="font-size:13px; margin:4px 0; color:#cbd5e1;">'
        f'<a href="/portal/feed?active_tab=community&view_profile={html.escape(str(c["author_phone"]), quote=True)}" '
        f'style="color:#6ee7b7;font-weight:700;text-decoration:none;">{html.escape(c["author_name"] or "")}</a>: '
        f'{html.escape(c["text"])}</div>'
        for c in comments
    )
    return f"""
    <div id="status-{status['id']}" style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:14px; margin-bottom:12px; {highlight_style}">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="font-weight:700;display:flex;align-items:center;">{avatar_html}{author_link}</div>
            <span style="font-size:11px; color:#64748b;">{html.escape(str(status['timestamp']))}</span>
        </div>
        <p style="margin:10px 0; color:#e2e8f0; font-size:15px; line-height:1.4;">{html.escape(status['content'])}</p>
        {image_html}
        <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:8px;">
            <form action="/portal/status/like" method="post" style="margin:0;"><input type="hidden" name="status_id" value="{status['id']}"><button type="submit" style="background:none;border:none;color:#60a5fa;cursor:pointer;font-size:13px;">👍 {status['likes']}</button></form>
            <form action="/portal/status/repost" method="post" style="margin:0;"><input type="hidden" name="status_id" value="{status['id']}"><button type="submit" style="background:none;border:none;color:#34d399;cursor:pointer;font-size:13px;">🔁 Repost</button></form>
            <form action="/portal/status/hide" method="post" style="margin:0;"><input type="hidden" name="status_id" value="{status['id']}"><button type="submit" style="background:none;border:none;color:#94a3b8;cursor:pointer;font-size:13px;">🙈 Hide</button></form>
            <details style="display:inline-block;"><summary style="color:#f87171;cursor:pointer;font-size:13px;list-style:none;">🚩 Report</summary>
                <form action="/portal/status/report" method="post" style="display:grid;gap:6px;margin:6px 0;padding:10px;background:rgba(0,0,0,.2);border-radius:8px;">
                    <input type="hidden" name="status_id" value="{status['id']}">
                    <textarea name="reason" required minlength="5" maxlength="500" placeholder="Why should this post be reviewed?" style="min-width:220px;padding:8px;background:#1e293b;color:#fff;border:1px solid #475569;border-radius:8px;"></textarea>
                    <button type="submit" class="btn btn-danger" style="padding:6px 10px;">Send report</button>
                </form>
            </details>
        </div>
        {comments_html}
        <form action="/portal/status/comment" method="post" style="display:flex; gap:6px; margin-top:8px;">
            <input type="hidden" name="status_id" value="{status['id']}">
            <input type="text" name="text" placeholder="Comment or reply…" maxlength="200" required style="flex:1; padding:8px; font-size:13px; background:#1e293b; border:1px solid #475569; color:#fff; border-radius:8px; margin:0;">
            <button type="submit" class="btn btn-blue" style="padding:6px 12px; font-size:12px;">Reply</button>
        </form>
    </div>"""


async def optimize_social_image(upload: UploadFile, kind: str) -> bytes:
    """Validate and compress an uploaded profile or status photo to a bounded JPEG."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    raw = await upload.read(MAX_SOCIAL_IMAGE_UPLOAD_SIZE + 1)
    if not raw:
        raise HTTPException(status_code=422, detail="Choose a photo to upload")
    if len(raw) > MAX_SOCIAL_IMAGE_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Photo must be 8 MB or smaller")

    try:
        with Image.open(io.BytesIO(raw)) as opened:
            if opened.format not in {"JPEG", "PNG", "WEBP"}:
                raise HTTPException(
                    status_code=415, detail="Use a JPEG, PNG, or WebP photo"
                )
            if opened.width * opened.height > MAX_SOCIAL_IMAGE_PIXELS:
                raise HTTPException(
                    status_code=413, detail="Photo dimensions are too large"
                )
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=422, detail="The selected photo is invalid") from exc

    if kind == "avatar":
        image = ImageOps.fit(image, (320, 320), method=Image.Resampling.LANCZOS)
    else:
        image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)

    while True:
        for quality in (82, 72, 62):
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            if output.tell() <= MAX_SOCIAL_IMAGE_STORAGE_SIZE:
                return output.getvalue()
        if image.width <= 320 or image.height <= 320:
            raise HTTPException(status_code=422, detail="Photo could not be compressed")
        image = image.resize(
            (max(1, int(image.width * 0.8)), max(1, int(image.height * 0.8))),
            Image.Resampling.LANCZOS,
        )


def save_social_image(image_data: bytes, kind: str) -> str:
    filename = f"{kind}_{secrets.token_hex(16)}.jpg"
    destination = os.path.join(MEDIA_DIR, filename)
    with open(destination, "wb") as image_file:
        image_file.write(image_data)
    return filename


def remove_social_image(filename: Optional[str]) -> None:
    if not filename:
        return
    safe_filename = os.path.basename(filename)
    if safe_filename == filename:
        path = os.path.join(MEDIA_DIR, safe_filename)
        if os.path.isfile(path):
            os.remove(path)


def render_shoutout_card(
    shoutout, viewer_phone: str, highlighted: bool = False, id_prefix: str = ""
) -> str:
    template_key = shoutout["template_key"] or "garden-01"
    emoji, background = SHOUTOUT_TEMPLATES.get(
        template_key, SHOUTOUT_TEMPLATES["garden-01"]
    )
    shoutout_id = int(shoutout["id"])
    author_phone = html.escape(str(shoutout["farmer_phone"]), quote=True)
    recipient = html.escape(shoutout["recipient"] or "")
    image_path = os.path.basename(str(shoutout["image_path"])) if shoutout["image_path"] else ""
    image_html = (
        f'<img class="shoutout-photo" src="/media/{html.escape(image_path, quote=True)}" '
        'alt="Celebration portrait" style="display:block;width:144px;height:180px;'
        'object-fit:contain;object-position:center;background:rgba(15,23,42,.35);'
        'border:3px solid rgba(255,255,255,.8);border-radius:16px;margin:14px auto;'
        'box-shadow:0 10px 24px rgba(0,0,0,.28);">'
        if image_path else ""
    )
    remove_photo_html = ""
    if image_path and str(shoutout["farmer_phone"]) == str(viewer_phone):
        remove_photo_html = f"""
            <form action="/portal/shoutout/remove-photo" method="post" style="margin:0;"
                  onsubmit="return confirm('Remove the photo from this shout-out?');">
                <input type="hidden" name="shoutout_id" value="{shoutout_id}">
                <button type="submit" class="btn" style="padding:6px 10px;color:#fecaca;">Remove photo</button>
            </form>"""
    card_highlight = "outline:2px solid #34d399;" if highlighted else ""
    article_id = f"{id_prefix}shoutout-{shoutout_id}"
    card_id = f"{id_prefix}shoutout-card-{shoutout_id}"
    return f"""
        <article class="shoutout-entry" id="{article_id}" style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:14px;padding:12px;margin-bottom:12px;{card_highlight}">
            <div id="{card_id}" class="shoutout-card" data-template="{html.escape(template_key, quote=True)}" style="position:relative;isolation:isolate;overflow:hidden;background:{background};background-image:radial-gradient(circle at 9% 12%,rgba(255,255,255,.48),transparent 25%),radial-gradient(circle at 90% 86%,rgba(255,255,255,.28),transparent 34%),{background};color:#fff;border-radius:16px;padding:22px;text-align:center;min-height:145px;box-sizing:border-box;box-shadow:0 12px 30px rgba(0,0,0,.3);">
                <div aria-hidden="true" style="position:absolute;inset:10px;border:1px solid rgba(255,255,255,.32);border-radius:12px;pointer-events:none;"></div>
                <div style="position:relative;z-index:1;">
                    <div style="font-size:30px;text-shadow:0 2px 12px rgba(0,0,0,.25);">{emoji}</div>
                    <div class="shoutout-category" style="font-size:12px;font-weight:900;text-transform:uppercase;letter-spacing:.12em;text-shadow:0 1px 5px rgba(0,0,0,.35);">{html.escape(shoutout['category'] or 'Other')}</div>
                    {f'<div class="shoutout-recipient" style="font-size:19px;font-weight:800;margin-top:8px;text-shadow:0 2px 8px rgba(0,0,0,.3);">For {recipient}</div>' if recipient else ''}
                    <div class="shoutout-message" style="font-size:17px;font-weight:600;line-height:1.45;margin-top:10px;white-space:pre-wrap;text-shadow:0 1px 6px rgba(0,0,0,.3);">{html.escape(shoutout['message'] or '')}</div>
                    {image_html}
                    <div style="font-size:12px;font-weight:700;margin-top:12px;text-shadow:0 1px 5px rgba(0,0,0,.3);">With love from {html.escape(shoutout['lga'] or 'Olode.com.ng')} · Olode.com.ng</div>
                </div>
            </div>
            <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap;margin-top:9px;">
                <a href="/portal/feed?active_tab=community&view_profile={author_phone}" style="color:#6ee7b7;font-size:13px;font-weight:700;text-decoration:none;">{html.escape(shoutout['farmer_name'] or '')}</a>
                <span style="color:#64748b;font-size:11px;">{html.escape(str(shoutout['timestamp']))}</span>
                <span style="display:flex;gap:6px;flex-wrap:wrap;">
                    <button type="button" class="btn" onclick="shareShoutout({shoutout_id}, this)" style="padding:6px 10px;">Share</button>
                    <button type="button" class="btn" onclick="printShoutout({shoutout_id}, this)" style="padding:6px 10px;">Print</button>
                    {remove_photo_html}
                    {f'''<form action="/portal/shoutout/delete" method="post" style="margin:0;" onsubmit="return confirm('Delete this shout-out permanently?');">
                        <input type="hidden" name="shoutout_id" value="{shoutout_id}">
                        <button type="submit" class="btn" style="padding:6px 10px;color:#fecaca;border-color:rgba(248,113,113,.4);">Delete shout-out</button>
                    </form>''' if str(shoutout["farmer_phone"]) == str(viewer_phone) else ''}
                </span>
            </div>
        </article>"""


async def is_trust_group_member(conn, group_id: int, farmer_phone: str) -> bool:
    async with conn.execute(
        """SELECT 1 FROM trust_group_members
           WHERE group_id = ? AND farmer_phone = ? AND membership_status = 'accepted'""",
        (group_id, farmer_phone)
    ) as cursor:
        return await cursor.fetchone() is not None


def sign_cookie_value(value: str) -> str:
    signature = hmac.new(COOKIE_SIGNING_KEY, value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{signature}"


def verify_cookie_value(signed_value: Optional[str]) -> Optional[str]:
    if not signed_value or "." not in signed_value:
        return None
    value, signature = signed_value.rsplit(".", 1)
    expected = hmac.new(COOKIE_SIGNING_KEY, value.encode(), hashlib.sha256).hexdigest()
    return value if hmac.compare_digest(signature, expected) else None


def sign_admin_session(username: str) -> str:
    payload = f"admin-v1:{username}:{int(time.time()) + ADMIN_SESSION_TTL_SECONDS}"
    signature = hmac.new(COOKIE_SIGNING_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_admin_session(session: Optional[str]) -> Optional[str]:
    if not session or "." not in session:
        return None
    payload, signature = session.rsplit(".", 1)
    expected = hmac.new(COOKIE_SIGNING_KEY, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        version, username, expires_at = payload.split(":", 2)
        if version != "admin-v1" or int(expires_at) <= int(time.time()):
            return None
    except (ValueError, TypeError):
        return None
    return username if username == ADMIN_USERNAME else None


def mask_phone_number(phone: str) -> str:
    clean = clean_phone(phone)
    if len(clean) <= 6: return "••••" + clean[-2:] if len(clean) > 2 else "••••"
    return f"{clean[:4]}••••{clean[-3:]}"


async def async_dispatch_whatsapp(to_number: str, message_text: str):
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        print("WhatsApp dispatch skipped: Twilio credentials are not configured.")
        return
    async with DISPATCH_SEMAPHORE:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
        digits = clean_phone(to_number)
        if len(digits) == 11 and digits.startswith("0"):
            digits = "234" + digits[1:]
        clean_target = f"whatsapp:+{digits}"
        payload = {"To": clean_target, "From": TWILIO_PHONE_NUMBER, "Body": message_text}
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                res = await client.post(url, data=payload, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
                print(f"📡 Background Dispatch Status: {res.status_code}")
                if res.is_error:
                    print(f"WhatsApp dispatch failed for {clean_target}: {res.text[:300]}")
            except Exception as e:
                print(f"❌ Non-blocking network alert exception: {e}")


async def send_trust_group_whatsapp_alert(group_id: int, sender_phone: str, message: str):
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return
    async with aiosqlite.connect(DB_FILE) as conn:
        async with conn.execute("""
            SELECT tgm.farmer_phone
            FROM trust_group_members tgm
            JOIN farmers f ON f.phone = tgm.farmer_phone
            WHERE tgm.group_id = ?
              AND tgm.membership_status = 'accepted'
              AND tgm.farmer_phone != ?
              AND tgm.whatsapp_enabled = 1
              AND f.status = 'Approved'
        """, (group_id, sender_phone)) as cursor:
            recipients = [row[0] for row in await cursor.fetchall()]
    if recipients:
        await asyncio.gather(
            *(async_dispatch_whatsapp(phone, message) for phone in recipients)
        )


async def get_realtime_weather(lga: str) -> dict:
    """Fetch live weather + short forecast from Open-Meteo for a given LGA."""
    geo_coordinates = {
        "osogbo": {"lat": 7.7827, "lon": 4.5418},
        "ile-ife": {"lat": 7.4667, "lon": 4.5667},
        "ibadan": {"lat": 7.3775, "lon": 3.9470},
        "ogbomoso": {"lat": 8.1333, "lon": 4.2667},
    }
    coords = geo_coordinates.get(lga.lower().strip(), {"lat": 7.3775, "lon": 3.9470})

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={coords['lat']}&longitude={coords['lon']}"
        f"&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"
        f"&timezone=Africa%2FLagos&forecast_days=3"
    )

    fallback = {
        "temp": "28°C",
        "humidity": "—",
        "wind": "—",
        "rain": "—",
        "desc": "Weather data unavailable",
        "forecast": [],
    }

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            res = await client.get(url)
            if res.status_code != 200:
                return fallback
            data = res.json()
            current = data.get("current", {})
            daily = data.get("daily", {})

            temp = current.get("temperature_2m")
            humidity = current.get("relative_humidity_2m")
            wind = current.get("wind_speed_10m")
            rain_now = current.get("precipitation", 0) or 0

            if temp is None:
                return fallback

            # Simple farming guidance
            if rain_now > 0.5:
                desc = "Rain falling now — good for crops, avoid spraying"
            elif 22 <= temp <= 32:
                desc = "Good conditions for growth"
            elif temp > 32:
                desc = "Hot — monitor plants for water stress"
            else:
                desc = "Cool — growth may slow"

            # Build 3-day forecast
            forecast = []
            times = daily.get("time", [])
            max_t = daily.get("temperature_2m_max", [])
            min_t = daily.get("temperature_2m_min", [])
            precip = daily.get("precipitation_sum", [])
            for i in range(min(3, len(times))):
                day_label = "Today" if i == 0 else ("Tomorrow" if i == 1 else times[i][5:])  # MM-DD
                rain_mm = precip[i] if i < len(precip) else 0
                rain_txt = f"{rain_mm:.0f} mm rain" if rain_mm and rain_mm >= 0.5 else "Little/no rain"
                forecast.append({
                    "day": day_label,
                    "high": f"{max_t[i]:.0f}°" if i < len(max_t) else "—",
                    "low": f"{min_t[i]:.0f}°" if i < len(min_t) else "—",
                    "rain": rain_txt,
                })

            return {
                "temp": f"{temp:.0f}°C",
                "humidity": f"{humidity:.0f}%" if humidity is not None else "—",
                "wind": f"{wind:.0f} km/h" if wind is not None else "—",
                "rain": f"{rain_now:.1f} mm" if rain_now else "None",
                "desc": desc,
                "forecast": forecast,
            }
        except Exception:
            return fallback


async def get_prayer_times(city: str) -> dict | None:
    """Fetch today's prayer times for a Muslim user's chosen city."""
    if not city.strip():
        return None
    local_date = datetime.now(ZoneInfo("Africa/Lagos")).strftime("%d-%m-%Y")
    url = f"https://api.aladhan.com/v1/timingsByCity/{local_date}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                url,
                params={"city": city, "country": "Nigeria", "method": 3},
            )
        if response.status_code != 200:
            return None
        data = response.json()
        timings = data.get("data", {}).get("timings", {})
        keys = ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")
        if not all(timings.get(key) for key in keys):
            return None
        return {key: timings[key].split(" ")[0] for key in keys}
    except (httpx.RequestError, ValueError):
        return None


async def render_faith_card(preference: str, city: str) -> str:
    """Render optional, private content based on a user's own preference."""
    audio_stations = {
        "Christian": (
            "Nigerian Gospel Music Radio",
            "https://stream.zeno.fm/3fmqr74a7f8uv",
            "Gospel radio; Sunday service availability follows the station's schedule.",
        ),
        "Muslim": (
            "Qurango — Tarateel",
            "https://qurango.net/radio/tarateel",
            "Qur'an recitation stream via MP3Quran.",
        ),
        "Traditionalist": (
            "Afrikana Radio — Live African",
            "https://radio.afrikanabestsounds.com/listen/live_african/radio.mp3",
            "African music and culture; this is not a traditional worship service.",
        ),
        "Atheist": (
            "Nature Radio Rain",
            "https://maggie.torontocast.com:2020/stream/natureradiorain",
            "A calm nature-sounds stream.",
        ),
    }
    content = {
        "Christian": (
            "Optional reading: Luke 10:25–37. Reflect on one practical way to care "
            "for a neighbour today."
        ),
        "Traditionalist": (
            "Explore local cultural and harvest celebrations with your community. "
            "Examples include Osun-Osogbo and New Yam festivals; customs and dates "
            "vary by place, so confirm details with local organizers."
        ),
        "Atheist": (
            "A secular wellbeing prompt: take a short pause, notice one thing that "
            "went well today, and choose one helpful next step."
        ),
        "Private": (
            "Faith-based personalization is off. You can choose or change this "
            "private preference in Edit Profile at any time."
        ),
    }
    if preference == "Muslim":
        prayer_times = await get_prayer_times(city)
        if prayer_times:
            schedule = " · ".join(
                f"{html.escape(name)} {html.escape(time)}"
                for name, time in prayer_times.items()
            )
            text = (
                f"Today's prayer times for {html.escape(city)}: {schedule}. "
                "Times are provided by AlAdhan and may vary by calculation method "
                "or local mosque."
            )
        else:
            text = (
                "Prayer times are temporarily unavailable for your city. Check a "
                "local mosque for today's schedule."
            )
        content["Muslim"] = (
            "Optional Qur'an reading: Al-Hujurat 49:13, on knowing and respecting "
            "one another. " + text
        )
    if preference == "Spiritualist":
        links = (
            ("Miracle of Mind", "https://isha.sadhguru.org/global/en/miracle-of-mind"),
            ("Yoga & meditation", "https://isha.sadhguru.org/yoga-meditation/global/en"),
            ("Sadhguru wisdom & talks", "https://isha.sadhguru.org/en/wisdom"),
            (
                "Isha Foundation — search for chants",
                "https://www.youtube.com/@IshaFoundation/search?query=chants",
            ),
        )
        link_html = "".join(
            f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
            'style="display:block;color:#a7f3d0;margin:8px 0;">'
            f'{html.escape(label)} ↗</a>'
            for label, url in links
        )
        return (
            '<div class="portal-card" style="margin-top:16px;">'
            '<div class="card-header">🧘 <h3 class="card-title">Your optional spiritual wellbeing space</h3></div>'
            '<p style="font-size:13px;color:#cbd5e1;line-height:1.6;">Explore meditation, yoga, talks, and chants through these official Isha Foundation resources. They open on their original sites; content availability and language may vary.</p>'
            f'{link_html}'
            '<p style="font-size:11px;color:#94a3b8;margin:10px 0 0;">Visible only to you. Choose Private in Edit Profile to remove this space.</p>'
            '</div>'
        )
    text = content.get(preference, content["Private"])
    station = audio_stations.get(preference)
    if station:
        station_name, stream_url, station_note = station
        audio_html = f"""
        <div style="border-top:1px solid rgba(255,255,255,0.06); margin-top:14px; padding-top:12px;">
            <div style="font-size:13px; font-weight:700; color:#e2e8f0; margin-bottom:8px;">🎧 Listen here: {html.escape(station_name)}</div>
            <audio controls preload="none" aria-label="Play {html.escape(station_name)}"
                   onerror="document.getElementById('faith_audio_status').style.display='block';"
                   style="display:block; width:100%; min-height:46px;">
                <source src="{html.escape(stream_url, quote=True)}" type="audio/mpeg">
                Your browser cannot play this audio stream.
            </audio>
            <p id="faith_audio_status" role="status" style="display:none; font-size:12px; color:#fbbf24; margin:8px 0 0;">This stream is temporarily unavailable. Please try again later.</p>
            <p style="font-size:11px; color:#94a3b8; margin:8px 0 0;">Tap Play on this player; it stays on this page. {html.escape(station_note)} Data charges may apply.</p>
        </div>"""
    else:
        audio_html = (
            '<p style="font-size:12px; color:#94a3b8; margin:12px 0 0;">'
            'Choose a content preference in Edit Profile if you would like a matching audio stream.</p>'
        )
    return (
        '<div class="portal-card" style="margin-top:16px;">'
        '<div class="card-header">🌿 <h3 class="card-title">Your optional daily reflection</h3></div>'
        f'<p style="font-size:13px; color:#cbd5e1; margin:0; line-height:1.6;">{text}</p>'
        f'{audio_html}'
        '<p style="font-size:11px; color:#94a3b8; margin:10px 0 0;">'
        'Visible only to you. For prayer times, your city is sent to AlAdhan. Religious and cultural dates can vary by locality.</p>'
        '</div>'
    )


async def get_latest_soil_reading(farmer_phone: str, lga: str) -> dict:
    """
    Return the most recent soil moisture + pH reading for this farmer
    (or fall back to the latest reading in the same LGA).
    """
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        # Prefer farmer's own sensor
        async with conn.execute(
            "SELECT moisture, ph, timestamp, source FROM sensor_readings WHERE farmer_phone = ? ORDER BY id DESC LIMIT 1",
            (farmer_phone,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            # Fall back to any reading in the same LGA
            async with conn.execute(
                "SELECT moisture, ph, timestamp, source FROM sensor_readings WHERE lga = ? ORDER BY id DESC LIMIT 1",
                (lga,)
            ) as cur:
                row = await cur.fetchone()

    if not row:
        return {
            "moisture": None,
            "ph": None,
            "moisture_label": "No sensor data yet",
            "ph_label": "No sensor data yet",
            "advice": "Connect a soil sensor or enter a manual reading.",
            "timestamp": None,
        }

    moisture = row["moisture"]
    ph = row["ph"]

    # Moisture guidance (typical range 0–100%)
    if moisture is None:
        moisture_label = "—"
        moisture_advice = ""
    elif moisture < 20:
        moisture_label = f"{moisture:.0f}% — Very dry"
        moisture_advice = "Soil is dry. Consider irrigation soon."
    elif moisture < 40:
        moisture_label = f"{moisture:.0f}% — Dry"
        moisture_advice = "Moisture is low. Watch crops closely."
    elif moisture <= 70:
        moisture_label = f"{moisture:.0f}% — Good"
        moisture_advice = "Soil moisture is in a healthy range."
    else:
        moisture_label = f"{moisture:.0f}% — Wet"
        moisture_advice = "Soil is quite wet. Avoid over-watering."

    # pH guidance (most crops prefer 5.5–7.5)
    if ph is None:
        ph_label = "—"
        ph_advice = ""
    elif ph < 5.5:
        ph_label = f"{ph:.1f} — Acidic"
        ph_advice = "Soil is acidic. Lime may help many crops."
    elif ph <= 7.5:
        ph_label = f"{ph:.1f} — Good"
        ph_advice = "pH is suitable for most crops."
    else:
        ph_label = f"{ph:.1f} — Alkaline"
        ph_advice = "Soil is alkaline. Some crops may need adjustment."

    advice = moisture_advice
    if ph_advice:
        advice = f"{moisture_advice} {ph_advice}".strip()

    return {
        "moisture": moisture,
        "ph": ph,
        "moisture_label": moisture_label,
        "ph_label": ph_label,
        "advice": advice or "Sensor reading available.",
        "timestamp": row["timestamp"],
        "source": row["source"] or "manual",
    }


def authenticate_admin(admin_session: Optional[str] = Cookie(None)):
    """Require a recently authenticated, signed admin session."""
    verified = verify_admin_session(admin_session)
    if verified:
        return verified
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin login required")


async def get_current_farmer(farmer_session: Optional[str] = Cookie(None)):
    verified_phone = verify_cookie_value(farmer_session)
    if not verified_phone: return None
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM farmers WHERE phone = ?", (verified_phone,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row and not row["is_demo"] else None


@app.post("/portal/auth")
async def farmer_authentication(
    phone: str = Form(...),
    password: str = Form(...),
    next_page: str = Form("/portal/feed"),
):
    target = normalize_nigerian_mobile(phone)
    if not target:
        return RedirectResponse(
            url="/portal/login?error=Invalid phone number. Use a valid Nigerian mobile (070/080/081/090/091).",
            status_code=303
        )
    if len(password) < 6:
        return RedirectResponse(url="/portal/login?error=Password must be at least 6 characters.", status_code=303)
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM farmers WHERE phone = ?", (target,)) as cursor:
            farmer = await cursor.fetchone()
        if not farmer:
            return RedirectResponse(url="/portal/login?error=Phone number not recognized on network scale.", status_code=303)
        if farmer["is_demo"]:
            return RedirectResponse(url="/portal/login?error=Demo profiles cannot sign in.", status_code=303)
        stored = farmer["password_hash"] if "password_hash" in farmer.keys() else None
        if not stored:
            await conn.execute("UPDATE farmers SET password_hash = ? WHERE phone = ?", (pw_hash, target))
            await conn.commit()
        elif not hmac.compare_digest(stored, pw_hash):
            return RedirectResponse(url="/portal/login?error=Wrong password. Try again.", status_code=303)
    if farmer["status"] == "Pending":
        return RedirectResponse(url="/portal/login?error=Access Restricted. Awaiting verification clearance.", status_code=303)
    if farmer["status"] == STATUS_REPORTED:
        return RedirectResponse(url="/portal/login?error=Access Restricted. Your node has been reported and is under review.", status_code=303)
    if not next_page.startswith("/") or next_page.startswith("//"):
        next_page = "/portal/feed"
    res = RedirectResponse(url=next_page, status_code=303)
    signed_token = sign_cookie_value(target)
    cookie_secure = os.getenv("COOKIE_SECURE", "0") == "1"
    res.set_cookie(key="farmer_session", value=signed_token, max_age=31536000, httponly=True, secure=cookie_secure, samesite="lax")
    return res


@app.post("/submit-registration")
async def handle_registration(
    name: str = Form(...),
    phone: str = Form(...),
    city_manual: str = Form(...),
    password: str = Form(...),
    faith_preference: str = Form("Private"),
):
    if faith_preference not in FAITH_PREFERENCES:
        raise HTTPException(status_code=422, detail="Choose a valid faith-content preference")
    clean_p = normalize_nigerian_mobile(phone)
    if not clean_p:
        return HTMLResponse(content=f"""
        <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{UPGRADED_CSS}</style></head>
        <body><div class="glass-panel" style="max-width: 480px; margin: 60px auto; text-align: center;">
            <div style="font-size: 48px; margin-bottom: 16px;">⚠️</div>
            <h2 style="margin: 0 0 12px 0;">Invalid Phone Number</h2>
            <p style="color: var(--text-muted); line-height: 1.6; font-size: 15px; margin-bottom: 24px;">
                Please enter a valid Nigerian mobile number.<br>
                Accepted formats:<br>
                <b>0803 123 4567</b> or <b>2348031234567</b><br>
                (Prefixes: 070, 080, 081, 090, 091)
            </p>
            <a href="/register" class="btn btn-emerald" style="width: 100%; box-sizing: border-box;">Try Again</a>
        </div></body></html>""", status_code=400)
    if len(password) < 6:
        return RedirectResponse(url="/register?error=short", status_code=303)

    alt = None
    if clean_p.startswith("0") and len(clean_p) == 11:
        alt = "234" + clean_p[1:]
    elif clean_p.startswith("234") and len(clean_p) == 13:
        alt = "0" + clean_p[3:]
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT phone FROM farmers WHERE (phone = ? OR phone = ?) AND COALESCE(is_demo, 0) = 0",
            (clean_p, alt or clean_p)
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            return HTMLResponse(content=f"""
            <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{UPGRADED_CSS}</style></head>
            <body><div class="glass-panel" style="max-width: 480px; margin: 60px auto; text-align: center;">
                <div style="font-size: 48px; margin-bottom: 16px;">⚠️</div>
                <h2 style="margin: 0 0 12px 0;">Number Already Registered</h2>
                <p style="color: var(--text-muted); line-height: 1.6; font-size: 15px; margin-bottom: 24px;">
                    This phone number is already on Farm Watch.<br>
                    You cannot register the same number twice.
                </p>
                <a href="/portal/login" class="btn btn-emerald" style="width: 100%; box-sizing: border-box; margin-bottom:10px;">Sign In Instead</a>
                <a href="/register" class="btn" style="width: 100%; box-sizing: border-box; background:rgba(255,255,255,0.08); color:#cbd5e1;">Use a Different Number</a>
            </div></body></html>""", status_code=400)

    lookup = city_manual.strip().lower()
    geo = CITY_AUTOFILL_MAP.get(lookup,
                                {"country": "Nigeria", "state": "Region", "lga": city_manual, "area": "General Hub"})
    unique_token = hashlib.sha256(os.urandom(24)).hexdigest()[:16]
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("""
            INSERT INTO farmers (
                phone, name, country, state, city, lga, area, token, status, xp,
                password_hash, faith_preference
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', 100, ?, ?)
        """, (
            clean_p, sanitize(name), geo["country"], geo["state"],
            sanitize(city_manual), geo["lga"], geo["area"], unique_token,
            pw_hash, faith_preference
        ))
        await conn.commit()
    return HTMLResponse(content=f"""
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{UPGRADED_CSS}</style></head>
    <body><div class="glass-panel" style="max-width: 500px; margin: 50px auto; text-align: center;">
        <div style="font-size: 52px; margin-bottom: 16px;">✅</div>
        <h2 style="margin: 0 0 12px 0; font-size: 26px; font-weight: 800;">Registration Received</h2>
        <p style="color: #cbd5e1; line-height: 1.65; font-size: 16px; margin-bottom: 12px;">
            Thank you, <b style="color:#fff;">{sanitize(name)}</b>.
        </p>
        <p style="color: #94a3b8; line-height: 1.6; font-size: 15px; margin-bottom: 28px;">
            Your farm in <b style="color:#e2e8f0;">{html.escape(str(geo['lga']))}</b> has been registered.<br>
            An administrator will approve it shortly.<br>
            After approval you can sign in with your phone number.
        </p>
        <a href="/" class="btn btn-emerald" style="width: 100%; box-sizing: border-box; font-size:16px; padding:16px;">Back to Home</a>
    </div></body></html>""")


UPGRADED_CSS = """
    :root {
        /* Nature + soft psychedelic focus palette */
        --bg-deep: #0a1f14;
        --bg-moss: #122a1c;
        --panel-glass: rgba(18, 42, 32, 0.72);
        --border-glass: rgba(110, 231, 183, 0.12);
        --accent-emerald: #34d399;
        --accent-teal: #2dd4bf;
        --accent-violet: #a78bfa;
        --accent-blue: #38bdf8;
        --accent-amber: #fbbf24;
        --accent-leaf: #86efac;
        --text-main: #f0fdf4;
        --text-muted: #a7c4b5;
        --glow-green: rgba(52, 211, 153, 0.25);
        --glow-violet: rgba(167, 139, 250, 0.2);
    }
    body {
        font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
        color: var(--text-main);
        margin: 0;
        padding: 40px 20px;
        min-height: 100vh;
        box-sizing: border-box;
        /* Layered nature aurora — calm greens, soft violet, slow visual depth */
        background-color: #071510;
        background-image:
            radial-gradient(ellipse 90% 60% at 15% 10%, rgba(52, 211, 153, 0.18) 0%, transparent 55%),
            radial-gradient(ellipse 70% 50% at 85% 20%, rgba(167, 139, 250, 0.16) 0%, transparent 50%),
            radial-gradient(ellipse 80% 60% at 50% 100%, rgba(45, 212, 191, 0.12) 0%, transparent 55%),
            radial-gradient(ellipse 50% 40% at 70% 60%, rgba(251, 191, 36, 0.06) 0%, transparent 50%),
            linear-gradient(165deg, #0a1f14 0%, #0d2818 35%, #122a2a 70%, #0f1a24 100%);
        background-attachment: fixed;
    }
    .portal-header { align-items: center; }
    .portal-header-actions {
        display: flex;
        flex-wrap: wrap;
        justify-content: flex-end;
        align-items: center;
        gap: 10px;
        min-width: 0;
    }
    body::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        z-index: 0;
        opacity: 0.55;
        background-image:
            radial-gradient(1px 1px at 8% 18%, rgba(255,255,255,.82) 98%, transparent),
            radial-gradient(1.5px 1.5px at 26% 74%, rgba(196,181,253,.8) 98%, transparent),
            radial-gradient(1px 1px at 44% 34%, rgba(255,255,255,.78) 98%, transparent),
            radial-gradient(1.5px 1.5px at 63% 82%, rgba(167,243,208,.75) 98%, transparent),
            radial-gradient(1px 1px at 78% 21%, rgba(255,255,255,.8) 98%, transparent),
            radial-gradient(1px 1px at 92% 61%, rgba(196,181,253,.82) 98%, transparent),
            radial-gradient(circle at 20% 80%, rgba(134, 239, 172, 0.08) 0%, transparent 25%),
            radial-gradient(circle at 80% 40%, rgba(45, 212, 191, 0.07) 0%, transparent 30%);
    }
    @media (max-width: 640px) {
        body { padding: 18px 10px; }
        .portal-header { padding: 16px !important; align-items: flex-start !important; }
        .portal-header > div:first-child { gap: 10px !important; min-width: 0; }
        .portal-header > div:first-child h1 { font-size: 17px !important; overflow-wrap: anywhere; }
        .portal-header-actions {
            width: 100%;
            display: grid !important;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            justify-content: stretch;
            gap: 8px !important;
        }
        .portal-header-actions > * { min-width: 0; max-width: 100%; }
        .portal-header-actions .badge { grid-column: 1 / -1; justify-self: start; }
        .portal-header-actions .btn,
        .portal-header-actions > a {
            width: 100%;
            min-height: 42px;
            padding: 9px 7px !important;
            box-sizing: border-box;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            white-space: normal;
            overflow-wrap: anywhere;
            line-height: 1.25;
        }
    }
    .container { max-width: 1100px; margin: 0 auto; width: 100%; position: relative; z-index: 1; }
    .glass-panel {
        background: linear-gradient(145deg, rgba(20, 48, 36, 0.85) 0%, rgba(15, 35, 40, 0.8) 100%);
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border: 1px solid var(--border-glass);
        border-radius: 24px;
        box-shadow:
            0 25px 50px -12px rgba(0, 0, 0, 0.45),
            0 0 40px -10px var(--glow-green),
            inset 0 1px 0 rgba(255,255,255,0.06);
        padding: 40px;
        box-sizing: border-box;
    }
    .badge { display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: 9999px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
    .badge-amber { background: rgba(251, 191, 36, 0.12); color: var(--accent-amber); border: 1px solid rgba(251, 191, 36, 0.25); }
    .badge-emerald { background: rgba(52, 211, 153, 0.12); color: var(--accent-emerald); border: 1px solid rgba(52, 211, 153, 0.25); }
    .badge-blue { background: rgba(56, 189, 248, 0.12); color: var(--accent-blue); border: 1px solid rgba(56, 189, 248, 0.25); }
    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 12px 24px; border-radius: 12px; font-weight: 700; text-decoration: none; cursor: pointer; border: none; transition: all 0.25s ease; font-size: 14px; }
    .btn-emerald {
        background: linear-gradient(135deg, #34d399 0%, #14b8a6 50%, #2dd4bf 100%);
        color: #042f2e;
        box-shadow: 0 4px 20px rgba(52, 211, 153, 0.35), 0 0 24px rgba(45, 212, 191, 0.15);
    }
    .btn-emerald:hover { filter: brightness(1.08); transform: translateY(-1px); }
    .btn-danger { background: rgba(248, 113, 113, 0.12); color: #fca5a5; border: 1px solid rgba(248, 113, 113, 0.3); }
    .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; margin: 30px 0; }
    .stat-card {
        background: linear-gradient(160deg, rgba(52, 211, 153, 0.06) 0%, rgba(167, 139, 250, 0.04) 100%);
        border: 1px solid var(--border-glass);
        border-radius: 16px;
        padding: 24px;
    }
    .data-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
    .data-table th { padding: 14px; color: var(--text-muted); font-size: 12px; text-transform: uppercase; border-bottom: 1px solid var(--border-glass); text-align: left; }
    .data-table td { padding: 16px 14px; font-size: 14px; border-bottom: 1px solid rgba(255,255,255,0.03); text-align: left; }
    input[type="text"], input[type="password"], select {
        width: 100%;
        padding: 16px 18px;
        background: rgba(10, 31, 20, 0.9);
        border: 2px solid rgba(110, 231, 183, 0.25);
        color: #f0fdf4;
        border-radius: 12px;
        box-sizing: border-box;
        font-size: 18px;
        font-weight: 500;
        letter-spacing: 0.02em;
    }
    input[type="text"]::placeholder, input[type="password"]::placeholder, select::placeholder {
        color: #7d9b8c;
        font-size: 16px;
        font-weight: 400;
        opacity: 1;
    }
    input[type="text"]:focus, input[type="password"]:focus, select:focus {
        outline: none;
        border-color: #34d399;
        background: rgba(12, 40, 28, 0.95);
        box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.2), 0 0 20px rgba(45, 212, 191, 0.1);
    }
    label {
        display: block;
        margin-bottom: 8px;
        margin-top: 18px;
        font-size: 16px;
        font-weight: 700;
        color: #e2e8f0;
    }
    .btn { font-size: 16px; padding: 14px 24px; }
"""


@app.post("/admin/approve-farmer")
async def admin_direct_approve_farmer(phone: str = Form(...), username: str = Depends(authenticate_admin)):
    clean_p = clean_phone(phone)
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("UPDATE farmers SET status = 'Approved' WHERE phone = ?", (clean_p,))
        await conn.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/delete-farmer")
async def handle_delete_farmer(phone: str = Form(...), username: str = Depends(authenticate_admin)):
    clean_p = clean_phone(phone)
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("""
            DELETE FROM trust_trip_checkins
            WHERE farmer_phone = ? OR trip_id IN (
                SELECT id FROM trust_trips
                WHERE farmer_phone = ? OR group_id IN (
                    SELECT id FROM trust_groups WHERE owner_phone = ?
                )
            )
        """, (clean_p, clean_p, clean_p))
        await conn.execute("""
            DELETE FROM trust_trips
            WHERE farmer_phone = ? OR group_id IN (
                SELECT id FROM trust_groups WHERE owner_phone = ?
            )
        """, (clean_p, clean_p))
        await conn.execute("""
            DELETE FROM trust_group_members
            WHERE farmer_phone = ? OR group_id IN (
                SELECT id FROM trust_groups WHERE owner_phone = ?
            )
        """, (clean_p, clean_p))
        await conn.execute("DELETE FROM trust_groups WHERE owner_phone = ?", (clean_p,))
        await conn.execute("DELETE FROM farmers WHERE phone = ?", (clean_p,))
        await conn.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/resolve-alert")
async def resolve_alert(alert_id: int = Form(...), username: str = Depends(authenticate_admin)):
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("UPDATE alerts_log SET status = 'Resolved' WHERE id = ?", (alert_id,))
        await conn.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/admin/threats/stream", response_class=HTMLResponse)
async def admin_live_threat_feed_stream(username: str = Depends(authenticate_admin)):
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM alerts_log WHERE status = 'Active' ORDER BY id DESC") as cursor:
            active_alerts = await cursor.fetchall()
    threat_feed_html = ""
    for a in active_alerts:
        v_tag = f'<div style="margin-top:8px;"><a href="/media/{a["video_path"]}" target="_blank" style="color:var(--accent-blue); font-size:12px; font-weight:700;">📂 View Attached Clip Evidence</a></div>' if \
        a['video_path'] else ''
        threat_feed_html += f"""
        <div style="background: rgba(239, 68, 68, 0.04); border: 1px solid rgba(239, 68, 68, 0.2); padding: 18px; border-radius: 14px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; gap: 15px;">
            <div>
                <span class="badge" style="background: rgba(239,68,68,0.15); color: #f87171; border: 1px solid rgba(239,68,68,0.25); margin-bottom: 6px;">{a['type']}</span>
                <div style="font-size: 15px; color: #f1f5f9; font-weight: 500; margin: 4px 0;">"{a['message']}"</div>
                {v_tag}
                <small style="color: var(--text-muted); font-size: 12px;">Sector Target Focus: <b>{a['lga']} Sector</b> &bull; Transmitted by {a['sender']}</small>
            </div>
            <form action="/resolve-alert" method="post" style="margin:0;"><input type="hidden" name="alert_id" value="{a['id']}"><button type="submit" class="btn btn-emerald" style="padding: 8px 16px; font-size: 12px; border-radius: 8px;">Clear Alarm</button></form>
        </div>"""
    return threat_feed_html or '<p style="color: var(--text-muted); font-style: italic; margin: 0; font-size: 14px;">All sector grids reporting quiet baseline operations.</p>'


@app.post("/admin/simulate-grid")
async def admin_simulate_grid_data(username: str = Depends(authenticate_admin)):
    """Create labeled demo profiles only when explicitly enabled for an isolated test deployment."""
    if not ENABLE_DEMO_DATA:
        raise HTTPException(
            status_code=403,
            detail="Demo data is disabled. Enable it only in an isolated test deployment.",
        )
    mock_farmers = [
        ("08031112201", "Bello Kano", "Kano Municipal", "Kano City Center", 245),
        ("08031112202", "Adewale Osogbo", "Osogbo", "Ataoja Sector", 410),
        ("08031112203", "Arowolo Ife", "Ile-Ife", "Ife Central Town", 295),
        ("07051113304", "Chioma Ibadan", "Ibadan", "Ido Farming Grid", 320),
        ("08161114405", "Musa Ogbomoso", "Ogbomoso", "Ogbomoso South Central", 180),
        ("09071115506", "Fatima Osogbo", "Osogbo", "Ataoja Sector", 505),
        ("08081116607", "Tunde Ile-Ife", "Ile-Ife", "Ife Central Town", 275),
        ("08191117708", "Amina Kano", "Kano Municipal", "Kano City Center", 390),
        ("07021118809", "Segun Ibadan", "Ibadan", "Ido Farming Grid", 210),
        ("09031119910", "Ngozi Ogbomoso", "Ogbomoso", "Ogbomoso South Central", 460),
        ("08041120011", "Ibrahim Kano", "Kano Municipal", "Kano City Center", 330),
        ("08151121112", "Yetunde Osogbo", "Osogbo", "Ataoja Sector", 280),
        ("07061122213", "Chinedu Ibadan", "Ibadan", "Ido Farming Grid", 415),
        ("09081123314", "Hauwa Ile-Ife", "Ile-Ife", "Ife Central Town", 190),
        ("08091124415", "Kunle Ogbomoso", "Ogbomoso", "Ogbomoso South Central", 355),
        ("08121125516", "Blessing Kano", "Kano Municipal", "Kano City Center", 270),
        ("07031126617", "Yusuf Osogbo", "Osogbo", "Ataoja Sector", 440),
        ("09041127718", "Amaka Ibadan", "Ibadan", "Ido Farming Grid", 305),
        ("08051128819", "Salihu Ile-Ife", "Ile-Ife", "Ife Central Town", 225),
        ("08171129920", "Funke Ogbomoso", "Ogbomoso", "Ogbomoso South Central", 380),
        ("07041130021", "Abubakar Kano", "Kano Municipal", "Kano City Center", 260),
        ("09051131122", "Kemi Osogbo", "Osogbo", "Ataoja Sector", 490),
        ("08061132223", "Emeka Ibadan", "Ibadan", "Ido Farming Grid", 340),
        ("08181133324", "Zainab Ile-Ife", "Ile-Ife", "Ife Central Town", 215),
        ("07071134425", "Wale Ogbomoso", "Ogbomoso", "Ogbomoso South Central", 370),
        ("09091135526", "Maryam Kano", "Kano Municipal", "Kano City Center", 295),
        ("08021136627", "Tope Osogbo", "Osogbo", "Ataoja Sector", 425),
        ("08131137728", "Chika Ibadan", "Ibadan", "Ido Farming Grid", 250),
        ("07081138829", "Ismaila Ile-Ife", "Ile-Ife", "Ife Central Town", 360),
        ("09021139930", "Bukola Ogbomoso", "Ogbomoso", "Ogbomoso South Central", 285),
        ("08071140031", "Garba Kano", "Kano Municipal", "Kano City Center", 310),
        ("08141141132", "Sade Osogbo", "Osogbo", "Ataoja Sector", 455),
        ("07091142233", "Obinna Ibadan", "Ibadan", "Ido Farming Grid", 200),
        ("09061143334", "Aisha Ile-Ife", "Ile-Ife", "Ife Central Town", 400),
        ("08031144435", "Femi Ogbomoso", "Ogbomoso", "Ogbomoso South Central", 265),
        ("08151145536", "Halima Kano", "Kano Municipal", "Kano City Center", 335),
        ("07021146637", "Dayo Osogbo", "Osogbo", "Ataoja Sector", 475),
        ("09031147738", "Nneka Ibadan", "Ibadan", "Ido Farming Grid", 290),
        ("08041148839", "Usman Ile-Ife", "Ile-Ife", "Ife Central Town", 220),
        ("08161149940", "Ronke Ogbomoso", "Ogbomoso", "Ogbomoso South Central", 350),
    ]
    async with aiosqlite.connect(DB_FILE) as conn:
        for phone, name, lga, area, xp in mock_farmers:
            await conn.execute("""
                INSERT OR IGNORE INTO farmers
                    (phone, name, country, state, city, lga, area, token, status, xp, is_demo)
                VALUES (?, 'DEMO: ' || ?, 'Nigeria', 'Region', 'City', ?, ?, 'mock_token', 'Approved', ?, 1)
            """, (phone, name, lga, area, xp))
        await conn.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/admin/flush-grid")
async def admin_flush_grid_data(username: str = Depends(authenticate_admin)):
    """WARNING: Destructive endpoint. Use with care."""
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("DELETE FROM trust_trip_checkins;")
        await conn.execute("DELETE FROM trust_trips;")
        await conn.execute("DELETE FROM trust_group_members;")
        await conn.execute("DELETE FROM trust_groups;")
        await conn.execute("DELETE FROM farmers;")
        await conn.execute("DELETE FROM alerts_log;")
        await conn.execute("DELETE FROM alert_comments;")
        await conn.execute("DELETE FROM direct_messages;")
        await conn.execute("DELETE FROM blocked_nodes;")
        await conn.execute("DELETE FROM message_reports;")
        await conn.execute("DELETE FROM farmer_reports;")
        await conn.execute("DELETE FROM sensor_readings;")
        await conn.execute("DELETE FROM checkins;")
        await conn.execute("DELETE FROM shoutouts;")
        await conn.execute("DELETE FROM game_scores;")
        await conn.execute("DELETE FROM farm_products;")
        await conn.execute("DELETE FROM spotify_links;")
        await conn.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/admin/approve-product")
async def admin_approve_product(product_id: int = Form(...), username: str = Depends(authenticate_admin)):
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT farmer_phone, title, status, is_demo FROM farm_products WHERE id = ?",
            (product_id,)
        ) as cursor:
            product = await cursor.fetchone()
        if product and product["status"] == "Pending":
            await conn.execute("UPDATE farm_products SET status = 'Active' WHERE id = ?", (product_id,))
            if not product["is_demo"]:
                await conn.execute(
                    """INSERT INTO farm_product_notifications
                       (farmer_phone, product_id, title, status)
                       VALUES (?, ?, ?, 'Active')""",
                    (product["farmer_phone"], product_id, product["title"])
                )
        await conn.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/admin/reject-product")
async def admin_reject_product(product_id: int = Form(...), username: str = Depends(authenticate_admin)):
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT farmer_phone, title, status, is_demo FROM farm_products WHERE id = ?",
            (product_id,)
        ) as cursor:
            product = await cursor.fetchone()
        if product and product["status"] == "Pending":
            await conn.execute("UPDATE farm_products SET status = 'Rejected' WHERE id = ?", (product_id,))
            if not product["is_demo"]:
                await conn.execute(
                    """INSERT INTO farm_product_notifications
                       (farmer_phone, product_id, title, status)
                       VALUES (?, ?, ?, 'Rejected')""",
                    (product["farmer_phone"], product_id, product["title"])
                )
        await conn.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/admin/seed-demo-products")
async def admin_seed_demo_products(username: str = Depends(authenticate_admin)):
    """Add clearly labeled sample marketplace listings in a demo deployment."""
    if not ENABLE_DEMO_DATA:
        raise HTTPException(
            status_code=403,
            detail="Demo data is disabled. Enable it only on a separate test deployment.",
        )
    demo_products = [
        ("DEMO: Fresh cassava roots — 50kg", "Test listing only; not a real offer.", "₦12,000", "Crops", "Osogbo"),
        ("DEMO: Yellow maize — 100kg bag", "Sample listing for marketplace testing.", "₦45,000", "Crops", "Ibadan"),
        ("DEMO: Ripe tomatoes — basket", "Test listing only; not a real offer.", "₦8,500", "Produce", "Ile-Ife"),
        ("DEMO: White yam tubers", "Sample listing for marketplace testing.", "₦15,000", "Crops", "Ogbomoso"),
        ("DEMO: Local chicken — 10 birds", "Test listing only; not a real offer.", "₦45,000", "Livestock", "Kano Municipal"),
        ("DEMO: Carrots — fresh bundle", "Sample listing for marketplace testing.", "₦3,000", "Produce", "Osogbo"),
        ("DEMO: Groundnuts — 50kg", "Test listing only; not a real offer.", "₦38,000", "Crops", "Ibadan"),
        ("DEMO: Healthy rabbit", "Sample listing for marketplace testing.", "₦18,000", "Livestock", "Ile-Ife"),
        ("DEMO: Vegetable seed pack", "Test listing only; not a real offer.", "₦2,500", "Seeds", "Ogbomoso"),
    ]
    async with aiosqlite.connect(DB_FILE) as conn:
        for title, description, price, category, lga in demo_products:
            await conn.execute(
                """INSERT INTO farm_products
                   (farmer_phone, farmer_name, lga, title, description, price,
                    contact_phone, category, status, is_demo)
                   SELECT ?, 'DEMO: Sample Farmer', ?, ?, ?, ?, '', ?, 'Active', 1
                   WHERE NOT EXISTS (
                       SELECT 1 FROM farm_products WHERE is_demo = 1 AND title = ?
                   )""",
                ("DEMO-" + lga.upper().replace(" ", "-"), lga, title, description,
                 price, category, title)
            )
        await conn.commit()
    return RedirectResponse(url="/dashboard?demo_products_added=1", status_code=303)


@app.post("/admin/delete-product")
async def admin_delete_product(product_id: int = Form(...), username: str = Depends(authenticate_admin)):
    """Permanently delete an advert/product listing."""
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("DELETE FROM farm_products WHERE id = ?", (product_id,))
        await conn.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


READY_DECOYS = [
    {"title": "Fresh Cassava Roots — 50kg", "price": "₦12,000", "category": "Crops", "desc": "Clean, freshly harvested cassava. Good for garri or fufu. Available in Osogbo."},
    {"title": "Yellow Maize — 100kg bag", "price": "₦45,000", "category": "Crops", "desc": "Dry yellow maize, well stored. Ideal for feed or food. Ibadan area."},
    {"title": "Ripe Tomatoes — Basket", "price": "₦8,500", "category": "Produce", "desc": "Fresh red tomatoes, carefully picked. Perfect for market or home use."},
    {"title": "White Yam Tubers — Large", "price": "₦15,000", "category": "Crops", "desc": "Big, healthy white yams. Ready for planting or eating. Ile-Ife."},
    {"title": "Ripe Plantain Bunch", "price": "₦3,500", "category": "Produce", "desc": "Sweet ripe plantains. Good for frying or boiling."},
    {"title": "White Rice — 50kg", "price": "₦62,000", "category": "Crops", "desc": "Clean local white rice. Well milled and bagged."},
    {"title": "Fresh Peppers — Mix", "price": "₦6,000", "category": "Produce", "desc": "Red and green peppers, spicy and fresh. Market ready."},
    {"title": "Onions & Garlic Bundle", "price": "₦4,500", "category": "Produce", "desc": "Fresh onions and garlic. Good quality, dry and firm."},
    {"title": "White Fulani Cow — Female", "price": "₦450,000", "category": "Livestock", "desc": "Healthy White Fulani cow. Good for dairy or breeding. Vaccinated."},
    {"title": "Boer Cross Goats — Pair", "price": "₦85,000", "category": "Livestock", "desc": "Two healthy goats. Strong and well fed. Ogbomoso."},
    {"title": "Layer Chickens — 20 birds", "price": "₦120,000", "category": "Livestock", "desc": "Productive laying hens. Good egg production. Clean pen."},
    {"title": "Healthy Sheep — Male", "price": "₦65,000", "category": "Livestock", "desc": "Strong ram, good body condition. Ready for sale."},
    {"title": "Broiler Chickens — 50", "price": "₦180,000", "category": "Livestock", "desc": "Ready-to-market broilers. Healthy and active."},
    {"title": "Red Bororo Cow — Bull", "price": "₦520,000", "category": "Livestock", "desc": "Strong Red Bororo bull. Excellent for breeding. Kano area."},
    {"title": "Farm Guard Dog — Male", "price": "₦35,000", "category": "Livestock", "desc": "Alert and healthy farm dog. Good with livestock. Vaccinated."},
    {"title": "Friendly Farm Dog — Female", "price": "₦28,000", "category": "Livestock", "desc": "Calm, healthy female dog. Suitable for farm work."},
    {"title": "Groundnuts in Shell — 50kg", "price": "₦38,000", "category": "Crops", "desc": "Dry, clean groundnuts. Good for oil or roasting."},
    {"title": "Fresh Vegetables Basket", "price": "₦5,500", "category": "Produce", "desc": "Mixed fresh greens and vegetables. Harvested this morning."},
    {"title": "Local Chicken — 10 birds", "price": "₦45,000", "category": "Livestock", "desc": "Hardy local chickens. Good for free range."},
    {"title": "Cassava Stems — Planting", "price": "₦7,000", "category": "Seeds", "desc": "Healthy cassava stems for planting. Disease free."},
]


@app.post("/admin/post-ready-decoy")
async def admin_post_ready_decoy(
    request: Request,
    username: str = Depends(authenticate_admin),
):
    """Create test listings only in an explicitly enabled isolated demo deployment."""
    if not ENABLE_DEMO_DATA:
        raise HTTPException(
            status_code=403,
            detail="Demo listings are disabled. Enable them only in an isolated test deployment.",
        )
    form = await request.form()
    try:
        decoy_index = int(form.get("decoy_index") or -1)
    except ValueError:
        decoy_index = -1
    if decoy_index < 0 or decoy_index >= len(READY_DECOYS):
        return RedirectResponse(url="/dashboard", status_code=303)
    decoy = READY_DECOYS[decoy_index]

    # Handle optional photos (up to 5)
    photo_paths = []
    uploads = form.getlist("photos")
    for photo in uploads[:5]:
        if not hasattr(photo, "read"):
            continue
        try:
            raw = await photo.read()
            if not raw or len(raw) > MAX_UPLOAD_SIZE:
                continue
            fname = f"prod_{hashlib.md5(os.urandom(16)).hexdigest()}.jpg"
            dest = os.path.join(MEDIA_DIR, fname)
            saved = False
            try:
                from PIL import Image
                import io
                try:
                    import pillow_heif
                    pillow_heif.register_heif_opener()
                except Exception:
                    pass
                img = Image.open(io.BytesIO(raw))
                img = img.convert("RGB")
                img.thumbnail((800, 800))
                img.save(dest, "JPEG", quality=70)
                saved = True
            except Exception:
                with open(dest, "wb") as f:
                    f.write(raw)
                saved = True
            if saved and os.path.exists(dest):
                photo_paths.append(fname)
        except Exception:
            continue
    photo_path = ",".join(photo_paths) if photo_paths else None

    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT phone, name, lga FROM farmers WHERE status = 'Approved' AND COALESCE(is_demo, 0) = 0 ORDER BY RANDOM() LIMIT 1") as cur:
            farmer = await cur.fetchone()
        if not farmer:
            return RedirectResponse(url="/dashboard?decoy_err=nofarmer", status_code=303)
        await conn.execute(
            """INSERT INTO farm_products
               (farmer_phone, farmer_name, lga, title, description, price, contact_phone, category, photo_path, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active')""",
            (farmer["phone"], farmer["name"], farmer["lga"],
             decoy["title"], decoy["desc"], decoy["price"], farmer["phone"], decoy["category"], photo_path)
        )
        await conn.commit()
    return RedirectResponse(url="/dashboard?decoy_ok=1", status_code=303)


@app.post("/admin/post-decoy-product")
async def admin_post_decoy_product(
    request: Request,
    username: str = Depends(authenticate_admin),
):
    """Create test listings only in an explicitly enabled isolated demo deployment."""
    if not ENABLE_DEMO_DATA:
        raise HTTPException(
            status_code=403,
            detail="Demo listings are disabled. Enable them only in an isolated test deployment.",
        )
    form = await request.form()
    farmer_phone = str(form.get("farmer_phone") or "")
    title = str(form.get("title") or "")
    description = str(form.get("description") or "")
    price = str(form.get("price") or "")
    category = str(form.get("category") or "General")

    clean_phone_num = clean_phone(farmer_phone)
    title_c = sanitize(title)[:MAX_PRODUCT_TITLE]
    if not title_c:
        return RedirectResponse(url="/dashboard", status_code=303)
    desc_c = sanitize(description)[:MAX_PRODUCT_DESC]
    price_c = sanitize(price)[:40]
    cat = sanitize(category)[:30] if category else "General"

    # Handle photo uploads (up to 5)
    photo_paths = []
    uploads = form.getlist("photos")
    for photo in uploads[:5]:
        if not hasattr(photo, "read"):
            continue
        try:
            raw = await photo.read()
            if not raw or len(raw) > MAX_UPLOAD_SIZE:
                continue
            fname = f"prod_{hashlib.md5(os.urandom(16)).hexdigest()}.jpg"
            dest = os.path.join(MEDIA_DIR, fname)
            saved = False
            try:
                from PIL import Image
                import io
                try:
                    import pillow_heif
                    pillow_heif.register_heif_opener()
                except Exception:
                    pass
                img = Image.open(io.BytesIO(raw))
                img = img.convert("RGB")
                img.thumbnail((800, 800))
                img.save(dest, "JPEG", quality=70)
                saved = True
            except Exception:
                with open(dest, "wb") as f:
                    f.write(raw)
                saved = True
            if saved and os.path.exists(dest):
                photo_paths.append(fname)
        except Exception:
            continue
    photo_path = ",".join(photo_paths) if photo_paths else None

    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT name, lga, phone FROM farmers WHERE phone = ? AND COALESCE(is_demo, 0) = 0", (clean_phone_num,)) as cur:
            farmer = await cur.fetchone()
        if not farmer:
            return RedirectResponse(url="/dashboard?decoy_err=1", status_code=303)
        await conn.execute(
            """INSERT INTO farm_products
               (farmer_phone, farmer_name, lga, title, description, price, contact_phone, category, photo_path, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active')""",
            (farmer["phone"], farmer["name"], farmer["lga"], title_c, desc_c, price_c, farmer["phone"], cat, photo_path)
        )
        await conn.commit()
    return RedirectResponse(url="/dashboard?decoy_ok=1", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if verify_admin_session(request.cookies.get("admin_session")) != ADMIN_USERNAME:
        return RedirectResponse(
            url="/admin/login?next_page=%2Fdashboard",
            status_code=303
        )
    username = ADMIN_USERNAME
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM farmers ORDER BY xp DESC") as c1:
            all_farmers = await c1.fetchall()
        async with conn.execute("SELECT * FROM alerts_log WHERE status = 'Active'") as c2:
            active_alerts = await c2.fetchall()
        async with conn.execute("""
            SELECT mr.id, mr.timestamp, mr.reporter_phone, dm.body, dm.sender_phone, dm.receiver_phone
            FROM message_reports mr
            JOIN direct_messages dm ON dm.id = mr.message_id
            ORDER BY mr.id DESC LIMIT 30
        """) as c3:
            recent_reports = await c3.fetchall()
        async with conn.execute("""
            SELECT fr.id, fr.timestamp, fr.reporter_phone, fr.target_phone,
                   fr.reason, reporter.name AS reporter_name, target.name AS target_name
            FROM farmer_reports fr
            LEFT JOIN farmers reporter ON reporter.phone = fr.reporter_phone
            LEFT JOIN farmers target ON target.phone = fr.target_phone
            ORDER BY fr.id DESC LIMIT 50
        """) as c_farmer_reports:
            recent_farmer_reports = await c_farmer_reports.fetchall()
        async with conn.execute("SELECT * FROM farm_products ORDER BY id DESC LIMIT 100") as c4:
            all_products = await c4.fetchall()

    live_farmers = [f for f in all_farmers if not f["is_demo"]]
    total_nodes = len(live_farmers)
    pending_clearance = sum(1 for f in live_farmers if f["status"] in RESTRICTED_STATUSES)
    active_threats = len(active_alerts)
    pulse_class = "pulse" if pending_clearance > 0 else ""

    # Safe data preparation for JavaScript extraction
    map_nodes_json = html.escape(json.dumps([
        {"name": f["name"], "lga": f["lga"], "status": f["status"]}
        for f in live_farmers if f["status"] == "Approved"
    ]), quote=True)
    map_threats_json = html.escape(json.dumps([
        {"type": a["type"], "lga": a["lga"]} for a in active_alerts
    ]), quote=True)

    pending_html = ""
    for f in live_farmers:
        if f["status"] in RESTRICTED_STATUSES:
            badge_class = "badge-amber" if f["status"] == STATUS_REPORTED else "badge-blue"
            status_badge = f'<span class="badge {badge_class}">{f["status"]}</span>'
            pending_html += f"""
            <tr>
                <td style="font-weight: 600; color: #fff;">{f['name']}</td>
                <td style="font-family: monospace; color: var(--text-muted);">{f['phone']}</td>
                <td><span class="badge badge-blue">{f['lga']}</span> {status_badge}</td>
                <td><div style="display: flex; gap: 8px;">
                    <form action="/admin/approve-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{f['phone']}"><button type="submit" class="btn btn-emerald" style="padding: 6px 14px; font-size: 12px; border-radius: 8px;">Grant Clearance</button></form>
                    <form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{f['phone']}"><button type="submit" class="btn btn-danger" style="padding: 6px 14px; font-size: 12px; border-radius: 8px;">Deny</button></form>
                </div></td>
            </tr>"""

    active_nodes_html = ""
    leaderboard_html = ""
    rank = 1
    for f in live_farmers:
        if f['status'] == 'Approved':
            if rank <= 5:
                leaderboard_html += f"<tr><td>🏅 <b>#{rank}</b></td><td>{f['name']}</td><td><span class='badge badge-blue'>{f['lga']}</span></td><td style='color:var(--accent-amber); font-weight:bold;'>{f['xp']} XP</td></tr>"
                rank += 1
            active_nodes_html += f"""
            <tr>
                <td style="font-weight: 600; color: #fff;">{f['name']}</td>
                <td style="font-family: monospace; color: var(--text-muted);">{f['phone']}</td>
                <td>{f['state']} &rarr; {f['lga']}</td>
                <td><span class="badge badge-emerald">Operational</span></td>
                <td><form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{f['phone']}"><button type="submit" class="btn btn-danger" style="padding: 6px 12px; font-size: 12px; border-radius: 8px;">Remove Node</button></form></td>
            </tr>"""

    pending_table = f'<div style="overflow-x: auto;"><table class="data-table"><thead><tr><th>Node Name</th><th>Phone</th><th>Sector / Status</th><th>Actions</th></tr></thead><tbody>{pending_html}</tbody></table></div>' if pending_clearance > 0 else '<p style="color: var(--text-muted); font-style: italic; margin: 0; font-size: 14px;">No new registrations or reported nodes awaiting clearance.</p>'

    # All products for admin management (approve / reject / delete)
    products_rows = ""
    for prod in all_products:
        status_badge = f'<span class="badge badge-blue">{html.escape(prod["status"] or "")}</span>'
        approve_btn = ""
        if prod["status"] == "Pending":
            approve_btn = f'''<form action="/admin/approve-product" method="post" style="margin:0;"><input type="hidden" name="product_id" value="{prod['id']}"><button type="submit" class="btn btn-emerald" style="padding:6px 12px; font-size:12px;">Approve</button></form>
                <form action="/admin/reject-product" method="post" style="margin:0;"><input type="hidden" name="product_id" value="{prod['id']}"><button type="submit" class="btn btn-danger" style="padding:6px 12px; font-size:12px;">Reject</button></form>'''
        products_rows += f"""
        <tr>
            <td style="font-weight:600; color:#fff;">{html.escape(prod['title'] or '')}</td>
            <td>{html.escape(prod['farmer_name'] or '')}</td>
            <td><span class="badge badge-blue">{html.escape(prod['lga'] or '')}</span> {status_badge}</td>
            <td style="font-size:13px; max-width:200px;">{html.escape((prod['description'] or '')[:60])}</td>
            <td><div style="display:flex; gap:6px; flex-wrap:wrap;">
                {approve_btn}
                <form action="/admin/delete-product" method="post" style="margin:0;" onsubmit="return confirm('Permanently delete this advert?');"><input type="hidden" name="product_id" value="{prod['id']}"><button type="submit" class="btn btn-danger" style="padding:6px 12px; font-size:12px;">Delete</button></form>
            </div></td>
        </tr>"""
    pending_products_table = f'<div style="overflow-x:auto;"><table class="data-table"><thead><tr><th>Title</th><th>Seller</th><th>LGA / Status</th><th>Details</th><th>Actions</th></tr></thead><tbody>{products_rows or "<tr><td colspan=5 style=color:var(--text-muted);font-style:italic;>No products found.</td></tr>"}</tbody></table></div>'

    # Farmer dropdown for decoy product posting (injected mock + any approved farmers)
    farmer_options = ""
    for f in all_farmers:
        if f["status"] == "Approved" and not f["is_demo"]:
            farmer_options += f'<option value="{f["phone"]}">{html.escape(f["name"] or "")} — {html.escape(f["lga"] or "")} ({f["phone"]})</option>'
    if not farmer_options:
        farmer_options = '<option value="">No approved farmers yet</option>'
    cat_options = "".join([f'<option value="{c}">{c}</option>' for c in PRODUCT_CATEGORIES])
    decoy_form_html = f'''
    <form action="/admin/post-decoy-product" method="post" enctype="multipart/form-data" style="display:grid; gap:12px; max-width:640px;">
        <div>
            <label style="font-size:13px; color:var(--text-muted);">Post as farmer</label>
            <select name="farmer_phone" required style="width:100%; padding:12px; background:#090d16; border:1px solid var(--border-glass); color:#fff; border-radius:10px;">{farmer_options}</select>
        </div>
        <div>
            <label style="font-size:13px; color:var(--text-muted);">Title</label>
            <input type="text" name="title" required maxlength="80" placeholder="e.g. Fresh cassava 50kg" style="width:100%; padding:12px; background:#090d16; border:1px solid var(--border-glass); color:#fff; border-radius:10px; box-sizing:border-box;">
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
            <div>
                <label style="font-size:13px; color:var(--text-muted);">Category</label>
                <select name="category" style="width:100%; padding:12px; background:#090d16; border:1px solid var(--border-glass); color:#fff; border-radius:10px;">{cat_options}</select>
            </div>
            <div>
                <label style="font-size:13px; color:var(--text-muted);">Price</label>
                <input type="text" name="price" maxlength="40" placeholder="e.g. ₦15,000" style="width:100%; padding:12px; background:#090d16; border:1px solid var(--border-glass); color:#fff; border-radius:10px; box-sizing:border-box;">
            </div>
        </div>
        <div>
            <label style="font-size:13px; color:var(--text-muted);">Description</label>
            <input type="text" name="description" maxlength="300" placeholder="Quality, quantity, location notes…" style="width:100%; padding:12px; background:#090d16; border:1px solid var(--border-glass); color:#fff; border-radius:10px; box-sizing:border-box;">
        </div>
        <div>
            <label style="font-size:13px; color:var(--text-muted);">Photos (optional, up to 5)</label>
            <input type="file" name="photos" accept="image/*" multiple style="width:100%; padding:10px; background:#090d16; border:1px solid var(--border-glass); color:#fff; border-radius:10px; box-sizing:border-box;">
            <p style="font-size:12px; color:#94a3b8; margin:6px 0 0 0;">iPhone and Android photos are accepted. Images are resized automatically.</p>
        </div>
        <button type="submit" class="btn btn-emerald" style="padding:12px 20px;">Post Decoy Listing (goes online immediately)</button>
    </form>
    '''

    # 20 ready-made Nigerian market decoys — one-click post
    ready_rows = ""
    for i, d in enumerate(READY_DECOYS):
        ready_rows += f"""
        <tr>
            <td style="font-weight:600; color:#fff;">{html.escape(d['title'])}</td>
            <td>{html.escape(d['price'])}</td>
            <td><span class="badge badge-blue">{html.escape(d['category'])}</span></td>
            <td style="font-size:13px; max-width:180px;">{html.escape(d['desc'][:60])}</td>
            <td>
                <form action="/admin/post-ready-decoy" method="post" enctype="multipart/form-data" style="margin:0; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                    <input type="hidden" name="decoy_index" value="{i}">
                    <input type="file" name="photos" accept="image/*" multiple style="font-size:12px; color:#cbd5e1; max-width:160px;">
                    <button type="submit" class="btn btn-emerald" style="padding:6px 14px; font-size:12px;">Post</button>
                </form>
            </td>
        </tr>"""
    ready_decoys_table = f'<div style="overflow-x:auto;"><table class="data-table"><thead><tr><th>Item</th><th>Price</th><th>Category</th><th>Details</th><th>Photos + Post</th></tr></thead><tbody>{ready_rows}</tbody></table></div>'

    active_table = f'<div style="overflow-x: auto;"><table class="data-table"><thead><tr><th>Node Name</th><th>Phone Address</th><th>Geographic Network Path</th><th>Status</th><th>Management</th></tr></thead><tbody>{active_nodes_html}</tbody></table></div>' if active_nodes_html else '<p style="color: var(--text-muted); font-style: italic; text-align: center;">No active nodes operating on current security grid.</p>'
    demo_controls_html = (
        '<form action="/admin/simulate-grid" method="post" style="margin:0;"><button type="submit" class="btn btn-emerald">⚙️ Add labeled demo farmers</button></form>'
        '<form action="/admin/seed-demo-products" method="post" style="margin:0;"><button type="submit" class="btn btn-emerald">🛒 Add sample marketplace posts</button></form>'
        if ENABLE_DEMO_DATA else
        '<span style="font-size:12px; color:#94a3b8;">To test, set ENABLE_DEMO_DATA=true in your separate staging service environment, then reload this page. Do not enable on the live service.</span>'
    )

    reports_rows = ""
    for r in recent_reports:
        reports_rows += f"""
        <tr>
            <td style="font-size:12px; color:var(--text-muted);">{r['timestamp']}</td>
            <td style="font-family:monospace; font-size:12px;">{r['reporter_phone']}</td>
            <td style="font-family:monospace; font-size:12px;">{r['sender_phone']}</td>
            <td style="font-size:13px; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{html.escape(r['body'][:80])}</td>
        </tr>"""
    reports_table = f"""
    <div style="overflow-x:auto;">
        <table class="data-table">
            <thead><tr><th>When</th><th>Reporter</th><th>Sender</th><th>Message Preview</th></tr></thead>
            <tbody>{reports_rows or "<tr><td colspan='4' style='color:var(--text-muted); font-style:italic;'>No message reports yet.</td></tr>"}</tbody>
        </table>
    </div>"""
    farmer_report_rows = "".join(
        f"""<tr>
            <td style="font-size:12px;color:var(--text-muted);">{html.escape(str(report["timestamp"]))}</td>
            <td>{html.escape(report["reporter_name"] or report["reporter_phone"])}</td>
            <td>{html.escape(report["target_name"] or report["target_phone"])}</td>
            <td style="white-space:pre-wrap;">{html.escape(report["reason"])}</td>
        </tr>"""
        for report in recent_farmer_reports
    )
    farmer_reports_table = f"""
    <div style="overflow-x:auto;">
        <table class="data-table">
            <thead><tr><th>When</th><th>Reporter</th><th>Reported farmer</th><th>Reason</th></tr></thead>
            <tbody>{farmer_report_rows or "<tr><td colspan='4' style='color:var(--text-muted);font-style:italic;'>No farmer reports yet.</td></tr>"}</tbody>
        </table>
    </div>"""

    html_template_head = f"""
    <html>
    <head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{UPGRADED_CSS} .map-container {{ background: #040814; border: 1px solid var(--border-glass); border-radius: 20px; padding: 20px; margin-bottom: 30px; position: relative; overflow: hidden; }} .grid-bg {{ stroke: rgba(59, 130, 246, 0.05); stroke-width: 1; fill: none; }} .map-dot {{ transition: all 0.5s ease; cursor: pointer; }} .map-pulse {{ animation: map-pulse-ring 1.5s infinite ease-out; transform-origin: center; }} @keyframes map-pulse-ring {{ 0% {{ r: 6; opacity: 1; }} 100% {{ r: 25; opacity: 0; }} }}</style></head>
    <body>
        <div class="container" id="dashboard-content">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-glass); padding-bottom: 24px; flex-wrap: wrap; gap: 15px;">
                <div><h1>📡 Global Command Control</h1><p style="margin: 4px 0 0 0; color: var(--text-muted); font-size: 14px;">Farm Watch Security Operations Matrix</p></div>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <a href="/" class="btn" style="background: rgba(255,255,255,0.08); color: #e2e8f0; border: 1px solid var(--border-glass); padding: 10px 18px; font-size: 13px;">🏠 Exit to Home</a>
                    <a href="/portal/login?next_page=%2Fportal%2Ffeed%3Factive_tab%3Dfarm_market" target="_blank" rel="noopener" class="btn btn-blue" style="padding:10px 14px; font-size:13px;">👨‍🌾 Open farmer account</a>
                    {demo_controls_html}
                    <form action="/admin/flush-grid" method="post" style="margin:0;"><button type="submit" class="btn btn-danger">🗑️ Flush Grid Records</button></form>
                </div>
            </div>
            <div class="stats-grid">
                <div class="stat-card" style="border-left: 4px solid var(--accent-blue);"><div>DEPLOYED STRUCTURE NODES</div><h3 id="stat_total">{total_nodes}</h3></div>
                <div class="stat-card" style="border-left: 4px solid var(--accent-amber);"><div>GATE AUTHORIZATIONS PENDING</div><h3 id="stat_pending" class="{pulse_class}">{pending_clearance}</h3></div>
                <div class="stat-card" style="border-left: 4px solid #ef4444;"><div>ACTIVE EMERGENCY THREATS</div><h3 id="stat_threats">{active_threats}</h3></div>
            </div>
            <div class="map-container">
                <h3>🗺️ Tactical Sector Infrastructure Map</h3>
                <svg id="vector_map" data-nodes="{map_nodes_json}" data-threats="{map_threats_json}" width="100%" height="320" style="background:#030712; border-radius:12px; border:1px solid rgba(255,255,255,0.02)"><defs><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 40 0 L 0 0 0 40" class="grid-bg"/></pattern></defs><rect width="100%" height="100%" fill="url(#grid)" /><g id="map_hardware_layer"></g></svg>
            </div>
            <div class="glass-panel" style="margin-bottom: 30px; padding: 30px;"><h3>🏆 Node Reliability Leaderboard</h3><table class="data-table"><thead><tr><th>Rank</th><th>Farmer Deployed Node Name</th><th>Grid Sector Focus</th><th>Network Rating</th></tr></thead><tbody>{leaderboard_html or "<tr><td colspan='4' style='color:var(--text-muted); font-style:italic;'>No XP metrics available.</td></tr>"}</tbody></table></div>
            <div class="glass-panel" style="margin-bottom: 30px; padding: 30px;"><h3><span style="color: #ef4444;" class="pulse">&bull;</span> Real-Time Emergency Vector Feed</h3><div id="live_threat_feed_target"><p style="color: var(--text-muted); font-style: italic; margin: 0; font-size: 14px;">Connecting link matrix...</p></div></div>
            <div class="glass-panel" style="margin-bottom: 30px; padding: 30px;"><h3>⚡ Demo Market Listings</h3><p style="color:var(--text-muted); font-size:14px; margin:0 0 16px 0;">For staging only. In Render, open your staging web service → Environment → add ENABLE_DEMO_DATA with value true → save and redeploy. Then use “Add sample marketplace posts” above and open the farmer account link to view the clearly labeled examples. Do not enable demo data on the live service.</p>{ready_decoys_table}</div>
            <div class="glass-panel" style="margin-bottom: 30px; padding: 30px;"><h3>🧪 Demo Listing Creator</h3><p style="color:var(--text-muted); font-size:14px; margin:0 0 16px 0;">Test listings are disabled on production deployments.</p>{decoy_form_html}</div>
            <div class="glass-panel" style="margin-bottom: 30px; padding: 30px;"><h3>🛒 Manage Adverts / Products</h3>{pending_products_table}</div>
            <div class="glass-panel" style="margin-bottom: 30px; padding: 30px;"><h3>⏳ Executive Node Approvals Pending</h3>{pending_table}</div>
            <div class="glass-panel" style="margin-bottom: 30px; padding: 30px;"><h3>🚩 Recent Message Reports</h3>{reports_table}</div>
            <div class="glass-panel" style="margin-bottom: 30px; padding: 30px;"><h3>🛡️ Farmer Safety Reports</h3>{farmer_reports_table}</div>
            <div class="glass-panel" style="padding: 30px;"><h3>🗂️ Active Grid Infrastructure Map</h3>{active_table}</div>
        </div>
    """
    # Pure raw string for the script layout ensures Python doesn't look at javascript literals like ${p.x}
    html_template_script = """
        <script>
            const geographicSectorCoordinates = {"OSOGBO": {x: 150, y: 220}, "ILE-IFE": {x: 280, y: 240}, "IBADAN": {x: 110, y: 140}, "OGBOMOSO": {x: 180, y: 80}, "KANO MUNICIPAL": {x: 620, y: 70}, "FAGGE": {x: 740, y: 90}, "IKEJA": {x: 450, y: 260}, "LEKKI": {x: 520, y: 280}};
            function renderTacticalVectorMap() { 
                const layer = document.getElementById('map_hardware_layer'); 
                if(!layer) return; 
                layer.innerHTML = ""; 
                const map = document.getElementById('vector_map');
                const deploymentNodes = JSON.parse(map.dataset.nodes || '[]');
                const operationalThreats = JSON.parse(map.dataset.threats || '[]');
                operationalThreats.forEach(t => { 
                    const p = geographicSectorCoordinates[t.lga.toUpperCase()] || {x: 350, y: 160}; 
                    layer.innerHTML += `<circle cx="${p.x}" cy="${p.y}" r="8" fill="rgba(239, 68, 68, 0.4)" class="map-pulse"/><circle cx="${p.x}" cy="${p.y}" r="5" fill="#ef4444" class="map-dot"/>`; 
                }); 
                deploymentNodes.forEach(n => { 
                    const k = n.lga.toUpperCase(), p = geographicSectorCoordinates[k] || {x: 350, y: 160}; 
                    if (!operationalThreats.some(t => t.lga.toUpperCase() === k)) { 
                        layer.innerHTML += `<circle cx="${p.x}" cy="${p.y}" r="6" fill="#10b981" class="map-dot"/><text x="${p.x + 10}" y="${p.y + 4}" fill="#94a3b8" font-size="10" font-family="monospace">${n.lga}</text>`; 
                    } 
                }); 
            }
            async function pullLiveThreatStream() { try { const e = await fetch('/admin/threats/stream'); const target = document.getElementById('live_threat_feed_target'); if (200 === e.status && target) { const t = await e.text(); if (target.innerHTML !== t) { target.innerHTML = t; renderTacticalVectorMap(); } } } catch (err) { console.error(err); } }
            function showAdminFlash(message, isError) {
                const toast = document.createElement('div');
                toast.textContent = (isError ? '⚠️ ' : '✅ ') + message;
                toast.style.cssText = 'position:fixed;top:24px;left:50%;transform:translateX(-50%);background:' + (isError ? 'rgba(239,68,68,.95)' : 'rgba(16,185,129,.95)') + ';color:#fff;padding:14px 28px;border-radius:14px;font-weight:800;font-size:16px;z-index:9999;box-shadow:0 10px 30px rgba(0,0,0,.4);max-width:90%;text-align:center;';
                document.body.appendChild(toast);
                setTimeout(() => toast.remove(), 3500);
            }
            document.addEventListener('submit', async function(event) {
                const form = event.target;
                if (!form || form.tagName !== 'FORM' || event.defaultPrevented || form.method.toLowerCase() !== 'post') return;
                const action = new URL(form.action, window.location.href);
                if (action.origin !== window.location.origin ||
                    !(action.pathname.startsWith('/admin/') || action.pathname === '/delete-farmer' || action.pathname === '/resolve-alert')) return;
                event.preventDefault();
                const button = form.querySelector('button[type="submit"], input[type="submit"]');
                if (button) button.disabled = true;
                try {
                    const response = await fetch(action, {method: 'POST', body: new FormData(form), credentials: 'same-origin'});
                    const finalUrl = new URL(response.url);
                    if (!response.ok || finalUrl.searchParams.has('decoy_err')) throw new Error('Action failed. Please try again.');
                    const html = await response.text();
                    const updatedPage = new DOMParser().parseFromString(html, 'text/html');
                    const updatedDashboard = updatedPage.getElementById('dashboard-content');
                    const dashboard = document.getElementById('dashboard-content');
                    if (!updatedDashboard || !dashboard) throw new Error('Could not refresh dashboard data.');
                    const scrollPosition = window.scrollY;
                    dashboard.innerHTML = updatedDashboard.innerHTML;
                    window.scrollTo(0, scrollPosition);
                    renderTacticalVectorMap();
                    await pullLiveThreatStream();
                    const messages = {
                        '/admin/approve-farmer': 'Farmer approved',
                        '/delete-farmer': 'Farmer removed',
                        '/resolve-alert': 'Alert cleared',
                        '/admin/simulate-grid': 'Mock farmer data added',
                        '/admin/flush-grid': 'Grid records cleared',
                        '/admin/approve-product': 'Product approved',
                        '/admin/reject-product': 'Product rejected',
                        '/admin/seed-demo-products': 'Sample marketplace posts added',
                        '/admin/delete-product': 'Product deleted',
                        '/admin/post-decoy-product': 'Test listing posted',
                        '/admin/post-ready-decoy': 'Market listing posted'
                    };
                    showAdminFlash(messages[action.pathname] || 'Action completed', false);
                } catch (error) {
                    showAdminFlash(error.message || 'Action failed. Please try again.', true);
                } finally {
                    if (button && button.isConnected) button.disabled = false;
                }
            });
            setInterval(pullLiveThreatStream, 2000); window.onload = () => { pullLiveThreatStream(); renderTacticalVectorMap(); };
        </script>
    </body></html>
    """

    return HTMLResponse(content=html_template_head + html_template_script)


@app.get("/register", response_class=HTMLResponse)
def registration_form():
    return f"""<html>
    <head>
        <meta name='viewport' content='width=device-width, initial-scale=1.0'>
        <style>
            {UPGRADED_CSS}
            .step-hint {{
                background: rgba(16,185,129,0.1);
                border: 1px solid rgba(16,185,129,0.25);
                border-radius: 12px;
                padding: 14px 16px;
                margin-bottom: 24px;
                font-size: 15px;
                color: #a7f3d0;
                line-height: 1.5;
            }}
            .field-help {{
                font-size: 14px;
                color: #cbd5e1;
                margin: 8px 0 4px 0;
                line-height: 1.45;
            }}
        </style>
    </head>
    <body>
        <div class='glass-panel' style='max-width: 500px; margin: 30px auto;'>
            <h2 style="font-size:28px; margin:0 0 6px 0; font-weight:800;">Join Farm Watch</h2>
            <p style="color:#94a3b8; font-size:16px; margin:0 0 20px 0;">Register your farm so neighbours can help protect it</p>

            <div class="step-hint">
                You only need three things:<br>
                <b style="color:#ecfdf5;">1.</b> Your full name &nbsp;
                <b style="color:#ecfdf5;">2.</b> Your phone number &nbsp;
                <b style="color:#ecfdf5;">3.</b> Your town
            </div>

            <form action='/submit-registration' method='post'>
                <label>1. Your Full Name</label>
                <input type='text' name='name' required placeholder='Example: Adewale Ojo' autocomplete='name'>

                <label>2. Your Phone Number</label>
                <input type='text' name='phone' placeholder='Example: 0803 123 4567' required inputmode='numeric' autocomplete='tel'>
                <p class="field-help">
                    Type your normal phone number.<br>
                    It must start with <b style="color:#f8fafc;">070, 080, 081, 090 or 091</b>
                </p>

                <label>3. Your Town / City</label>
                <input type='text' name='city_manual' placeholder='Example: Osogbo' required autocomplete='address-level2'>
                <p class="field-help">
                    Write the name of your town (e.g. Osogbo, Ibadan, Ile-Ife, Ogbomoso)
                </p>

                <label>Optional: Content preference</label>
                <select name="faith_preference">
                    <option value="Private" selected>Private / no personalization</option>
                    <option value="Christian">Christian</option>
                    <option value="Muslim">Muslim</option>
                    <option value="Traditionalist">Traditionalist</option>
                    <option value="Atheist">Atheist / secular</option>
                    <option value="Spiritualist">Spiritualist</option>
                </select>
                <p class="field-help">
                    This is voluntary and private. It is used only to tailor your daily content,
                    is not shown on your profile, and can be changed or removed later.
                    If you choose Muslim content, your town is sent to AlAdhan to fetch prayer times.
                </p>

                <label>4. Create a Password</label>
                <input type='password' name='password' placeholder='At least 6 characters' required minlength='6' autocomplete='new-password'>
                <p class="field-help">This password protects your account from ID theft.</p>

                <br>
                <button type='submit' class='btn btn-emerald' style='width:100%; font-size:18px; padding:18px; margin-top:8px;'>
                    Register My Farm
                </button>
            </form>

            <div style="display:grid; gap:10px; margin-top:24px;">
                <a href="/portal/login" class="btn btn-emerald" style="display:block; text-align:center; padding:14px; text-decoration:none; box-sizing:border-box;">Already registered? Sign in</a>
                <a href="/#admin-login" class="btn" style="display:block; text-align:center; padding:14px; background:rgba(245,158,11,0.12); color:#fbbf24; text-decoration:none; border:1px solid rgba(245,158,11,0.35); border-radius:12px; box-sizing:border-box;">Admin Login</a>
                <a href="/" class="btn" style="display:block; text-align:center; padding:14px; background:rgba(255,255,255,0.06); color:#cbd5e1; text-decoration:none; border:1px solid rgba(255,255,255,0.12); border-radius:12px; box-sizing:border-box;">← Back to Main Page</a>
            </div>
        </div>
    </body>
    </html>"""


@app.get("/admin/export-ledger")
async def admin_export_ledger(username: str = Depends(authenticate_admin)):
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM alerts_log") as cursor:
            logs = await cursor.fetchall()
    csv_data = "Timestamp,Type,Sender,District,Message,Status\n"
    for log in logs: csv_data += f"\"{log['timestamp']}\",\"{log['type']}\",\"{log['sender']}\",\"{log['lga']}\",\"{log['message']}\",\"{log['status']}\"\n"
    return StreamingResponse(iter([csv_data]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=ledger.csv"})


@app.get("/portal/login", response_class=HTMLResponse)
def farmer_login_page(error: str = None, next_page: str = "/portal/feed"):
    if not next_page.startswith("/") or next_page.startswith("//"):
        next_page = "/portal/feed"
    err_msg = f"<p style='color:#fecaca; background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.3); padding:12px 14px; border-radius:10px; font-size:15px; line-height:1.4; margin-bottom:16px;'>{error}</p>" if error else ""
    return f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>{UPGRADED_CSS}</style></head>
    <body><div class='glass-panel' style='max-width:420px; margin:60px auto;'>
        <h2 style="font-size:26px; margin-bottom:8px;">Member Sign In</h2>
        <p style="color:#94a3b8; font-size:15px; margin-bottom:20px;">Enter your phone number and password</p>
        <p style="color:#cbd5e1; font-size:13px; margin-bottom:16px;">Signing in here keeps your Admin session active in this browser.</p>
        {err_msg}
        <form action='/portal/auth' method='post'>
            <input type='hidden' name='next_page' value='{html.escape(next_page, quote=True)}'>
            <label>Phone Number</label>
            <input type='text' name='phone' placeholder='e.g. 0803 123 4567' required inputmode='numeric'>
            <label style="margin-top:12px; display:block;">Password</label>
            <input type='password' name='password' placeholder='Your password' required minlength='6'>
            <p style='font-size:14px; color:#cbd5e1; margin:8px 0 18px 0; line-height:1.4;'>
                Nigerian mobile only — <b style="color:#f8fafc;">070, 080, 081, 090, 091</b>
            </p>
            <button type='submit' class='btn btn-emerald' style='width:100%; font-size:17px; padding:16px;'>Sign In</button>
        </form>
        <a href='/register' class='btn' style='display:block; width:100%; text-align:center; margin-top:12px; padding:14px; background:rgba(255,255,255,0.06); color:#cbd5e1; text-decoration:none; border-radius:12px; box-sizing:border-box;'>← Go back to Register</a>
    </div></body></html>"""


@app.get("/portal/logout")
def handle_member_logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="farmer_session")
    return response


@app.post("/portal/approve-node")
async def handle_node_approval(target_phone: str = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user: raise HTTPException(status_code=401, detail="Unauthorized session Access")
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("UPDATE farmers SET status = 'Approved' WHERE phone = ? AND lga = ?",
                           (clean_phone(target_phone), current_user['lga']))
        await conn.commit()
    return RedirectResponse(url="/portal/feed", status_code=303)


@app.post("/portal/sensors/submit")
async def submit_soil_reading(
    moisture: float = Form(...),
    ph: float = Form(...),
    current_user=Depends(get_current_farmer)
):
    """Record a soil moisture + pH reading (manual entry or IoT device)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Basic sanity bounds
    moisture = max(0.0, min(100.0, float(moisture)))
    ph = max(0.0, min(14.0, float(ph)))

    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            """INSERT INTO sensor_readings (farmer_phone, lga, moisture, ph, source)
               VALUES (?, ?, ?, ?, 'manual')""",
            (current_user["phone"], current_user["lga"], moisture, ph)
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=incidents&soil_saved=1", status_code=303)


@app.post("/portal/checkin")
async def farmer_checkin(current_user=Depends(get_current_farmer)):
    """Daily 'I'm OK' check-in — awards XP once per day."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        # Only one XP award per calendar day
        async with conn.execute("""
            SELECT id FROM checkins
            WHERE farmer_phone = ? AND date(timestamp) = date('now', 'localtime')
            LIMIT 1
        """, (current_user["phone"],)) as cur:
            already = await cur.fetchone()
        await conn.execute(
            "INSERT INTO checkins (farmer_phone, lga) VALUES (?, ?)",
            (current_user["phone"], current_user["lga"])
        )
        if not already:
            await conn.execute(
                "UPDATE farmers SET xp = xp + ? WHERE phone = ?",
                (CHECKIN_XP, current_user["phone"])
            )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=community", status_code=303)


@app.post("/portal/shoutout")
async def post_shoutout(request: Request, current_user=Depends(get_current_farmer)):
    """Create a celebration card for the signed-in farmer's LGA."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    form = await request.form()
    msg = sanitize(str(form.get("message") or ""))[:MAX_SHOUTOUT_LEN]
    if not msg:
        return RedirectResponse(url="/portal/feed?active_tab=shoutouts#shoutout-form", status_code=303)
    category = str(form.get("category") or "Other")
    if category not in SHOUTOUT_CATEGORIES:
        raise HTTPException(status_code=400, detail="Choose a valid shout-out occasion.")
    template_key = str(form.get("template_key") or "garden")
    if template_key not in SHOUTOUT_TEMPLATES:
        raise HTTPException(status_code=400, detail="Choose a valid celebration design.")
    recipient = sanitize(str(form.get("recipient") or ""))[:60]
    image_path = None
    upload = form.get("photo")
    if hasattr(upload, "read") and getattr(upload, "filename", ""):
        raw = await upload.read(MAX_UPLOAD_SIZE + 1)
        if len(raw) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=413, detail="Celebration photos must be 15 MB or smaller.")
        if not raw:
            raise HTTPException(status_code=400, detail="The selected photo is empty.")
        try:
            import io
            from PIL import Image, ImageOps
            with Image.open(io.BytesIO(raw)) as source_image:
                if source_image.width * source_image.height > 25_000_000:
                    raise HTTPException(status_code=400, detail="Choose an image smaller than 25 megapixels.")
                from PIL import ImageFilter
                portrait = ImageOps.exif_transpose(source_image).convert("RGB")
                image = ImageOps.fit(portrait, (480, 600)).filter(ImageFilter.GaussianBlur(24))
                image = Image.blend(image, Image.new("RGB", image.size, "#14202f"), 0.3)
                foreground = ImageOps.contain(portrait, (444, 564))
                image.paste(
                    foreground,
                    ((image.width - foreground.width) // 2, (image.height - foreground.height) // 2)
                )
                filename = f"shoutout_{secrets.token_hex(16)}.jpg"
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail="The uploaded file must be a valid image.") from exc
        try:
            image.save(os.path.join(MEDIA_DIR, filename), "JPEG", quality=82, optimize=True)
            image_path = filename
        except OSError as exc:
            raise HTTPException(status_code=500, detail="The celebration photo could not be saved.") from exc
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.execute(
            """INSERT INTO shoutouts
               (farmer_phone, farmer_name, lga, message, category, recipient, template_key, image_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (current_user["phone"], current_user["name"], current_user["lga"],
             msg, category, recipient, template_key, image_path)
        )
        shoutout_id = cursor.lastrowid
        await conn.execute(
            "UPDATE farmers SET xp = xp + ? WHERE phone = ?",
            (SHOUTOUT_XP, current_user["phone"])
        )
        await conn.commit()
    return RedirectResponse(
        url=f"/portal/feed?active_tab=shoutouts&shoutout_posted={shoutout_id}#shoutout-{shoutout_id}",
        status_code=303,
    )


@app.post("/portal/shoutout/remove-photo")
async def remove_shoutout_photo(
    shoutout_id: int = Form(...),
    current_user=Depends(get_current_farmer),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT image_path FROM shoutouts WHERE id = ? AND farmer_phone = ?",
            (shoutout_id, current_user["phone"]),
        ) as cursor:
            shoutout = await cursor.fetchone()
        if not shoutout:
            raise HTTPException(status_code=404, detail="Shout-out not found.")
        stored_path = shoutout["image_path"]
        if stored_path:
            filename = os.path.basename(str(stored_path))
            photo_path = os.path.join(MEDIA_DIR, filename)
            try:
                if os.path.isfile(photo_path):
                    os.remove(photo_path)
            except OSError as exc:
                raise HTTPException(status_code=500, detail="The photo could not be removed.") from exc
            await conn.execute(
                "UPDATE shoutouts SET image_path = NULL WHERE id = ? AND farmer_phone = ?",
                (shoutout_id, current_user["phone"]),
            )
            await conn.commit()
    return RedirectResponse(
        url=f"/portal/feed?active_tab=shoutouts&shoutout_posted={shoutout_id}#shoutout-{shoutout_id}",
        status_code=303,
    )


@app.post("/portal/shoutout/delete")
async def delete_shoutout(
    shoutout_id: int = Form(...),
    current_user=Depends(get_current_farmer),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT image_path FROM shoutouts WHERE id = ? AND farmer_phone = ?",
            (shoutout_id, current_user["phone"]),
        ) as cursor:
            shoutout = await cursor.fetchone()
        if not shoutout:
            raise HTTPException(status_code=404, detail="Shout-out not found.")
        stored_path = shoutout["image_path"]
        if stored_path:
            try:
                remove_social_image(str(stored_path))
            except OSError as exc:
                raise HTTPException(
                    status_code=500, detail="The shout-out photo could not be removed."
                ) from exc
        await conn.execute(
            "DELETE FROM shoutouts WHERE id = ? AND farmer_phone = ?",
            (shoutout_id, current_user["phone"]),
        )
        await conn.commit()
    return RedirectResponse(
        url="/portal/feed?active_tab=shoutouts#shoutout-list",
        status_code=303,
    )


@app.post("/portal/status/post")
async def post_status(
    content: str = Form(""),
    photo: Optional[UploadFile] = File(None),
    current_user=Depends(get_current_farmer),
):
    """Post a normal status update."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    text = sanitize(content)[:280]
    has_photo = bool(photo and photo.filename)
    if not text and not has_photo:
        return RedirectResponse(url="/portal/feed?active_tab=community", status_code=303)
    photo_path = None
    if has_photo:
        photo_path = save_social_image(await optimize_social_image(photo, "status"), "status")
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            cursor = await conn.execute(
                """INSERT INTO statuses (author_phone, author_name, content, image_path)
                   VALUES (?, ?, ?, ?)""",
                (current_user["phone"], current_user["name"], text, photo_path)
            )
            status_id = cursor.lastrowid
            await conn.commit()
    except Exception:
        remove_social_image(photo_path)
        raise
    return RedirectResponse(
        url=f"/portal/feed?active_tab=community&status_posted={status_id}#status-{status_id}",
        status_code=303,
    )


@app.post("/portal/status/like")
async def like_status(status_id: int = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        if not await can_view_status(conn, status_id, current_user["phone"]):
            raise HTTPException(status_code=404, detail="Status not found")
        try:
            await conn.execute(
                "INSERT INTO status_likes (status_id, user_phone) VALUES (?, ?)",
                (status_id, current_user["phone"])
            )
            await conn.commit()
        except Exception:
            pass  # already liked
    return RedirectResponse(url="/portal/feed?active_tab=community", status_code=303)


@app.post("/portal/status/comment")
async def comment_status(status_id: int = Form(...), text: str = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    clean = sanitize(text)[:200]
    if clean:
        async with aiosqlite.connect(DB_FILE) as conn:
            if not await can_view_status(conn, status_id, current_user["phone"]):
                raise HTTPException(status_code=404, detail="Status not found")
            await conn.execute(
                "INSERT INTO status_comments (status_id, author_phone, author_name, text) VALUES (?, ?, ?, ?)",
                (status_id, current_user["phone"], current_user["name"], clean)
            )
            await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=community", status_code=303)


@app.post("/portal/status/repost")
async def repost_status(status_id: int = Form(...), current_user=Depends(get_current_farmer)):
    """Repost a status so the user's friends can see it."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        if not await can_view_status(conn, status_id, current_user["phone"]):
            raise HTTPException(status_code=404, detail="Status not found")
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT content, author_name FROM statuses WHERE id = ?", (status_id,)) as c:
            orig = await c.fetchone()
        if orig:
            repost_text = f"🔁 {orig['author_name']}: {orig['content']}"
            await conn.execute(
                "INSERT INTO statuses (author_phone, author_name, content, original_id) VALUES (?, ?, ?, ?)",
                (current_user["phone"], current_user["name"], repost_text[:280], status_id)
            )
            await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=community", status_code=303)


@app.post("/portal/status/hide")
async def hide_status(status_id: int = Form(...), current_user=Depends(get_current_farmer)):
    """Hide a post from the current user's feed."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        if not await can_view_status(conn, status_id, current_user["phone"]):
            raise HTTPException(status_code=404, detail="Status not found")
        try:
            await conn.execute(
                "INSERT INTO status_hides (status_id, user_phone) VALUES (?, ?)",
                (status_id, current_user["phone"])
            )
            await conn.commit()
        except Exception:
            pass
    return RedirectResponse(url="/portal/feed?active_tab=community", status_code=303)


@app.post("/portal/status/report")
async def report_status(status_id: int = Form(...), reason: str = Form(...), current_user=Depends(get_current_farmer)):
    """Report a post for moderation."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    clean_reason = reason.strip()
    if len(clean_reason) < 5 or len(clean_reason) > 500:
        raise HTTPException(status_code=422, detail="Please provide a reason (5–500 characters).")
    async with aiosqlite.connect(DB_FILE) as conn:
        if not await can_view_status(conn, status_id, current_user["phone"]):
            raise HTTPException(status_code=404, detail="Status not found")
        await conn.execute(
            """INSERT OR IGNORE INTO status_reports
               (status_id, reporter_phone, reason) VALUES (?, ?, ?)""",
            (status_id, current_user["phone"], sanitize(clean_reason)[:500])
        )
        await conn.commit()
    return RedirectResponse(
        url="/portal/feed?active_tab=community&report_sent=1",
        status_code=303,
    )


@app.post("/portal/market/post")
async def post_farm_product(request: Request, current_user=Depends(get_current_farmer)):
    """Post a farm product listing (up to 5 photos). Always saves a browser-readable JPEG."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    form = await request.form()
    title_c = sanitize(str(form.get("title") or ""))[:MAX_PRODUCT_TITLE]
    if not title_c:
        return RedirectResponse(url="/portal/feed?active_tab=farm_market&post_err=title", status_code=303)
    desc_c = sanitize(str(form.get("description") or ""))[:MAX_PRODUCT_DESC]
    price_c = sanitize(str(form.get("price") or ""))[:40]
    category = str(form.get("category") or "General")
    contact_phone = str(form.get("contact_phone") or "")
    animal_type = str(form.get("animal_type") or "")
    animal_sex = str(form.get("animal_sex") or "")
    cow_breed = str(form.get("cow_breed") or "")
    breed_custom = str(form.get("breed_custom") or "")
    exotic_type = str(form.get("exotic_type") or "")
    cat = sanitize(category)[:30] if category else "General"
    if cat == "Livestock" and animal_type:
        bits = [sanitize(animal_type)]
        if animal_sex:
            bits.append(sanitize(animal_sex))
        if animal_type == "Cow":
            breed = sanitize(breed_custom) if cow_breed == "Other" and breed_custom else sanitize(cow_breed)
            if breed:
                bits.append(breed)
        if animal_type == "Exotic Pets" and exotic_type:
            bits.append(sanitize(exotic_type))
        extra = " · ".join(bits)
        desc_c = (extra + (" — " + desc_c if desc_c else ""))[:MAX_PRODUCT_DESC]
    contact = normalize_nigerian_mobile(contact_phone) or current_user["phone"]

    photo_paths = []
    uploads = form.getlist("photos")
    print(f"Market post photos received: {len(uploads)}")
    for photo in uploads[:5]:
        if not hasattr(photo, "read"):
            print(f"Skip non-file part: {type(photo)}")
            continue
        try:
            raw = await photo.read()
            print(f"Photo bytes: {len(raw) if raw else 0} name={getattr(photo, 'filename', '')}")
            if not raw:
                continue
            if len(raw) > MAX_UPLOAD_SIZE:
                print("Photo too large, skipped")
                continue
            fname = f"prod_{hashlib.md5(os.urandom(16)).hexdigest()}.jpg"
            dest = os.path.join(MEDIA_DIR, fname)
            saved = False
            try:
                from PIL import Image
                import io
                try:
                    import pillow_heif
                    pillow_heif.register_heif_opener()
                except Exception:
                    pass
                img = Image.open(io.BytesIO(raw))
                img = img.convert("RGB")
                img.thumbnail((800, 800))
                img.save(dest, "JPEG", quality=70)
                saved = True
            except Exception as conv_err:
                print(f"Convert failed, saving raw: {conv_err}")
                with open(dest, "wb") as f:
                    f.write(raw)
                saved = True
            if saved and os.path.exists(dest):
                photo_paths.append(fname)
                print(f"Saved photo: {dest}")
        except Exception as e:
            print(f"Photo save error: {e}")
            continue

    photo_path = ",".join(photo_paths) if photo_paths else None
    print(f"photo_path stored: {photo_path}")
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            """INSERT INTO farm_products
               (farmer_phone, farmer_name, lga, title, description, price, contact_phone, category, photo_path, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending')""",
            (current_user["phone"], current_user["name"], current_user["lga"],
             title_c, desc_c, price_c, contact, cat, photo_path)
        )
        await conn.execute(
            "UPDATE farmers SET xp = xp + ? WHERE phone = ?",
            (PRODUCT_POST_XP, current_user["phone"])
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=farm_market&posted=1", status_code=303)


@app.post("/portal/market/edit")
async def edit_farm_product(request: Request, current_user=Depends(get_current_farmer)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    form = await request.form()
    try:
        product_id = int(str(form.get("product_id") or ""))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid listing")

    title = sanitize(str(form.get("title") or ""))[:MAX_PRODUCT_TITLE]
    if not title:
        return JSONResponse({"detail": "Please enter a product title."}, status_code=400)
    description = sanitize(str(form.get("description") or ""))[:MAX_PRODUCT_DESC]
    price = sanitize(str(form.get("price") or ""))[:40]
    category = sanitize(str(form.get("category") or "General"))[:30]
    if category not in PRODUCT_CATEGORIES and category != "General":
        return JSONResponse({"detail": "Please choose a valid category."}, status_code=400)
    contact = normalize_nigerian_mobile(str(form.get("contact_phone") or "")) or current_user["phone"]

    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT photo_path FROM farm_products WHERE id = ? AND farmer_phone = ?",
            (product_id, current_user["phone"])
        ) as cursor:
            product = await cursor.fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="Listing not found or you do not own it.")

        photo_path = product["photo_path"]
        if str(form.get("remove_photos") or "") == "1":
            photo_path = None
        else:
            new_photos = []
            for photo in form.getlist("photos")[:5]:
                if not hasattr(photo, "read") or not getattr(photo, "filename", ""):
                    continue
                raw = await photo.read()
                if not raw:
                    continue
                if len(raw) > MAX_UPLOAD_SIZE:
                    return JSONResponse({"detail": "Each photo must be within the upload size limit."}, status_code=400)
                fname = f"prod_{hashlib.md5(os.urandom(16)).hexdigest()}.jpg"
                dest = os.path.join(MEDIA_DIR, fname)
                try:
                    from PIL import Image
                    import io
                    try:
                        import pillow_heif
                        pillow_heif.register_heif_opener()
                    except ImportError:
                        pass
                    with Image.open(io.BytesIO(raw)) as image:
                        converted = image.convert("RGB")
                        converted.thumbnail((800, 800))
                        converted.save(dest, "JPEG", quality=70)
                except Exception:
                    with open(dest, "wb") as image_file:
                        image_file.write(raw)
                new_photos.append(fname)
            if new_photos:
                photo_path = ",".join(new_photos)

        await conn.execute(
            """UPDATE farm_products
               SET title = ?, description = ?, price = ?, contact_phone = ?,
                   category = ?, photo_path = ?, status = 'Pending'
               WHERE id = ? AND farmer_phone = ?""",
            (title, description, price, contact, category, photo_path, product_id, current_user["phone"])
        )
        await conn.commit()
    return JSONResponse({
        "product_id": product_id,
        "message": "Listing updated and sent for admin approval."
    })


@app.post("/portal/market/interest")
async def express_interest(
    product_id: int = Form(...),
    seller_phone: str = Form(...),
    interest_photo: Optional[UploadFile] = File(None),
    current_user=Depends(get_current_farmer)
):
    """Buyer marks interest, optionally uploads a photo, and auto-sends a message to the seller."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if seller_phone == current_user["phone"]:
        return RedirectResponse(url="/portal/feed?active_tab=market", status_code=303)

    photo_note = ""
    if interest_photo and interest_photo.filename:
        content = await interest_photo.read()
        if len(content) <= MAX_UPLOAD_SIZE:
            ext = os.path.splitext(interest_photo.filename)[1].lower() or ".jpg"
            fname = f"interest_{current_user['phone']}_{product_id}_{hashlib.md5(os.urandom(8)).hexdigest()[:8]}{ext}"
            path = os.path.join(MEDIA_DIR, fname)
            with open(path, "wb") as f:
                f.write(content)
            photo_note = f" (photo attached: /media/{fname})"

    listing_name = "your listing"
    listing_price = ""
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT title, price FROM farm_products WHERE id = ?", (product_id,)) as cur:
            prod = await cur.fetchone()
            if prod:
                listing_name = prod["title"] or listing_name
                listing_price = prod["price"] or ""
        price_bit = f" ({listing_price})" if listing_price else ""
        msg = f"I am interested in your listing: {listing_name}{price_bit}.{photo_note}"
        await conn.execute(
            "INSERT INTO direct_messages (sender_phone, receiver_phone, body) VALUES (?, ?, ?)",
            (current_user["phone"], seller_phone, msg)
        )
        await conn.commit()
    return RedirectResponse(url=f"/portal/feed?active_tab=market&interested=1", status_code=303)


@app.post("/portal/market/sold")
async def mark_product_sold(
    product_id: int = Form(...),
    current_user=Depends(get_current_farmer)
):
    """Mark own listing as sold."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "UPDATE farm_products SET status = 'Sold' WHERE id = ? AND farmer_phone = ?",
            (product_id, current_user["phone"])
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=market", status_code=303)


@app.post("/portal/market/remove")
async def remove_farm_product(
    product_id: int = Form(...),
    current_user=Depends(get_current_farmer)
):
    """Remove own product listing."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "UPDATE farm_products SET status = 'Removed' WHERE id = ? AND farmer_phone = ?",
            (product_id, current_user["phone"])
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=market", status_code=303)


def parse_spotify_path(url: str) -> Optional[str]:
    """Extract embed path (e.g. playlist/ID) from a Spotify URL or URI."""
    if not url:
        return None
    url = url.strip()
    import re
    m = re.search(r"open\.spotify\.com/(playlist|album|track|episode|show)/([a-zA-Z0-9]+)", url)
    if not m:
        m = re.search(r"spotify:(playlist|album|track|episode|show):([a-zA-Z0-9]+)", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return None


@app.post("/portal/spotify/save")
async def save_spotify_link(
    title: str = Form(...),
    url: str = Form(...),
    current_user=Depends(get_current_farmer)
):
    """Save a personal Spotify playlist/album/track link."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    title_c = sanitize(title)[:60]
    path = parse_spotify_path(url)
    if not title_c or not path:
        return RedirectResponse(url="/portal/feed?active_tab=incidents&spotify_err=1", status_code=303)
    async with aiosqlite.connect(DB_FILE) as conn:
        # Limit to 20 saved links per farmer
        async with conn.execute(
            "SELECT COUNT(*) FROM spotify_links WHERE farmer_phone = ?",
            (current_user["phone"],)
        ) as cur:
            count = (await cur.fetchone())[0]
        if count >= 20:
            return RedirectResponse(url="/portal/feed?active_tab=incidents&spotify_err=limit", status_code=303)
        await conn.execute(
            "INSERT INTO spotify_links (farmer_phone, title, embed_path) VALUES (?, ?, ?)",
            (current_user["phone"], title_c, path)
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=incidents", status_code=303)


@app.post("/portal/spotify/delete")
async def delete_spotify_link(
    link_id: int = Form(...),
    current_user=Depends(get_current_farmer)
):
    """Remove a saved Spotify link."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "DELETE FROM spotify_links WHERE id = ? AND farmer_phone = ?",
            (link_id, current_user["phone"])
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=incidents", status_code=303)


@app.post("/portal/games/score")
async def submit_game_score(
    game_name: str = Form(...),
    score: int = Form(...),
    current_user=Depends(get_current_farmer)
):
    """Record a mini-game score and award XP for good results."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    game_name = sanitize(game_name)[:40]
    score = max(0, min(1000, int(score)))
    xp = 0
    if game_name == "dart" and score >= 50:
        xp = DART_WIN_XP
    elif game_name == "hunt" and score >= 3:
        xp = HUNT_WIN_XP
    elif score > 0:
        xp = min(5, score // 10)

    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "INSERT INTO game_scores (farmer_phone, game_name, score, xp_earned) VALUES (?, ?, ?, ?)",
            (current_user["phone"], game_name, score, xp)
        )
        if xp > 0:
            await conn.execute(
                "UPDATE farmers SET xp = xp + ? WHERE phone = ?",
                (xp, current_user["phone"])
            )
        await conn.commit()
        async with conn.execute("SELECT xp FROM farmers WHERE phone = ?", (current_user["phone"],)) as c:
            new_xp = (await c.fetchone())[0]
    return {"xp_earned": xp, "balance": new_xp}


@app.post("/portal/flag-node")
async def handle_flag_node(
    target_phone: str = Form(...),
    reason: str = Form(...),
    current_user=Depends(get_current_farmer),
):
    """Record a reasoned farmer report for administrator review."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized session")
    clean_t = clean_phone(target_phone)
    clean_reason = reason.strip()
    if not clean_t:
        raise HTTPException(status_code=400, detail="Choose another farmer to report.")
    if len(clean_reason) < 5 or len(clean_reason) > 500:
        raise HTTPException(status_code=422, detail="Please provide a reason (5–500 characters).")
    async with aiosqlite.connect(DB_FILE) as conn:
        target_aliases = phone_aliases(clean_t)
        target_placeholders = ",".join("?" for _ in target_aliases)
        async with conn.execute(
            f"SELECT phone FROM farmers WHERE phone IN ({target_placeholders}) AND COALESCE(is_demo, 0) = 0",
            tuple(target_aliases),
        ) as cursor:
            target = await cursor.fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Farmer not found.")
        clean_t = target[0]
        if clean_t in phone_aliases(current_user["phone"]):
            raise HTTPException(status_code=400, detail="Choose another farmer to report.")
        await conn.execute(
            """INSERT OR IGNORE INTO farmer_reports
               (reporter_phone, target_phone, reason) VALUES (?, ?, ?)""",
            (current_user["phone"], clean_t, clean_reason[:500]),
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?report_sent=1", status_code=303)


@app.post("/portal/block-node")
async def handle_block_node(target_phone: str = Form(...), current_user=Depends(get_current_farmer)):
    """Place a peer in the current user's Guardroom."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    clean_t = clean_phone(target_phone)
    if clean_t in phone_aliases(current_user["phone"]):
        raise HTTPException(status_code=400, detail="You cannot block yourself.")
    async with aiosqlite.connect(DB_FILE) as conn:
        current_guard = await guard_status(conn, current_user["phone"], clean_t)
        if current_guard == "expelled":
            return RedirectResponse(
                url="/portal/guardroom?notice=expelled",
                status_code=303,
            )
        if current_guard == "blocked":
            return RedirectResponse(
                url="/portal/guardroom?notice=sent",
                status_code=303,
            )
        target_aliases = phone_aliases(clean_t)
        target_placeholders = ",".join("?" for _ in target_aliases)
        async with conn.execute(
            f"SELECT phone FROM farmers WHERE phone IN ({target_placeholders}) AND COALESCE(is_demo, 0) = 0",
            tuple(target_aliases),
        ) as cursor:
            target = await cursor.fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Farmer not found.")
        clean_t = target[0]
        await conn.execute(
            """INSERT INTO blocked_nodes (blocker_phone, blocked_phone, guard_status, created_at)
               VALUES (?, ?, 'blocked', CURRENT_TIMESTAMP)
               ON CONFLICT(blocker_phone, blocked_phone) DO NOTHING""",
            (current_user["phone"], clean_t)
        )
        await conn.commit()
    return RedirectResponse(url="/portal/guardroom?notice=sent", status_code=303)


@app.post("/portal/unblock-node")
async def handle_unblock_node(target_phone: str = Form(...), current_user=Depends(get_current_farmer)):
    """Release a peer from the current user's Guardroom."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    clean_t = clean_phone(target_phone)
    blocker_aliases = phone_aliases(current_user["phone"])
    target_aliases = phone_aliases(clean_t)
    blocker_placeholders = ",".join("?" for _ in blocker_aliases)
    target_placeholders = ",".join("?" for _ in target_aliases)
    async with aiosqlite.connect(DB_FILE) as conn:
        if await guard_status(conn, current_user["phone"], clean_t) == "expelled":
            raise HTTPException(
                status_code=409,
                detail="An expelled farmer cannot be released from the Guardroom.",
            )
        await conn.execute(
            f"""DELETE FROM blocked_nodes
                WHERE blocker_phone IN ({blocker_placeholders})
                  AND blocked_phone IN ({target_placeholders})
                  AND guard_status = 'blocked'""",
            tuple(blocker_aliases) + tuple(target_aliases),
        )
        await conn.commit()
    return RedirectResponse(url="/portal/guardroom?notice=released", status_code=303)


@app.post("/portal/guardroom/expel")
async def expel_guardroom_farmer(
    target_phone: str = Form(...),
    current_user=Depends(get_current_farmer),
):
    """Permanently remove both sides of a farmer pair from each other's network."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    clean_t = clean_phone(target_phone)
    if not clean_t or clean_t in phone_aliases(current_user["phone"]):
        raise HTTPException(status_code=400, detail="Choose another farmer to expel.")
    blocker_aliases = phone_aliases(current_user["phone"])
    target_aliases = phone_aliases(clean_t)
    blocker_placeholders = ",".join("?" for _ in blocker_aliases)
    target_placeholders = ",".join("?" for _ in target_aliases)
    async with aiosqlite.connect(DB_FILE) as conn:
        async with conn.execute(
            f"""SELECT 1 FROM blocked_nodes
                WHERE blocker_phone IN ({blocker_placeholders})
                  AND blocked_phone IN ({target_placeholders})""",
            tuple(blocker_aliases) + tuple(target_aliases),
        ) as cursor:
            is_in_guardroom = await cursor.fetchone()
        if not is_in_guardroom:
            raise HTTPException(status_code=404, detail="Farmer not found in your Guardroom.")
        await conn.execute(
            f"""UPDATE blocked_nodes SET guard_status = 'expelled'
                WHERE blocker_phone IN ({blocker_placeholders})
                  AND blocked_phone IN ({target_placeholders})""",
            tuple(blocker_aliases) + tuple(target_aliases),
        )
        await conn.execute(
            """DELETE FROM friendships
               WHERE (requester_phone = ? AND receiver_phone = ?)
                  OR (requester_phone = ? AND receiver_phone = ?)""",
            (current_user["phone"], clean_t, clean_t, current_user["phone"]),
        )
        await conn.commit()
    return RedirectResponse(url="/portal/guardroom?notice=expelled", status_code=303)


@app.get("/portal/guardroom", response_class=HTMLResponse)
async def guardroom_page(
    notice: Optional[str] = Query(None),
    current_user=Depends(get_current_farmer),
):
    if not current_user:
        return RedirectResponse(url="/portal/login", status_code=303)
    owner_aliases = phone_aliases(current_user["phone"])
    owner_placeholders = ",".join("?" for _ in owner_aliases)
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            f"""SELECT bn.blocked_phone, bn.guard_status, bn.created_at, f.name
                FROM blocked_nodes bn
                LEFT JOIN farmers f ON f.phone = bn.blocked_phone
                WHERE bn.blocker_phone IN ({owner_placeholders})
               ORDER BY CASE bn.guard_status WHEN 'expelled' THEN 1 ELSE 0 END,
                        bn.id DESC""",
            tuple(owner_aliases),
        ) as cursor:
            guarded_farmers = await cursor.fetchall()
    notice_messages = {
        "sent": "This farmer has been sent to your Guardroom. They are hidden from each other while held here.",
        "released": "Farmer released. If you were friends before, they are back in your friends list.",
        "expelled": "Farmer expelled. Both accounts are removed from each other's view and cannot reconnect.",
    }
    notice_html = ""
    if notice in notice_messages:
        notice_html = (
            '<div style="padding:12px 16px;margin:0 0 16px;background:rgba(110,231,183,.12);'
            'border:1px solid rgba(110,231,183,.3);border-radius:12px;color:#a7f3d0;">'
            + html.escape(notice_messages[notice])
            + "</div>"
        )
    rows = []
    for farmer in guarded_farmers:
        phone_value = html.escape(str(farmer["blocked_phone"]), quote=True)
        name = html.escape(farmer["name"] or "Former farmer")
        status = farmer["guard_status"] or "blocked"
        if status == "expelled":
            action_html = '<span style="color:#fca5a5;font-weight:800;">🌲 Expelled permanently</span>'
        else:
            action_html = f"""
                <form action="/portal/unblock-node" method="post" style="margin:0;">
                    <input type="hidden" name="target_phone" value="{phone_value}">
                    <button class="btn btn-emerald" type="submit">Release to friends</button>
                </form>
                <form action="/portal/guardroom/expel" method="post" style="margin:0;"
                      onsubmit="return confirm('Expel this person permanently? Neither of you will be able to find or reconnect with the other. This cannot be undone.');">
                    <input type="hidden" name="target_phone" value="{phone_value}">
                    <button class="btn btn-danger" type="submit">Expel to the forest</button>
                </form>"""
        rows.append(f"""
            <article style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;
                padding:16px;margin:10px 0;background:rgba(10,18,16,.82);border:1px solid rgba(167,211,181,.24);border-radius:14px;">
                <div>
                    <div style="font-weight:800;color:#f0fdf4;">{name}</div>
                    <div style="font-size:12px;color:#a7c4b5;margin-top:4px;">{html.escape(str(farmer["created_at"]))}</div>
                    <div style="font-size:12px;color:#d6d3d1;margin-top:5px;">{"Held in your Guardroom" if status == "blocked" else "Expelled permanently"}</div>
                </div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;">{action_html}</div>
            </article>""")
    entries = "".join(rows) or (
        '<p style="color:#cbd5e1;text-align:center;padding:20px;">Your Guardroom is empty. '
        'People you block will appear here.</p>'
    )
    return HTMLResponse(f"""<!doctype html>
        <html><head><meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Guardroom | Olode</title><style>{UPGRADED_CSS}
        .guardroom {{ max-width:860px;margin:24px auto;padding:24px;border:1px solid rgba(167,211,181,.28);
            border-radius:20px;background-color:rgba(8,20,15,.94);
            background-image:linear-gradient(rgba(8,20,15,.91),rgba(8,20,15,.94)),
            url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180' viewBox='0 0 180 180'%3E%3Cg fill='none' stroke='%23a7d3b5' stroke-width='3' opacity='.32'%3E%3Cpath d='M18 0v180M54 0v180M90 0v180M126 0v180M162 0v180M0 18h180M0 54h180M0 90h180M0 126h180M0 162h180'/%3E%3C/g%3E%3C/svg%3E");box-shadow:0 18px 48px rgba(0,0,0,.35); }}
        </style></head><body><main class="guardroom">
            <a href="/portal/feed?active_tab=friends" class="btn" style="display:inline-block;text-decoration:none;">← Back to Friends & Requests</a>
            <h1 style="color:#d1fae5;margin-bottom:6px;">🛡️ Guardroom</h1>
            <p style="color:#cbd5e1;line-height:1.55;">Blocked people are held here and cannot find or contact you. Release someone to restore your previous friendship, or permanently expel them. Expulsion also removes them from your view and cannot be undone.</p>
            {notice_html}{entries}
        </main></body></html>""")


@app.post("/portal/messages/report")
async def report_direct_message(
    message_id: int = Form(...),
    return_phone: Optional[str] = Form(None),
    current_user=Depends(get_current_farmer)
):
    """Report a message. Multiple unique reports auto-flag the sender."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        # Record the report (unique per reporter + message)
        await conn.execute(
            "INSERT OR IGNORE INTO message_reports (message_id, reporter_phone) VALUES (?, ?)",
            (message_id, current_user["phone"])
        )
        # Count unique reporters for this message's sender
        async with conn.execute("""
            SELECT dm.sender_phone, COUNT(DISTINCT mr.reporter_phone) as report_count
            FROM direct_messages dm
            JOIN message_reports mr ON mr.message_id = dm.id
            WHERE dm.id = ?
            GROUP BY dm.sender_phone
        """, (message_id,)) as cur:
            row = await cur.fetchone()

        if row and row["report_count"] >= REPORTS_TO_AUTO_FLAG:
            await conn.execute(
                "UPDATE farmers SET status = ? WHERE phone = ?",
                (STATUS_REPORTED, row["sender_phone"])
            )
        await conn.commit()

    redirect = "/portal/feed?active_tab=messages"
    if return_phone:
        redirect += f"&search_phone={clean_phone(return_phone)}"
    return RedirectResponse(url=redirect, status_code=303)


@app.post("/portal/messages/send")
async def send_direct_message(
    receiver_phone: str = Form(...),
    body: str = Form(...),
    current_user=Depends(get_current_farmer)
):
    """Send a direct message with safety checks (LGA, block, rate limits, length)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    clean_r = clean_phone(receiver_phone)
    msg_body = sanitize(body)
    redirect_url = f"/portal/chat?with={clean_r}"

    if not msg_body:
        return RedirectResponse(url=redirect_url, status_code=303)

    if len(msg_body) > MAX_MESSAGE_LENGTH:
        return RedirectResponse(url=redirect_url + "&error=length", status_code=303)

    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row

        # Resolve peer (with Nigerian format fallback)
        async with conn.execute("SELECT phone, lga, status FROM farmers WHERE phone = ? AND COALESCE(is_demo, 0) = 0", (clean_r,)) as cur:
            peer = await cur.fetchone()
        if not peer:
            if clean_r.startswith("0") and len(clean_r) == 11:
                alt = "234" + clean_r[1:]
            elif clean_r.startswith("234") and len(clean_r) == 13:
                alt = "0" + clean_r[3:]
            else:
                alt = None
            if alt:
                async with conn.execute("SELECT phone, lga, status FROM farmers WHERE phone = ? AND COALESCE(is_demo, 0) = 0", (alt,)) as cur:
                    peer = await cur.fetchone()
                if peer:
                    clean_r = peer["phone"]
                    redirect_url = f"/portal/chat?with={clean_r}"

        if not peer:
            return RedirectResponse(url=redirect_url + "&error=notfound", status_code=303)

        # Allow messaging if same LGA OR they are accepted friends
        same_lga = peer["lga"] == current_user["lga"]
        is_friend = False
        async with conn.execute("""
            SELECT 1 FROM friendships
            WHERE status = 'accepted'
              AND ((requester_phone = ? AND receiver_phone = ?)
                OR (requester_phone = ? AND receiver_phone = ?))
        """, (current_user["phone"], clean_r, clean_r, current_user["phone"])) as fcur:
            if await fcur.fetchone():
                is_friend = True
        # Allow messaging if same LGA, friends, OR the receiver has an active product (buyer-seller)
        has_product = False
        async with conn.execute(
            "SELECT 1 FROM farm_products WHERE farmer_phone = ? AND status = 'Active' LIMIT 1",
            (clean_r,)
        ) as pcur:
            if await pcur.fetchone():
                has_product = True
        if not same_lga and not is_friend and not has_product:
            return RedirectResponse(url=redirect_url + "&error=lga", status_code=303)

        if await guard_status(conn, current_user["phone"], clean_r):
            return RedirectResponse(url=redirect_url + "&error=blocked", status_code=303)

        # Rate limit: messages to this peer in the last hour
        async with conn.execute("""
            SELECT COUNT(*) as cnt FROM direct_messages
            WHERE sender_phone = ? AND receiver_phone = ?
              AND timestamp > datetime('now', '-1 hour')
        """, (current_user["phone"], clean_r)) as cur:
            hour_count = (await cur.fetchone())["cnt"]
        if hour_count >= MAX_MESSAGES_PER_HOUR_TO_PEER:
            return RedirectResponse(url=redirect_url + "&error=rate_hour", status_code=303)

        # Rate limit: total messages sent today
        async with conn.execute("""
            SELECT COUNT(*) as cnt FROM direct_messages
            WHERE sender_phone = ?
              AND timestamp > datetime('now', '-1 day')
        """, (current_user["phone"],)) as cur:
            day_count = (await cur.fetchone())["cnt"]
        if day_count >= MAX_MESSAGES_PER_DAY:
            return RedirectResponse(url=redirect_url + "&error=rate_day", status_code=303)

        # All checks passed — insert
        await conn.execute(
            "INSERT INTO direct_messages (sender_phone, receiver_phone, body) VALUES (?, ?, ?)",
            (current_user["phone"], clean_r, msg_body)
        )
        await conn.commit()

    return RedirectResponse(url=redirect_url + "&sent=1", status_code=303)


@app.post("/portal/messages/delete")
async def delete_direct_message(
    message_id: int = Form(...),
    return_phone: Optional[str] = Form(None),
    current_user=Depends(get_current_farmer)
):
    """Delete a direct message (only sender or receiver may delete)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "DELETE FROM direct_messages WHERE id = ? AND (sender_phone = ? OR receiver_phone = ?)",
            (message_id, current_user["phone"], current_user["phone"])
        )
        await conn.commit()
    redirect = "/portal/feed?active_tab=messages"
    if return_phone:
        redirect += f"&search_phone={clean_phone(return_phone)}"
    return RedirectResponse(url=redirect, status_code=303)



@app.post("/portal/market/report")
async def report_product(
    product_id: int = Form(...),
    reason: str = Form(""),
    current_user=Depends(get_current_farmer)
):
    """Report a product listing for scam or abuse."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    reason_c = sanitize(reason)[:200]
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO product_reports (product_id, reporter_phone, reason) VALUES (?, ?, ?)",
            (product_id, current_user["phone"], reason_c)
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=market&reported=1", status_code=303)


@app.post("/portal/market/review")
async def review_product(
    product_id: int = Form(...),
    rating: int = Form(...),
    comment: str = Form(""),
    current_user=Depends(get_current_farmer)
):
    """Leave a 1-5 star review on a product."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    rating = max(1, min(5, int(rating)))
    comment_c = sanitize(comment)[:300]
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            """INSERT OR REPLACE INTO product_reviews
               (product_id, reviewer_phone, reviewer_name, rating, comment)
               VALUES (?, ?, ?, ?, ?)""",
            (product_id, current_user["phone"], current_user["name"], rating, comment_c)
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=market", status_code=303)


@app.post("/portal/xp/tick")
async def xp_tick(current_user=Depends(get_current_farmer)):
    """Award a small amount of XP for staying active on the page."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "UPDATE farmers SET xp = xp + ? WHERE phone = ?",
            (AUTO_XP_PER_TICK, current_user["phone"])
        )
        async with conn.execute("SELECT xp FROM farmers WHERE phone = ?", (current_user["phone"],)) as cur:
            row = await cur.fetchone()
            new_xp = row[0] if row else current_user["xp"]
        await conn.commit()
    return {"xp": new_xp}


@app.post("/portal/friend/request")
async def send_friend_request(
    target_phone: str = Form(...),
    current_user=Depends(get_current_farmer)
):
    """Send a friend request to another farmer."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    clean_t = clean_phone(target_phone)
    if clean_t in phone_aliases(current_user["phone"]):
        return RedirectResponse(url="/portal/feed?active_tab=community", status_code=303)
    async with aiosqlite.connect(DB_FILE) as conn:
        if await guard_status(conn, current_user["phone"], clean_t):
            raise HTTPException(
                status_code=403,
                detail="You cannot connect with this farmer because of an active Guardroom restriction.",
            )
        # Only block if already accepted friends. Pending requests do not block new ones.
        async with conn.execute("""
            SELECT status FROM friendships
            WHERE status = 'accepted'
              AND ((requester_phone = ? AND receiver_phone = ?)
                OR (requester_phone = ? AND receiver_phone = ?))
        """, (current_user["phone"], clean_t, clean_t, current_user["phone"])) as cur:
            already_friends = await cur.fetchone()
        if not already_friends:
            # Allow multiple pending requests to different people.
            # If a pending request to this person already exists, INSERT OR IGNORE keeps it.
            await conn.execute(
                "INSERT OR IGNORE INTO friendships (requester_phone, receiver_phone, status) VALUES (?, ?, 'pending')",
                (current_user["phone"], clean_t)
            )
            await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=community&friend_sent=1", status_code=303)


@app.post("/portal/friend/accept")
async def accept_friend_request(
    requester_phone: str = Form(...),
    current_user=Depends(get_current_farmer)
):
    """Accept a friend request."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    clean_r = clean_phone(requester_phone)
    async with aiosqlite.connect(DB_FILE) as conn:
        if await guard_status(conn, current_user["phone"], clean_r):
            raise HTTPException(
                status_code=403,
                detail="This farmer cannot be added while a Guardroom restriction is active.",
            )
        await conn.execute(
            "UPDATE friendships SET status = 'accepted' WHERE requester_phone = ? AND receiver_phone = ? AND status = 'pending'",
            (clean_r, current_user["phone"])
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=community", status_code=303)


@app.post("/portal/friend/reject")
async def reject_friend_request(
    requester_phone: str = Form(...),
    current_user=Depends(get_current_farmer)
):
    """Reject a friend request."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    clean_r = clean_phone(requester_phone)
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "DELETE FROM friendships WHERE requester_phone = ? AND receiver_phone = ? AND status = 'pending'",
            (clean_r, current_user["phone"])
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=community", status_code=303)


@app.post("/portal/trust-groups/create")
async def create_trust_group(name: str = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if current_user.get("status") != STATUS_APPROVED:
        raise HTTPException(status_code=403, detail="Only approved farmers can create trust groups")
    group_name = name.strip()[:60]
    if not group_name:
        return RedirectResponse(url="/portal/feed?active_tab=community&trust_error=name", status_code=303)
    async with aiosqlite.connect(DB_FILE) as conn:
        async with conn.execute(
            "INSERT INTO trust_groups (name, owner_phone) VALUES (?, ?)",
            (group_name, current_user["phone"])
        ) as cursor:
            group_id = cursor.lastrowid
        await conn.execute(
            "INSERT INTO trust_group_members (group_id, farmer_phone) VALUES (?, ?)",
            (group_id, current_user["phone"])
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=community&trust_created=1", status_code=303)


@app.post("/portal/trust-groups/add-member")
async def add_trust_group_member(
    group_id: int = Form(...),
    friend_phone: str = Form(...),
    current_user=Depends(get_current_farmer)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if current_user.get("status") != STATUS_APPROVED:
        raise HTTPException(status_code=403, detail="Only approved farmers can manage trust groups")
    target_phone = clean_phone(friend_phone)
    async with aiosqlite.connect(DB_FILE) as conn:
        async with conn.execute(
            "SELECT owner_phone FROM trust_groups WHERE id = ?",
            (group_id,)
        ) as cursor:
            group = await cursor.fetchone()
        if not group or group[0] != current_user["phone"]:
            raise HTTPException(status_code=403, detail="Only the group creator can add members")
        async with conn.execute("""
            SELECT 1 FROM friendships
            WHERE status = 'accepted'
              AND ((requester_phone = ? AND receiver_phone = ?)
                OR (requester_phone = ? AND receiver_phone = ?))
        """, (current_user["phone"], target_phone, target_phone, current_user["phone"])) as cursor:
            is_friend = await cursor.fetchone()
        if not is_friend:
            raise HTTPException(status_code=400, detail="Only accepted friends can join this group")
        async with conn.execute(
            "SELECT 1 FROM farmers WHERE phone = ? AND status = 'Approved' AND COALESCE(is_demo, 0) = 0",
            (target_phone,)
        ) as cursor:
            is_approved = await cursor.fetchone()
        if not is_approved:
            raise HTTPException(status_code=400, detail="The friend must be an approved farmer")
        async with conn.execute(
            """SELECT membership_status FROM trust_group_members
               WHERE group_id = ? AND farmer_phone = ?""",
            (group_id, target_phone)
        ) as cursor:
            existing_membership = await cursor.fetchone()
        if existing_membership:
            return RedirectResponse(
                url="/portal/feed?active_tab=community&trust_invite_exists=1",
                status_code=303
            )
        await conn.execute(
            """INSERT INTO trust_group_members
               (group_id, farmer_phone, membership_status)
               VALUES (?, ?, 'pending')""",
            (group_id, target_phone)
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=community&trust_invite_sent=1", status_code=303)


@app.post("/portal/trust-groups/respond")
async def respond_to_trust_group_invite(
    group_id: int = Form(...),
    decision: str = Form(...),
    current_user=Depends(get_current_farmer),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if current_user.get("status") != STATUS_APPROVED:
        raise HTTPException(status_code=403, detail="Only approved farmers can respond to trust group invites")
    if decision not in ("accept", "reject"):
        raise HTTPException(status_code=400, detail="Choose whether to accept or reject the invitation")

    async with aiosqlite.connect(DB_FILE) as conn:
        if decision == "accept":
            result = await conn.execute(
                """UPDATE trust_group_members
                   SET membership_status = 'accepted', joined_at = CURRENT_TIMESTAMP
                   WHERE group_id = ? AND farmer_phone = ? AND membership_status = 'pending'""",
                (group_id, current_user["phone"])
            )
        else:
            result = await conn.execute(
                """UPDATE trust_group_members
                   SET membership_status = 'rejected', whatsapp_enabled = 0
                   WHERE group_id = ? AND farmer_phone = ? AND membership_status = 'pending'""",
                (group_id, current_user["phone"])
            )
        await conn.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Trust group invitation not found or already handled")
    return RedirectResponse(
        url=f"/portal/feed?active_tab=community&trust_invite_{decision}d=1",
        status_code=303
    )


@app.post("/portal/trust-groups/whatsapp")
async def set_trust_group_whatsapp_alerts(
    group_id: int = Form(...),
    enabled: bool = Form(...),
    current_user=Depends(get_current_farmer)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if current_user.get("status") != STATUS_APPROVED:
        raise HTTPException(status_code=403, detail="Only approved farmers can manage trust group alerts")
    async with aiosqlite.connect(DB_FILE) as conn:
        if not await is_trust_group_member(conn, group_id, current_user["phone"]):
            raise HTTPException(status_code=403, detail="You are not a member of this trust group")
        await conn.execute(
            """UPDATE trust_group_members SET whatsapp_enabled = ?
               WHERE group_id = ? AND farmer_phone = ?""",
            (1 if enabled else 0, group_id, current_user["phone"])
        )
        await conn.commit()
    return RedirectResponse(
        url=f"/portal/feed?active_tab=community&trust_whatsapp={1 if enabled else 0}",
        status_code=303
    )


@app.post("/portal/trust-groups/travel")
async def start_trust_group_trip(
    background_tasks: BackgroundTasks,
    group_id: int = Form(...),
    destination: str = Form(...),
    note: str = Form(""),
    current_user=Depends(get_current_farmer)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if current_user.get("status") != STATUS_APPROVED:
        raise HTTPException(status_code=403, detail="Only approved farmers can start travel alerts")
    destination_text = destination.strip()[:120]
    note_text = note.strip()[:240]
    if not destination_text:
        return RedirectResponse(url="/portal/feed?active_tab=community&trust_error=destination", status_code=303)
    async with aiosqlite.connect(DB_FILE) as conn:
        if not await is_trust_group_member(conn, group_id, current_user["phone"]):
            raise HTTPException(status_code=403, detail="You are not a member of this trust group")
        async with conn.execute("SELECT name FROM trust_groups WHERE id = ?", (group_id,)) as cursor:
            group = await cursor.fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="Trust group not found")
        await conn.execute(
            """INSERT INTO trust_trips (group_id, farmer_phone, destination, note)
               VALUES (?, ?, ?, ?)""",
            (group_id, current_user["phone"], destination_text, note_text)
        )
        await conn.commit()
    message = (
        f"Travel alert for {group[0]}: {current_user['name']} is travelling to "
        f"{destination_text}."
        + (f" Details: {note_text}" if note_text else "")
        + " They will send an I'm OK update when safe."
    )
    background_tasks.add_task(
        send_trust_group_whatsapp_alert, group_id, current_user["phone"], message
    )
    return RedirectResponse(url="/portal/feed?active_tab=community&trust_trip_started=1", status_code=303)


@app.post("/portal/trust-groups/check-in")
async def trust_group_check_in(
    background_tasks: BackgroundTasks,
    trip_id: int = Form(...),
    current_user=Depends(get_current_farmer)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if current_user.get("status") != STATUS_APPROVED:
        raise HTTPException(status_code=403, detail="Only approved farmers can check in")
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("BEGIN IMMEDIATE")
        async with conn.execute(
            """SELECT t.id, t.group_id, t.destination, g.name AS group_name
               FROM trust_trips t JOIN trust_groups g ON g.id = t.group_id
               WHERE t.id = ? AND t.farmer_phone = ? AND t.status = 'active'""",
            (trip_id, current_user["phone"])
        ) as cursor:
            trip = await cursor.fetchone()
        if not trip or not await is_trust_group_member(conn, trip["group_id"], current_user["phone"]):
            await conn.rollback()
            raise HTTPException(status_code=404, detail="Active trip not found")
        async with conn.execute(
            "SELECT COUNT(*) FROM trust_trip_checkins WHERE trip_id = ? AND farmer_phone = ? AND xp_awarded > 0",
            (trip_id, current_user["phone"])
        ) as cursor:
            xp_checkins = (await cursor.fetchone())[0]
        xp_awarded = CHECKIN_XP if xp_checkins < 3 else 0
        await conn.execute(
            "INSERT INTO trust_trip_checkins (trip_id, farmer_phone, xp_awarded) VALUES (?, ?, ?)",
            (trip_id, current_user["phone"], xp_awarded)
        )
        if xp_awarded:
            await conn.execute(
                "UPDATE farmers SET xp = xp + ? WHERE phone = ?",
                (xp_awarded, current_user["phone"])
            )
        await conn.commit()
    message = (
        f"✅ {current_user['name']} is OK and checked in while travelling to "
        f"{trip['destination']} (Trust Group: {trip['group_name']})."
    )
    background_tasks.add_task(
        send_trust_group_whatsapp_alert, trip["group_id"], current_user["phone"], message
    )
    return RedirectResponse(
        url=f"/portal/feed?active_tab=community&trust_checkin={xp_awarded}",
        status_code=303
    )


@app.post("/portal/trust-groups/finish-trip")
async def finish_trust_group_trip(trip_id: int = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if current_user.get("status") != STATUS_APPROVED:
        raise HTTPException(status_code=403, detail="Only approved farmers can finish travel alerts")
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            """UPDATE trust_trips SET status = 'completed', ended_at = CURRENT_TIMESTAMP
               WHERE id = ? AND farmer_phone = ? AND status = 'active'""",
            (trip_id, current_user["phone"])
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=community&trust_trip_finished=1", status_code=303)


@app.get("/portal/profile/edit", response_class=HTMLResponse)
async def edit_profile_form(
    photo_updated: Optional[str] = Query(None),
    photo_removed: Optional[str] = Query(None),
    current_user=Depends(get_current_farmer),
):
    if not current_user:
        return RedirectResponse(url="/portal/login?error=Session required.", status_code=303)
    avatar_path = os.path.basename(str(current_user.get("avatar_path") or ""))
    avatar_html = (
        f'<img src="/media/{html.escape(avatar_path, quote=True)}" alt="Your profile photo" '
        'style="width:96px;height:96px;border-radius:50%;object-fit:cover;display:block;margin-bottom:12px;">'
        if avatar_path else ""
    )
    photo_notice = (
        '<p role="status" style="color:#6ee7b7;">Profile picture updated.</p>'
        if photo_updated else
        '<p role="status" style="color:#6ee7b7;">Profile picture removed.</p>'
        if photo_removed else ""
    )
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{UPGRADED_CSS}</style></head>
    <body><div class="glass-panel" style="max-width:480px; margin:40px auto;">
        <h2 style="margin:0 0 8px 0;">Edit Profile</h2>
        {photo_notice}
        <p style="color:var(--text-muted); font-size:14px; margin-bottom:20px;">Update your name, town, and optional private content preference. Your phone number cannot be changed.</p>
        <section style="margin:0 0 20px;padding:14px;background:rgba(255,255,255,.04);border-radius:12px;">
            {avatar_html}
            <form action="/portal/profile/photo" method="post" enctype="multipart/form-data">
                <label>Profile picture</label>
                <input type="file" name="photo" accept="image/jpeg,image/png,image/webp" required>
                <p style="font-size:12px;color:#94a3b8;">JPEG, PNG, or WebP; up to 8 MB. Photos are resized and compressed before saving.</p>
                <button type="submit" class="btn btn-emerald" style="width:100%;">Upload Profile Picture</button>
            </form>
            {f'<form action="/portal/profile/photo/remove" method="post" style="margin-top:8px;"><button type="submit" class="btn" style="width:100%;">Remove Profile Picture</button></form>' if avatar_path else ''}
        </section>
        <form action="/portal/profile/update" method="post">
            <label>Full Name</label>
            <input type="text" name="name" value="{html.escape(current_user.get('name') or '')}" required maxlength="80">
            <label>Town / City</label>
            <input type="text" name="city" value="{html.escape(current_user.get('city') or '')}" required maxlength="60">
            <p style="font-size:13px; color:#94a3b8; margin:8px 0 16px 0;">Changing town may affect your LGA sector and who can see your posts.</p>
            <label>Optional content preference (private)</label>
            <select name="faith_preference">
                {''.join(f'<option value="{option}" {"selected" if current_user.get("faith_preference", "Private") == option else ""}>{option}</option>' for option in FAITH_PREFERENCES)}
            </select>
            <p style="font-size:13px; color:#94a3b8; margin:8px 0 16px 0;">Used only to personalize your daily reflection. Choose Private to remove this preference; it is never shown on your profile. Muslim prayer-time lookups send your town to AlAdhan.</p>
            <button type="submit" class="btn btn-emerald" style="width:100%; padding:14px; margin-top:8px;">Save Changes</button>
        </form>
        <p style="text-align:center; margin-top:20px;">
            <a href="/portal/feed" style="color:#6ee7b7; text-decoration:none;">← Back to Feed</a>
        </p>
        <hr style="border:none; border-top:1px solid rgba(255,255,255,0.1); margin:24px 0;">
        <p style="font-size:13px; color:#f87171; margin-bottom:10px;">Danger zone</p>
        <form action="/portal/account/delete" method="post" onsubmit="return confirm('Permanently delete your account and all data? This cannot be undone.');">
            <button type="submit" class="btn btn-danger" style="width:100%; padding:12px;">Delete My Account</button>
        </form>
    </div></body></html>"""


@app.post("/portal/profile/photo")
async def update_profile_photo(
    photo: UploadFile = File(...),
    current_user=Depends(get_current_farmer),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    image_path = save_social_image(await optimize_social_image(photo, "avatar"), "avatar")
    old_image_path = None
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT avatar_path FROM farmers WHERE phone = ?",
                (current_user["phone"],),
            ) as cursor:
                farmer = await cursor.fetchone()
            if not farmer:
                raise HTTPException(status_code=404, detail="Profile not found")
            old_image_path = farmer["avatar_path"]
            await conn.execute(
                "UPDATE farmers SET avatar_path = ? WHERE phone = ?",
                (image_path, current_user["phone"]),
            )
            await conn.commit()
    except Exception:
        remove_social_image(image_path)
        raise
    remove_social_image(old_image_path)
    return RedirectResponse(url="/portal/profile/edit?photo_updated=1", status_code=303)


@app.post("/portal/profile/photo/remove")
async def remove_profile_photo(current_user=Depends(get_current_farmer)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT avatar_path FROM farmers WHERE phone = ?",
            (current_user["phone"],),
        ) as cursor:
            farmer = await cursor.fetchone()
        if not farmer:
            raise HTTPException(status_code=404, detail="Profile not found")
        await conn.execute(
            "UPDATE farmers SET avatar_path = NULL WHERE phone = ?",
            (current_user["phone"],),
        )
        await conn.commit()
    remove_social_image(farmer["avatar_path"])
    return RedirectResponse(url="/portal/profile/edit?photo_removed=1", status_code=303)


@app.post("/portal/profile/update")
async def update_profile(
    name: str = Form(...),
    city: str = Form(...),
    faith_preference: str = Form("Private"),
    current_user=Depends(get_current_farmer)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    clean_name = sanitize(name)[:80]
    clean_city = sanitize(city)[:60]
    if not clean_name or not clean_city:
        return RedirectResponse(url="/portal/profile/edit?error=empty", status_code=303)
    if faith_preference not in FAITH_PREFERENCES:
        raise HTTPException(status_code=422, detail="Choose a valid content preference")
    # Re-resolve LGA from city map if possible
    lookup = clean_city.strip().lower()
    geo = CITY_AUTOFILL_MAP.get(lookup, {
        "country": current_user.get("country") or "Nigeria",
        "state": current_user.get("state") or "Region",
        "lga": clean_city,
        "area": current_user.get("area") or "General Hub"
    })
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            """UPDATE farmers SET name = ?, city = ?, lga = ?, state = ?, area = ?,
               faith_preference = ?
               WHERE phone = ?""",
            (
                clean_name, clean_city, geo["lga"], geo["state"], geo["area"],
                faith_preference, current_user["phone"]
            )
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=community&profile_updated=1", status_code=303)


@app.post("/portal/invite")
async def send_invite(
    target_phone: str = Form(...),
    current_user=Depends(get_current_farmer)
):
    """Send a WhatsApp invite with the site link to a non-registered number."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    clean_t = normalize_nigerian_mobile(target_phone)
    if not clean_t:
        return RedirectResponse(url="/portal/feed?active_tab=messages&error=invalid_phone", status_code=303)
    # Check if already registered
    async with aiosqlite.connect(DB_FILE) as conn:
        async with conn.execute("SELECT 1 FROM farmers WHERE phone = ?", (clean_t,)) as cur:
            if await cur.fetchone():
                return RedirectResponse(url=f"/portal/feed?active_tab=messages&search_phone={clean_t}&error=already_member", status_code=303)
    # Send invite via WhatsApp
    invite_text = (
        f"👋 Hello! {current_user['name']} invited you to join Farm Watch (olode.com.ng).\n\n"
        f"Register your farm and connect with neighbours to protect your community.\n"
        f"Join here: {SITE_URL}/register\n\n"
        f"After you register and get approved, you can message each other on the platform."
    )
    asyncio.create_task(async_dispatch_whatsapp(clean_t, invite_text))
    return RedirectResponse(url=f"/portal/feed?active_tab=messages&search_phone={clean_t}&invite_sent=1", status_code=303)


@app.get("/portal/messages", response_class=HTMLResponse)
async def simple_messages_page(current_user=Depends(get_current_farmer)):
    """Lightweight messages page — shows friends AND anyone who has messaged you."""
    if not current_user:
        return RedirectResponse(url="/portal/login?error=Session required.", status_code=303)
    my_phone = current_user["phone"]
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        # Friends
        async with conn.execute("""
            SELECT 
                CASE WHEN f.requester_phone = ? THEN f.receiver_phone ELSE f.requester_phone END as phone,
                fa.name as name
            FROM friendships f
            JOIN farmers fa ON fa.phone = CASE WHEN f.requester_phone = ? THEN f.receiver_phone ELSE f.requester_phone END
            WHERE f.status = 'accepted'
              AND (f.requester_phone = ? OR f.receiver_phone = ?)
              AND COALESCE(fa.is_demo, 0) = 0
        """, (my_phone, my_phone, my_phone, my_phone)) as cur:
            friends = await cur.fetchall()
        # Anyone who has sent or received a message with me
        async with conn.execute("""
            SELECT DISTINCT
                CASE WHEN dm.sender_phone = ? THEN dm.receiver_phone ELSE dm.sender_phone END as phone,
                fa.name as name
            FROM direct_messages dm
            JOIN farmers fa ON fa.phone = CASE WHEN dm.sender_phone = ? THEN dm.receiver_phone ELSE dm.sender_phone END
            WHERE (dm.sender_phone = ? OR dm.receiver_phone = ?)
              AND COALESCE(fa.is_demo, 0) = 0
        """, (my_phone, my_phone, my_phone, my_phone)) as cur:
            chat_partners = await cur.fetchall()
    # Merge: friends first, then other chat partners
    seen = set()
    contacts = []
    for row in list(friends) + list(chat_partners):
        ph = row["phone"]
        if ph and ph not in seen:
            seen.add(ph)
            contacts.append({"phone": ph, "name": row["name"] or "Unknown"})
    contacts_html = ""
    for c in contacts:
        contacts_html += (
            '<div style="display:flex; justify-content:space-between; align-items:center; padding:14px; background:rgba(16,185,129,0.08); border-radius:10px; margin-bottom:8px;">'
            f'<a href="/portal/feed?active_tab=community&view_profile={html.escape(str(c["phone"]), quote=True)}" style="font-weight:700; color:#f1f5f9;text-decoration:none;">{html.escape(c["name"])}</a>'
            f'<a href="/portal/chat?with={c["phone"]}" style="background:#34d399; color:#042f2e; padding:8px 16px; border-radius:8px; text-decoration:none; font-weight:700; font-size:14px;">Open Chat</a>'
            '</div>'
        )
    if not contacts_html:
        contacts_html = '<p style="color:#94a3b8; text-align:center;">No conversations yet.</p>'
    page = (
        '<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<style>body{font-family:system-ui,sans-serif;background:#0a1f14;color:#f0fdf4;margin:0;padding:20px;}'
        '.wrap{max-width:560px;margin:0 auto;}h1{font-size:24px;margin:0 0 8px 0;}'
        '.back{color:#6ee7b7;text-decoration:none;font-weight:700;font-size:14px;}'
        '.card{background:rgba(18,42,32,0.8);border:1px solid rgba(52,211,153,0.2);border-radius:16px;padding:20px;margin-top:16px;}'
        '</style></head><body><div class="wrap">'
        '<a href="/portal/feed?active_tab=community" class="back">← Back to Community</a>'
        '<h1 style="margin-top:12px;">💬 Messages</h1>'
        '<p style="color:#94a3b8; font-size:14px;">Friends and people who messaged you</p>'
        f'<div class="card">{contacts_html}</div></div></body></html>'
    )
    return HTMLResponse(content=page)


@app.get("/portal/messages/notifications")
async def message_notifications(current_user=Depends(get_current_farmer)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT COUNT(*) AS unread_count FROM direct_messages dm
               WHERE dm.receiver_phone = ? AND dm.seen = 0
                 AND NOT EXISTS (
                     SELECT 1 FROM blocked_nodes bn
                     WHERE (bn.blocker_phone = dm.sender_phone AND bn.blocked_phone = dm.receiver_phone)
                        OR (bn.blocker_phone = dm.receiver_phone AND bn.blocked_phone = dm.sender_phone)
                 )""",
            (current_user["phone"],)
        ) as cursor:
            unread_count = (await cursor.fetchone())["unread_count"]
        async with conn.execute("""
            SELECT dm.id, dm.sender_phone, dm.body, dm.timestamp, f.name AS sender_name
            FROM direct_messages dm
            LEFT JOIN farmers f ON f.phone = dm.sender_phone
            WHERE dm.receiver_phone = ? AND dm.seen = 0
              AND NOT EXISTS (
                  SELECT 1 FROM blocked_nodes bn
                  WHERE (bn.blocker_phone = dm.sender_phone AND bn.blocked_phone = dm.receiver_phone)
                     OR (bn.blocker_phone = dm.receiver_phone AND bn.blocked_phone = dm.sender_phone)
              )
            ORDER BY dm.id DESC
            LIMIT 10
        """, (current_user["phone"],)) as cursor:
            unread_messages = await cursor.fetchall()
        async with conn.execute(
            """SELECT COUNT(*) FROM friendships
               WHERE receiver_phone = ? AND status = 'pending'
                 AND EXISTS (
                     SELECT 1 FROM farmers f
                     WHERE f.phone = friendships.requester_phone
                       AND COALESCE(f.is_demo, 0) = 0
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM blocked_nodes bn
                     WHERE (bn.blocker_phone = friendships.requester_phone AND bn.blocked_phone = friendships.receiver_phone)
                        OR (bn.blocker_phone = friendships.receiver_phone AND bn.blocked_phone = friendships.requester_phone)
                 )""",
            (current_user["phone"],),
        ) as cursor:
            friend_request_count = (await cursor.fetchone())[0]
        async with conn.execute("""
            SELECT fr.id, fr.requester_phone, f.name AS requester_name
            FROM friendships fr
            LEFT JOIN farmers f ON f.phone = fr.requester_phone
            WHERE fr.receiver_phone = ? AND fr.status = 'pending'
              AND COALESCE(f.is_demo, 0) = 0
              AND NOT EXISTS (
                  SELECT 1 FROM blocked_nodes bn
                  WHERE (bn.blocker_phone = fr.requester_phone AND bn.blocked_phone = fr.receiver_phone)
                     OR (bn.blocker_phone = fr.receiver_phone AND bn.blocked_phone = fr.requester_phone)
              )
            ORDER BY fr.id DESC LIMIT 20
        """, (current_user["phone"],)) as cursor:
            friend_requests = await cursor.fetchall()
    return {
        "unread_count": unread_count,
        "friend_request_count": friend_request_count,
        "friend_requests": [
            {
                "id": request["id"],
                "requester_phone": request["requester_phone"],
                "requester_name": request["requester_name"] or "A farmer",
            }
            for request in friend_requests
        ],
        "messages": [
            {
                "id": message["id"],
                "sender_phone": message["sender_phone"],
                "sender_name": message["sender_name"] or "A farmer",
                "body": message["body"] or "",
                "timestamp": message["timestamp"],
                "kind": "marketplace" if (message["body"] or "").startswith("I am interested in your listing:") else "message",
            }
            for message in unread_messages
        ],
    }


@app.get("/portal/market/notifications")
async def farm_product_notifications(current_user=Depends(get_current_farmer)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("""
            SELECT id, product_id, title, status, created_at
            FROM farm_product_notifications
            WHERE farmer_phone = ? AND is_read = 0
            ORDER BY id DESC LIMIT 10
        """, (current_user["phone"],)) as cursor:
            notifications = await cursor.fetchall()
        if notifications:
            ids = [notification["id"] for notification in notifications]
            placeholders = ",".join("?" for _ in ids)
            await conn.execute(
                f"UPDATE farm_product_notifications SET is_read = 1 WHERE id IN ({placeholders})",
                ids
            )
            await conn.commit()
    return {
        "notifications": [
            {
                "id": notification["id"],
                "product_id": notification["product_id"],
                "title": notification["title"],
                "status": notification["status"],
                "created_at": notification["created_at"],
            }
            for notification in notifications
        ]
    }



@app.get("/portal/chat", response_class=HTMLResponse)
async def simple_chat_page(
    with_phone: str = Query(..., alias="with"),
    sent: Optional[str] = Query(None),
    current_user=Depends(get_current_farmer)
):
    """Lightweight one-to-one chat."""
    if not current_user:
        return RedirectResponse(url="/portal/login?error=Session required.", status_code=303)
    clean_with = normalize_nigerian_mobile(with_phone) or clean_phone(with_phone)
    # Mark incoming messages from this person as seen (safe if column missing)
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute(
                "UPDATE direct_messages SET seen = 1 WHERE receiver_phone = ? AND sender_phone = ?",
                (current_user["phone"], clean_with)
            )
            alt = None
            if clean_with.startswith("0") and len(clean_with) == 11:
                alt = "234" + clean_with[1:]
            elif clean_with.startswith("234") and len(clean_with) == 13:
                alt = "0" + clean_with[3:]
            if alt:
                await conn.execute(
                    "UPDATE direct_messages SET seen = 1 WHERE receiver_phone = ? AND sender_phone = ?",
                    (current_user["phone"], alt)
                )
            await conn.commit()
    except Exception:
        pass
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        peer = None
        async with conn.execute("SELECT name, phone FROM farmers WHERE phone = ? AND COALESCE(is_demo, 0) = 0", (clean_with,)) as cur:
            peer = await cur.fetchone()
        if not peer and clean_with.startswith("0") and len(clean_with) == 11:
            async with conn.execute("SELECT name, phone FROM farmers WHERE phone = ? AND COALESCE(is_demo, 0) = 0", ("234" + clean_with[1:],)) as cur:
                peer = await cur.fetchone()
        elif not peer and clean_with.startswith("234") and len(clean_with) == 13:
            async with conn.execute("SELECT name, phone FROM farmers WHERE phone = ? AND COALESCE(is_demo, 0) = 0", ("0" + clean_with[3:],)) as cur:
                peer = await cur.fetchone()
        if peer and await guard_status(conn, current_user["phone"], peer["phone"]):
            peer = None
        msgs = []
        peer_phone = clean_with
        peer_name = "Unknown"
        if peer:
            peer_name = peer["name"] or "Unknown"
            peer_phone = peer["phone"]
            alts = {peer_phone}
            if peer_phone.startswith("0") and len(peer_phone) == 11:
                alts.add("234" + peer_phone[1:])
            elif peer_phone.startswith("234") and len(peer_phone) == 13:
                alts.add("0" + peer_phone[3:])
            ph = ",".join("?" * len(alts))
            async with conn.execute(
                f"SELECT * FROM direct_messages WHERE (sender_phone = ? AND receiver_phone IN ({ph})) OR (receiver_phone = ? AND sender_phone IN ({ph})) ORDER BY id ASC",
                (current_user["phone"],) + tuple(alts) + (current_user["phone"],) + tuple(alts)
            ) as mcur:
                msgs = await mcur.fetchall()
    messages_html = ""
    for m in msgs:
        is_mine = m["sender_phone"] == current_user["phone"]
        align = "flex-end" if is_mine else "flex-start"
        bg = "rgba(16,185,129,0.2)" if is_mine else "rgba(255,255,255,0.08)"
        messages_html += (
            f'<div style="display:flex;justify-content:{align};margin-bottom:10px;">'
            f'<div style="max-width:75%;background:{bg};padding:10px 14px;border-radius:12px;">'
            f'<div style="font-size:15px;color:#f1f5f9;">{html.escape(m["body"])}</div>'
            f'<div style="font-size:11px;color:#94a3b8;margin-top:4px;">{m["timestamp"]}</div>'
            '</div></div>'
        )
    if not messages_html:
        messages_html = '<p style="text-align:center;color:#94a3b8;margin:40px 0;">No messages yet. Say hello!</p>'
    page = (
        '<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<style>body{font-family:system-ui,sans-serif;background:#0a1f14;color:#f0fdf4;margin:0;padding:20px;}'
        '.wrap{max-width:600px;margin:0 auto;}.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;}'
        '.name{font-size:20px;font-weight:800;}.back{color:#6ee7b7;text-decoration:none;font-weight:700;}'
        '.chat{background:rgba(0,0,0,0.25);border-radius:12px;padding:16px;min-height:280px;max-height:50vh;overflow-y:auto;margin-bottom:16px;}'
        'form{display:flex;gap:10px;}input{flex:1;padding:14px;font-size:16px;background:#1e293b;border:2px solid #475569;color:#f8fafc;border-radius:10px;}'
        'button{padding:14px 24px;background:#34d399;color:#042f2e;border:none;border-radius:10px;font-weight:700;font-size:16px;cursor:pointer;}'
        '</style></head><body><div class="wrap">'
        '<div class="header"><a href="/portal/messages" class="back">← Back</a>'
        f'<div class="name"><a href="/portal/feed?active_tab=community&view_profile={html.escape(str(peer_phone), quote=True)}" style="color:inherit;text-decoration:none;">{html.escape(peer_name)}</a> ✅</div><span></span></div>'
        f'<div style="font-size:13px;color:#94a3b8;margin-bottom:12px;font-family:monospace;">{mask_phone_number(peer_phone)}</div>'
        + ('<div style="background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.4);border-radius:10px;padding:12px;margin-bottom:12px;color:#6ee7b7;font-weight:700;">✅ Message sent successfully.</div>' if sent else '')
        + f'<div class="chat" id="chatBox">{messages_html}</div>'
        '<div id="sentMsg" style="display:none;background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.4);border-radius:10px;padding:10px;margin-bottom:10px;color:#6ee7b7;font-weight:700;">✅ Message sent successfully.</div>'
        '<form id="sendForm" action="/portal/messages/send" method="post">'
        f'<input type="hidden" name="receiver_phone" value="{peer_phone}">'
        '<input type="text" name="body" id="msgBody" placeholder="Type a message..." required maxlength="350" autocomplete="off">'
        '<button type="submit">Send</button></form>'
        '<script>'
        'document.getElementById("sendForm").addEventListener("submit", async function(e) {'
        '  e.preventDefault();'
        '  var body = document.getElementById("msgBody");'
        '  var text = body.value.trim();'
        '  if (!text) return;'
        '  var fd = new FormData(this);'
        '  var res = await fetch("/portal/messages/send", {method:"POST", body:fd, redirect:"manual"});'
        '  if (res.ok || res.status === 303 || res.type === "opaqueredirect") {'
        '    var box = document.getElementById("chatBox");'
        '    var line = document.createElement("div");'
        '    line.style.cssText = "text-align:right;margin:8px 0;color:#6ee7b7;";'
        '    line.textContent = text;'
        '    box.appendChild(line);'
        '    box.scrollTop = box.scrollHeight;'
        '    body.value = "";'
        '    var note = document.getElementById("sentMsg");'
        '    note.style.display = "block";'
        '    setTimeout(function(){ note.style.display = "none"; }, 3000);'
        '  }'
        '});'
        '</script></div></body></html>'
    )
    return HTMLResponse(content=page)



@app.get("/portal/soil/history", response_class=HTMLResponse)
async def soil_history(current_user=Depends(get_current_farmer)):
    """Show the farmer's past soil readings."""
    if not current_user:
        return RedirectResponse(url="/portal/login?error=Session required.", status_code=303)
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT moisture, ph, timestamp, source FROM sensor_readings WHERE farmer_phone = ? ORDER BY id DESC LIMIT 50",
            (current_user["phone"],)
        ) as cur:
            rows = await cur.fetchall()
    rows_html = ""
    for r in rows:
        rows_html += (
            "<tr>"
            f"<td>{r['timestamp']}</td>"
            f"<td style='font-weight:700; color:#6ee7b7;'>{r['moisture']}%</td>"
            f"<td style='font-weight:700; color:#93c5fd;'>{r['ph']}</td>"
            f"<td style='font-size:12px; color:#94a3b8;'>{r['source'] or 'manual'}</td>"
            "</tr>"
        )
    if not rows_html:
        rows_html = '<tr><td colspan="4" style="text-align:center; color:#94a3b8;">No readings yet.</td></tr>'
    page = (
        f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>{UPGRADED_CSS}</style></head>"
        "<body><div class='glass-panel' style='max-width:640px; margin:40px auto;'>"
        "<h2 style='margin:0 0 8px 0;'>🌱 Soil Reading History</h2>"
        "<p style='color:var(--text-muted); font-size:14px; margin-bottom:16px;'>Your last 50 readings.</p>"
        "<div style='overflow-x:auto;'>"
        "<table class='data-table'><thead><tr><th>Date</th><th>Moisture</th><th>pH</th><th>Source</th></tr></thead>"
        f"<tbody>{rows_html}</tbody></table></div>"
        "<p style='text-align:center; margin-top:20px;'>"
        "<a href='/portal/feed?active_tab=incidents' style='color:#6ee7b7; text-decoration:none;'>← Back to Feed</a>"
        "</p></div></body></html>"
    )
    return HTMLResponse(content=page)


@app.post("/portal/family/create")
async def create_family_group(
    family_name: str = Form(...),
    lga: str = Form(...),
    town: str = Form(...),
    current_user=Depends(get_current_farmer),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Sign in to create a family meeting")
    if current_user.get("status") != STATUS_APPROVED:
        raise HTTPException(status_code=403, detail="Only approved farmers can create family meetings")
    clean_name = family_name.strip()[:80]
    clean_lga = lga.strip()[:80]
    clean_town = town.strip()[:80]
    if not clean_name or not clean_lga or not clean_town:
        raise HTTPException(status_code=400, detail="Family name, LGA, and town are required")

    invite_code = secrets.token_hex(8).upper()
    meeting_room = secrets.token_hex(20)
    async with aiosqlite.connect(DB_FILE) as conn:
        async with conn.execute(
            """INSERT INTO family_groups
               (name, lga, town, owner_phone, invite_code, meeting_room)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (clean_name, clean_lga, clean_town, current_user["phone"], invite_code, meeting_room),
        ) as cursor:
            group_id = cursor.lastrowid
        await conn.execute(
            "INSERT INTO family_group_members (group_id, farmer_phone) VALUES (?, ?)",
            (group_id, current_user["phone"]),
        )
        await conn.commit()
    return RedirectResponse("/portal/feed?active_tab=family", status_code=303)


@app.post("/portal/family/join")
async def join_family_group(
    invite_code: str = Form(...),
    current_user=Depends(get_current_farmer),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Sign in to join a family meeting")
    if current_user.get("status") != STATUS_APPROVED:
        raise HTTPException(status_code=403, detail="Only approved farmers can join family meetings")
    code = invite_code.strip().upper()
    async with aiosqlite.connect(DB_FILE) as conn:
        async with conn.execute(
            "SELECT id FROM family_groups WHERE invite_code = ?",
            (code,),
        ) as cursor:
            group = await cursor.fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="Family invite code not found")
        await conn.execute(
            "INSERT OR IGNORE INTO family_group_members (group_id, farmer_phone) VALUES (?, ?)",
            (group[0], current_user["phone"]),
        )
        await conn.commit()
    return RedirectResponse("/portal/feed?active_tab=family", status_code=303)


@app.post("/portal/family/rotate-code")
async def rotate_family_invite_code(
    group_id: int = Form(...),
    current_user=Depends(get_current_farmer),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if current_user.get("status") != STATUS_APPROVED:
        raise HTTPException(status_code=403, detail="Only approved farmers can manage family meeting invites")
    async with aiosqlite.connect(DB_FILE) as conn:
        async with conn.execute(
            "SELECT owner_phone FROM family_groups WHERE id = ?",
            (group_id,),
        ) as cursor:
            group = await cursor.fetchone()
        if not group or group[0] != current_user["phone"]:
            raise HTTPException(status_code=403, detail="Only the family meeting creator can renew its invite")
        new_code = secrets.token_hex(8).upper()
        await conn.execute(
            "UPDATE family_groups SET invite_code = ? WHERE id = ?",
            (new_code, group_id),
        )
        await conn.commit()
    return RedirectResponse("/portal/feed?active_tab=family", status_code=303)


@app.post("/portal/family/message")
async def post_family_message(
    group_id: int = Form(...),
    body: str = Form(...),
    current_user=Depends(get_current_farmer),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if current_user.get("status") != STATUS_APPROVED:
        raise HTTPException(status_code=403, detail="Only approved farmers can post family messages")
    message = body.strip()
    if not message or len(message) > 500:
        raise HTTPException(status_code=400, detail="Family messages must be between 1 and 500 characters")
    async with aiosqlite.connect(DB_FILE) as conn:
        async with conn.execute(
            "SELECT 1 FROM family_group_members WHERE group_id = ? AND farmer_phone = ?",
            (group_id, current_user["phone"]),
        ) as cursor:
            membership = await cursor.fetchone()
        if not membership:
            raise HTTPException(status_code=403, detail="Join this family meeting before posting")
        await conn.execute(
            """INSERT INTO family_meeting_messages
               (group_id, author_phone, author_name, body) VALUES (?, ?, ?, ?)""",
            (group_id, current_user["phone"], current_user["name"], message),
        )
        await conn.commit()
    return RedirectResponse("/portal/feed?active_tab=family", status_code=303)


@app.get("/portal/family/qr/{invite_code}")
async def family_invite_qr(
    invite_code: str,
    request: Request,
    current_user=Depends(get_current_farmer),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Sign in to view this family invite QR code")
    if current_user.get("status") != STATUS_APPROVED:
        raise HTTPException(status_code=403, detail="Only approved farmers can view family meeting invites")
    code = invite_code.upper()
    if len(code) != 16 or not all(char in "0123456789ABCDEF" for char in code):
        raise HTTPException(status_code=404, detail="Family invite not found")
    async with aiosqlite.connect(DB_FILE) as conn:
        async with conn.execute(
            """SELECT 1 FROM family_groups fg
               JOIN family_group_members fgm ON fgm.group_id = fg.id
               WHERE fg.invite_code = ? AND fgm.farmer_phone = ?""",
            (code, current_user["phone"]),
        ) as cursor:
            membership = await cursor.fetchone()
    if not membership:
        raise HTTPException(status_code=404, detail="Family invite not found")
    invite_url = f"{str(request.base_url).rstrip('/')}/family/invite/{code}"
    qr_image = qrcode.make(invite_url)
    image_buffer = io.BytesIO()
    qr_image.save(image_buffer, format="PNG")
    return Response(
        content=image_buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/family/invite/{invite_code}", response_class=HTMLResponse)
async def family_invite_page(
    invite_code: str,
    current_user=Depends(get_current_farmer),
):
    code = invite_code.upper()
    if len(code) != 16 or not all(char in "0123456789ABCDEF" for char in code):
        raise HTTPException(status_code=404, detail="Family invite not found")
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT name, lga, town FROM family_groups WHERE invite_code = ?",
            (code,),
        ) as cursor:
            family = await cursor.fetchone()
        is_member = False
        if family and current_user and current_user.get("status") == STATUS_APPROVED:
            async with conn.execute(
                """SELECT 1 FROM family_groups fg
                   JOIN family_group_members fgm ON fgm.group_id = fg.id
                   WHERE fg.invite_code = ? AND fgm.farmer_phone = ?""",
                (code, current_user["phone"]),
            ) as cursor:
                is_member = await cursor.fetchone() is not None
    if not family:
        raise HTTPException(status_code=404, detail="Family invite not found")

    invite_url = f"/family/invite/{code}"
    if current_user and is_member:
        action_html = '<a class="btn btn-emerald" href="/portal/feed?active_tab=family">Open Family Meetings</a>'
    elif current_user and current_user.get("status") == STATUS_APPROVED:
        action_html = f"""
            <form action="/portal/family/join" method="post">
                <input type="hidden" name="invite_code" value="{code}">
                <button class="btn btn-emerald" type="submit">Join this family meeting</button>
            </form>"""
    elif current_user:
        action_html = '<p style="color:#fbbf24;">Approved farmer accounts can join family meetings.</p>'
    else:
        login_url = f"/portal/login?next_page={quote(invite_url, safe='/')}"
        action_html = f"""
            <a class="btn btn-emerald" href="{html.escape(login_url, quote=True)}">Sign in to join</a>
            <p style="margin-top:12px;color:#cbd5e1;">New to Olode.com.ng? <a href="/register" style="color:#6ee7b7;">Register as a farmer</a>, then enter this invite code: <b>{code}</b></p>"""

    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Family invitation | Olode.com.ng</title><style>{UPGRADED_CSS}</style></head>
        <body><main class="glass-panel" style="max-width:560px;margin:48px auto;">
            <div style="font-size:38px;">👨‍👩‍👧‍👦</div>
            <h1 style="color:#fff;">Family meeting invitation</h1>
            <p style="color:#cbd5e1;">You are invited to <b style="color:#6ee7b7;">{html.escape(family['name'])}</b>.</p>
            <p style="color:#cbd5e1;">📍 {html.escape(family['town'])}, {html.escape(family['lga'])}</p>
            <p style="color:#94a3b8;">Invite code: <b style="color:#e2e8f0;">{code}</b></p>
            {action_html}
            <p style="margin-top:24px;color:#94a3b8;font-size:13px;">Olode.com.ng · Family connections for farming communities</p>
        </main></body></html>"""


@app.post("/portal/account/delete")
async def delete_account(current_user=Depends(get_current_farmer)):
    """Permanently delete the current user's account and data."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    phone = current_user["phone"]
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("""
            DELETE FROM trust_trip_checkins
            WHERE farmer_phone = ? OR trip_id IN (
                SELECT id FROM trust_trips
                WHERE farmer_phone = ? OR group_id IN (
                    SELECT id FROM trust_groups WHERE owner_phone = ?
                )
            )
        """, (phone, phone, phone))
        await conn.execute("""
            DELETE FROM trust_trips
            WHERE farmer_phone = ? OR group_id IN (
                SELECT id FROM trust_groups WHERE owner_phone = ?
            )
        """, (phone, phone))
        await conn.execute("""
            DELETE FROM trust_group_members
            WHERE farmer_phone = ? OR group_id IN (
                SELECT id FROM trust_groups WHERE owner_phone = ?
            )
        """, (phone, phone))
        await conn.execute("DELETE FROM trust_groups WHERE owner_phone = ?", (phone,))
        await conn.execute("""
            DELETE FROM family_meeting_messages
            WHERE group_id IN (SELECT id FROM family_groups WHERE owner_phone = ?)
               OR author_phone = ?
        """, (phone, phone))
        await conn.execute("""
            DELETE FROM family_group_members
            WHERE farmer_phone = ? OR group_id IN (
                SELECT id FROM family_groups WHERE owner_phone = ?
            )
        """, (phone, phone))
        await conn.execute("DELETE FROM family_groups WHERE owner_phone = ?", (phone,))
        await conn.execute("DELETE FROM direct_messages WHERE sender_phone = ? OR receiver_phone = ?", (phone, phone))
        await conn.execute("DELETE FROM friendships WHERE requester_phone = ? OR receiver_phone = ?", (phone, phone))
        await conn.execute("DELETE FROM farmer_reports WHERE reporter_phone = ? OR target_phone = ?", (phone, phone))
        await conn.execute("""
            DELETE FROM blocked_nodes
            WHERE (blocker_phone = ? OR blocked_phone = ?)
              AND guard_status != 'expelled'
        """, (phone, phone))
        await conn.execute("DELETE FROM farm_products WHERE farmer_phone = ?", (phone,))
        await conn.execute("DELETE FROM sensor_readings WHERE farmer_phone = ?", (phone,))
        await conn.execute("DELETE FROM checkins WHERE farmer_phone = ?", (phone,))
        await conn.execute("DELETE FROM shoutouts WHERE farmer_phone = ?", (phone,))
        await conn.execute("DELETE FROM farmers WHERE phone = ?", (phone,))
        await conn.commit()
    resp = RedirectResponse(url="/register?deleted=1", status_code=303)
    resp.delete_cookie(key="farmer_session")
    return resp



@app.get("/portal/feed", response_class=HTMLResponse)
async def farmer_feed_portal(
    request: Request,
    current_user=Depends(get_current_farmer),
    active_tab: Optional[str] = Query(None),
    search_phone: Optional[str] = Query(None),
    market_cat: Optional[str] = Query(None),
    market_status: Optional[str] = Query(None),
    market_q: Optional[str] = Query(None),
    market_sort: Optional[str] = Query(None),
    market_mine: Optional[str] = Query(None),
    market_page: Optional[int] = Query(1),
    friend_sent: Optional[str] = Query(None),
    report_sent: Optional[str] = Query(None),
    profile_updated: Optional[str] = Query(None),
    status_posted: Optional[int] = Query(None),
    shoutout_posted: Optional[int] = Query(None),
    invite_sent: Optional[str] = Query(None),
    view_profile: Optional[str] = Query(None),
    friend_name: Optional[str] = Query(None),
    soil_saved: Optional[str] = Query(None),
    posted: Optional[str] = Query(None),
    post_err: Optional[str] = Query(None),
):
    if not current_user: return RedirectResponse(url="/portal/login?error=Session required.", status_code=303)
    # Always define tip_of_day early so it is never unbound
    tip_of_day = FARMING_TIPS[int(__import__('datetime').datetime.now().strftime('%j')) % len(FARMING_TIPS)]
    # Unread message count for badge (safe if column missing)
    unread_count = 0
    unread_product_count = 0
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM direct_messages WHERE receiver_phone = ? AND seen = 0",
                (current_user["phone"],)
            ) as cur:
                unread_count = (await cur.fetchone())[0]
            async with conn.execute(
                """SELECT COUNT(*) FROM farm_product_notifications
                   WHERE farmer_phone = ? AND is_read = 0""",
                (current_user["phone"],)
            ) as cur:
                unread_product_count = (await cur.fetchone())[0]
    except Exception:
        unread_count = 0
    unread_badge = f'<span id="unread-message-badge" style="display:{"inline-block" if unread_count else "none"}; background:#ef4444; color:white; font-size:11px; font-weight:800; padding:2px 7px; border-radius:10px; margin-left:6px;">{unread_count}</span>'
    product_notification_badge = (
        f'<span id="market-notification-count" style="background:#ef4444;color:white;font-size:11px;font-weight:800;padding:2px 7px;border-radius:10px;margin-left:6px;">{unread_product_count}</span>'
        if unread_product_count else
        '<span id="market-notification-count" style="display:none;background:#ef4444;color:white;font-size:11px;font-weight:800;padding:2px 7px;border-radius:10px;margin-left:6px;">0</span>'
    )
    admin_dashboard_link = (
        '<a href="/admin/login?next_page=%2Fdashboard" class="btn" '
        'style="background:rgba(245,158,11,0.12);color:#fbbf24;'
        'border:1px solid rgba(245,158,11,0.35);padding:10px 14px;'
        'font-size:13px;border-radius:10px;">🔐 Admin Login</a>'
    )
    if current_user.get("status") in RESTRICTED_STATUSES:
        return HTMLResponse(content=f"""
        <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{UPGRADED_CSS}</style></head>
        <body><div class="glass-panel" style="max-width:480px; margin:80px auto; text-align:center;">
            <div style="font-size:48px; margin-bottom:16px;">🔒</div>
            <h2 style="margin:0 0 12px 0;">Access Hold Active</h2>
            <p style="color:var(--text-muted); line-height:1.6;">
                Your node status is currently <b>{html.escape(str(current_user.get('status')))}</b>.
                Portal access is restricted until an administrator reviews and clears your profile.
            </p>
            <a href="/portal/logout" class="btn btn-danger" style="margin-top:20px;">Disconnect Session</a>
        </div></body></html>""")
    weather = await get_realtime_weather(current_user['lga'])
    soil = await get_latest_soil_reading(current_user['phone'], current_user['lga'])
    faith_card_html = ""
    if active_tab in (None, "community"):
        faith_card_html = await render_faith_card(
            current_user.get("faith_preference", "Private"),
            current_user.get("city") or current_user.get("lga") or "",
        )
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("""
            SELECT * FROM farmers f
            WHERE f.lga = ? AND f.status = 'Pending' AND COALESCE(f.is_demo, 0) = 0
              AND NOT EXISTS (
                  SELECT 1 FROM blocked_nodes bn
                  WHERE (bn.blocker_phone = ? AND bn.blocked_phone = f.phone)
                     OR (bn.blocker_phone = f.phone AND bn.blocked_phone = ?)
              )
        """, (current_user['lga'], current_user['phone'], current_user['phone'])) as c1:
            pending_neighbors = await c1.fetchall()
        pending_neighbors = [
            farmer for farmer in pending_neighbors
            if not await guard_status(conn, current_user["phone"], farmer["phone"])
        ]
        async with conn.execute("""
            SELECT * FROM farmers f
            WHERE f.lga = ? AND f.status = 'Approved' AND f.phone != ?
              AND COALESCE(f.is_demo, 0) = 0
              AND NOT EXISTS (
                  SELECT 1 FROM blocked_nodes bn
                  WHERE (bn.blocker_phone = ? AND bn.blocked_phone = f.phone)
                     OR (bn.blocker_phone = f.phone AND bn.blocked_phone = ?)
              )
        """, (current_user['lga'], current_user['phone'], current_user['phone'], current_user['phone'])) as c2:
            approved_neighbors = await c2.fetchall()
        approved_neighbors = [
            farmer for farmer in approved_neighbors
            if not await guard_status(conn, current_user["phone"], farmer["phone"])
        ]
        # Existing friendships (pending or accepted) for current user
        async with conn.execute("""
            SELECT requester_phone, receiver_phone, status FROM friendships
            WHERE requester_phone = ? OR receiver_phone = ?
        """, (current_user['phone'], current_user['phone'])) as cf:
            friend_rows = await cf.fetchall()
        friend_status_map = {}
        for fr in friend_rows:
            other = fr["receiver_phone"] if fr["requester_phone"] == current_user["phone"] else fr["requester_phone"]
            if await guard_status(conn, current_user["phone"], other):
                continue
            friend_status_map[other] = fr["status"]
        async with conn.execute("SELECT * FROM alerts_log WHERE lga = ? AND status = 'Active' ORDER BY id DESC",
                                (current_user['lga'],)) as c3:
            active_threats = await c3.fetchall()
        # Community engagement data
        async with conn.execute("""
            SELECT c.farmer_phone, f.name, c.timestamp FROM checkins c
            JOIN farmers f ON f.phone = c.farmer_phone
            WHERE c.lga = ? AND c.timestamp > datetime('now', '-1 day')
              AND NOT EXISTS (
                  SELECT 1 FROM blocked_nodes bn
                  WHERE (bn.blocker_phone = ? AND bn.blocked_phone = c.farmer_phone)
                     OR (bn.blocker_phone = c.farmer_phone AND bn.blocked_phone = ?)
              )
            ORDER BY c.id DESC LIMIT 20
        """, (current_user['lga'], current_user['phone'], current_user['phone'])) as c4:
            recent_checkins = await c4.fetchall()
        async with conn.execute("""
            SELECT id, farmer_phone, farmer_name, lga, message, timestamp,
                   category, recipient, template_key, image_path
            FROM shoutouts s WHERE lga = ?
              AND NOT EXISTS (
                  SELECT 1 FROM blocked_nodes bn
                  WHERE (bn.blocker_phone = ? AND bn.blocked_phone = s.farmer_phone)
                     OR (bn.blocker_phone = s.farmer_phone AND bn.blocked_phone = ?)
              )
            ORDER BY id DESC LIMIT 25
        """, (current_user['lga'], current_user['phone'], current_user['phone'])) as c5:
            recent_shoutouts = await c5.fetchall()
        # Statuses from friends + own (network growth)
        friend_phones = [ph for ph, st in friend_status_map.items() if st == 'accepted']
        friend_phones.append(current_user['phone'])
        placeholders = ",".join("?" * len(friend_phones))
        async with conn.execute(f"""
            SELECT s.id, s.author_phone, s.author_name, s.content, s.timestamp,
                   s.image_path, f.avatar_path,
                   (SELECT COUNT(*) FROM status_likes WHERE status_id = s.id) as likes,
                   (SELECT COUNT(*) FROM status_comments WHERE status_id = s.id) as comments
            FROM statuses s
            JOIN farmers f ON f.phone = s.author_phone
            WHERE s.author_phone IN ({placeholders})
              AND s.id NOT IN (SELECT status_id FROM status_hides WHERE user_phone = ?)
            ORDER BY s.id DESC LIMIT 30
        """, friend_phones + [current_user['phone']]) as cs:
            status_posts = await cs.fetchall()
        status_comments_map = {}
        if status_posts:
            ids = [s['id'] for s in status_posts]
            ph = ",".join("?" * len(ids))
            async with conn.execute(f"SELECT status_id, author_phone, author_name, text FROM status_comments WHERE status_id IN ({ph}) ORDER BY id ASC", ids) as cc:
                for row in await cc.fetchall():
                    status_comments_map.setdefault(row['status_id'], []).append(row)
        async with conn.execute("""
            SELECT id FROM checkins
            WHERE farmer_phone = ? AND date(timestamp) = date('now', 'localtime') LIMIT 1
        """, (current_user['phone'],)) as c6:
            checked_in_today = await c6.fetchone() is not None
        async with conn.execute("""
            SELECT name, xp, phone FROM farmers
            WHERE lga = ? AND status = 'Approved' AND COALESCE(is_demo, 0) = 0
              AND NOT EXISTS (
                  SELECT 1 FROM blocked_nodes bn
                  WHERE (bn.blocker_phone = ? AND bn.blocked_phone = farmers.phone)
                     OR (bn.blocker_phone = farmers.phone AND bn.blocked_phone = ?)
              )
            ORDER BY xp DESC LIMIT 10
        """, (current_user['lga'], current_user['phone'], current_user['phone'])) as c7:
            leaderboard_rows = await c7.fetchall()
        async with conn.execute("""
            SELECT f.id, f.requester_phone, fa.name as requester_name
            FROM friendships f
            JOIN farmers fa ON fa.phone = f.requester_phone
            WHERE f.receiver_phone = ? AND f.status = 'pending'
              AND COALESCE(fa.is_demo, 0) = 0
              AND NOT EXISTS (
                  SELECT 1 FROM blocked_nodes bn
                  WHERE (bn.blocker_phone = f.receiver_phone AND bn.blocked_phone = f.requester_phone)
                     OR (bn.blocker_phone = f.requester_phone AND bn.blocked_phone = f.receiver_phone)
              )
        """, (current_user['phone'],)) as c_fr:
            pending_requests = await c_fr.fetchall()
        async with conn.execute("""
            SELECT 
                CASE WHEN f.requester_phone = ? THEN f.receiver_phone ELSE f.requester_phone END as friend_phone,
                fa.name as friend_name
            FROM friendships f
            JOIN farmers fa ON fa.phone = CASE WHEN f.requester_phone = ? THEN f.receiver_phone ELSE f.requester_phone END
            WHERE f.status = 'accepted'
              AND (f.requester_phone = ? OR f.receiver_phone = ?)
              AND COALESCE(fa.is_demo, 0) = 0
              AND NOT EXISTS (
                  SELECT 1 FROM blocked_nodes bn
                  WHERE (bn.blocker_phone = ? AND bn.blocked_phone = CASE WHEN f.requester_phone = ? THEN f.receiver_phone ELSE f.requester_phone END)
                     OR (bn.blocker_phone = CASE WHEN f.requester_phone = ? THEN f.receiver_phone ELSE f.requester_phone END AND bn.blocked_phone = ?)
              )
        """, (current_user['phone'], current_user['phone'], current_user['phone'], current_user['phone'],
              current_user['phone'], current_user['phone'], current_user['phone'], current_user['phone'])) as c_ff:
            my_friends = await c_ff.fetchall()
        my_friends = [
            friend for friend in my_friends
            if not await guard_status(conn, current_user["phone"], friend["friend_phone"])
        ]
        async with conn.execute("""
            SELECT tg.id, tg.name, tg.owner_phone
            FROM trust_groups tg
            JOIN trust_group_members tgm ON tgm.group_id = tg.id
            WHERE tgm.farmer_phone = ? AND tgm.membership_status = 'accepted'
            ORDER BY tg.id DESC
        """, (current_user["phone"],)) as c_tg:
            trust_groups = await c_tg.fetchall()
        async with conn.execute("""
            SELECT tg.id, tg.name, f.phone AS owner_phone, f.name AS owner_name
            FROM trust_group_members tgm
            JOIN trust_groups tg ON tg.id = tgm.group_id
            JOIN farmers f ON f.phone = tg.owner_phone
            WHERE tgm.farmer_phone = ? AND tgm.membership_status = 'pending'
            ORDER BY tgm.joined_at DESC
        """, (current_user["phone"],)) as c_tgi:
            pending_trust_group_invites = await c_tgi.fetchall()
        async with conn.execute("""
            SELECT id, title, embed_path FROM spotify_links
            WHERE farmer_phone = ? ORDER BY id DESC LIMIT 20
        """, (current_user["phone"],)) as c_sp:
            my_spotify_links = await c_sp.fetchall()
        # Market filter: category + status + search + sort
        status_filter = market_status if market_status in ("Active", "Sold", "All") else "Active"
        show_mine_only = (market_mine or "").lower() in ("1", "yes", "true")
        cat_filter = market_cat if market_cat in PRODUCT_CATEGORIES else None
        search_q = (market_q or "").strip()[:80]
        sort_key = market_sort if market_sort in ("newest", "oldest", "title_az", "title_za") else "newest"
        if status_filter == "All":
            sql = "SELECT * FROM farm_products WHERE status IN ('Active','Sold')"
            params: list = []
        elif show_mine_only and status_filter == "Active":
            sql = "SELECT * FROM farm_products WHERE status IN ('Active','Pending')"
            params = []
        else:
            sql = "SELECT * FROM farm_products WHERE status = ?"
            params = [status_filter]
        if cat_filter:
            sql += " AND category = ?"
            params.append(cat_filter)
        if search_q:
            sql += " AND (title LIKE ? OR description LIKE ? OR farmer_name LIKE ? OR lga LIKE ?)"
            like = f"%{search_q}%"
            params.extend([like, like, like, like])
        if show_mine_only:
            sql += " AND farmer_phone = ?"
            params.append(current_user["phone"])
        order_map = {
            "newest": "id DESC",
            "oldest": "id ASC",
            "title_az": "title COLLATE NOCASE ASC",
            "title_za": "title COLLATE NOCASE DESC",
        }
        # Count total for pagination
        count_sql = sql.replace("SELECT *", "SELECT COUNT(*)", 1)
        async with conn.execute(count_sql, params) as ccount:
            total_products = (await ccount.fetchone())[0]
        page = max(1, int(market_page or 1))
        per_page = 9
        total_pages = max(1, (total_products + per_page - 1) // per_page)
        if page > total_pages:
            page = total_pages
        offset = (page - 1) * per_page
        sql += f" ORDER BY {order_map[sort_key]} LIMIT {per_page} OFFSET {offset}"
        async with conn.execute(sql, params) as c8:
            market_products = await c8.fetchall()
        market_result_count = total_products
        market_page_num = page
        market_total_pages = total_pages

    # Friends panel HTML
    pending_html = ""
    for r in pending_requests:
        requester_phone = html.escape(str(r["requester_phone"]), quote=True)
        requester_profile = f"/portal/feed?active_tab=community&view_profile={requester_phone}"
        pending_html += f"""
        <div id="friend-request-{r['id']}" data-friend-request-id="{r['id']}" style="background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.25); border-radius:10px; padding:12px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap;">
            <a href="{requester_profile}" style="font-weight:600; color:#f1f5f9; text-decoration:none;">{html.escape(r['requester_name'] or '')}</a>
            <div style="display:flex; gap:6px; flex-wrap:wrap;">
                <a href="{requester_profile}" style="background:rgba(59,130,246,0.2); border:1px solid rgba(59,130,246,0.4); color:#93c5fd; font-size:12px; font-weight:700; padding:6px 12px; border-radius:8px; text-decoration:none;">👤 View Profile</a>
                <form action="/portal/friend/accept" method="post" style="margin:0;">
                    <input type="hidden" name="requester_phone" value="{requester_phone}">
                    <button type="submit" class="btn btn-emerald" style="padding:6px 12px; font-size:12px;">Accept</button>
                </form>
                <form action="/portal/friend/reject" method="post" style="margin:0;">
                    <input type="hidden" name="requester_phone" value="{requester_phone}">
                    <button type="submit" class="btn btn-danger" style="padding:6px 12px; font-size:12px;">Reject</button>
                </form>
            </div>
        </div>"""
    pending_request_count = len(pending_requests)
    if not pending_html:
        pending_html = '<p style="color:var(--text-muted); font-size:13px; margin:0;">No new friend requests right now.</p>'
    pending_requests_panel = f"""
    <div id="friend-requests-panel" class="portal-card" style="margin-bottom:20px; border:1px solid rgba(245,158,11,0.35);">
        <div class="card-header" style="justify-content:space-between;">
            <h3 class="card-title" style="color:#fbbf24;">👋 Friend Requests</h3>
            <span id="friend-request-count" style="background:rgba(245,158,11,0.2); color:#fbbf24; border-radius:999px; padding:4px 10px; font-weight:800;">{pending_request_count}</span>
        </div>
        <p style="font-size:13px; color:#cbd5e1; margin:0 0 12px;">Requests from other farmers appear here. Accept to add them to your friends.</p>
        <div id="pending-friend-request-list">{pending_html}</div>
    </div>"""
    pending_request_badge = (
        f'<span id="friend-request-tab-badge" style="display:inline-block;background:#ef4444;color:white;font-size:11px;font-weight:800;padding:2px 7px;border-radius:10px;margin-left:6px;">{pending_request_count}</span>'
        if pending_request_count else
        '<span id="friend-request-tab-badge" style="display:none;background:#ef4444;color:white;font-size:11px;font-weight:800;padding:2px 7px;border-radius:10px;margin-left:6px;">0</span>'
    )

    friends_html = ""
    friend_suggestion_options = ""
    for fr in my_friends:
        friend_suggestion_options += (
            f'<option value="{html.escape(str(fr["friend_phone"]), quote=True)}" '
            f'label="{html.escape(fr["friend_name"] or "", quote=True)}"></option>'
        )
        friend_profile_url = (
            f"/portal/feed?active_tab=community&view_profile="
            f"{html.escape(str(fr['friend_phone']), quote=True)}"
        )
        friends_html += f"""
        <div style="padding:10px 12px; background:rgba(16,185,129,0.06); border-radius:8px; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center;">
            <a href="{friend_profile_url}" style="font-weight:600; color:#f1f5f9; text-decoration:none;">{html.escape(fr['friend_name'] or '')} <span title="Verified" style="color:#34d399;">✅</span></a>
            <a href="/portal/chat?with={fr['friend_phone']}" style="font-size:12px; color:#93c5fd; text-decoration:none; background:rgba(59,130,246,0.15); padding:6px 12px; border-radius:8px; border:1px solid rgba(59,130,246,0.3);">💬 Message</a>
        </div>"""
    if not friends_html:
        friends_html = '<p style="color:var(--text-muted); font-size:13px;">No friends yet. Add some from your neighbors!</p>'
    friends_tab_content = f"""
        {pending_requests_panel}
        <div class="portal-card" style="grid-column:1 / -1;">
            <div class="card-header">🤝 <h3 class="card-title">My Friends</h3></div>
            <p style="font-size:13px;color:#cbd5e1;margin:0 0 12px;">View accepted friends or open their profiles.</p>
            {friends_html}
        </div>"""

    trust_groups_html = ""
    pending_trust_group_invites_html = ""
    for invite in pending_trust_group_invites:
        pending_trust_group_invites_html += f"""
        <div style="background:rgba(59,130,246,.08); border:1px solid rgba(59,130,246,.25); border-radius:10px; padding:12px; margin:8px 0;">
            <div style="font-weight:700; color:#f1f5f9;">Invitation to {html.escape(invite["name"])}</div>
            <div style="font-size:12px; color:#94a3b8; margin-top:4px;">From <a href="/portal/feed?active_tab=community&view_profile={html.escape(str(invite['owner_phone']), quote=True)}" style="color:#cbd5e1;text-decoration:none;">{html.escape(invite["owner_name"] or "a friend")}</a>. Accept to receive this group's travel alerts and check-ins.</div>
            <div style="display:flex; gap:8px; margin-top:10px;">
                <form action="/portal/trust-groups/respond" method="post" style="margin:0;">
                    <input type="hidden" name="group_id" value="{invite["id"]}">
                    <input type="hidden" name="decision" value="accept">
                    <button type="submit" class="btn btn-emerald" style="padding:8px 12px; font-size:12px;">Accept</button>
                </form>
                <form action="/portal/trust-groups/respond" method="post" style="margin:0;">
                    <input type="hidden" name="group_id" value="{invite["id"]}">
                    <input type="hidden" name="decision" value="reject">
                    <button type="submit" class="btn btn-danger" style="padding:8px 12px; font-size:12px;">Reject</button>
                </form>
            </div>
        </div>"""
    whatsapp_delivery_note = (
        "WhatsApp delivery is enabled for this app."
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN
        else "WhatsApp delivery is not configured yet; group updates will still appear here."
    )
    for group in trust_groups:
        group_id = group["id"]
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("""
                SELECT f.phone, f.name, tgm.whatsapp_enabled
                FROM trust_group_members tgm
                JOIN farmers f ON f.phone = tgm.farmer_phone
                WHERE tgm.group_id = ? AND tgm.membership_status = 'accepted'
                ORDER BY f.name COLLATE NOCASE
            """, (group_id,)) as cursor:
                group_members = await cursor.fetchall()
            async with conn.execute("""
                SELECT t.id, t.farmer_phone, t.destination, t.note, t.started_at, f.name
                FROM trust_trips t
                JOIN farmers f ON f.phone = t.farmer_phone
                WHERE t.group_id = ? AND t.status = 'active'
                ORDER BY t.id DESC
            """, (group_id,)) as cursor:
                active_trips = await cursor.fetchall()

            async with conn.execute(
                "SELECT farmer_phone FROM trust_group_members WHERE group_id = ?",
                (group_id,)
            ) as cursor:
                group_member_phones = {row["farmer_phone"] for row in await cursor.fetchall()}
            current_group_member = next(
                (member for member in group_members if member["phone"] == current_user["phone"]),
                None
            )
            addable_friends = [
                friend for friend in my_friends
                if friend["friend_phone"] not in group_member_phones
            ]
            whatsapp_enabled = bool(current_group_member and current_group_member["whatsapp_enabled"])
            whatsapp_toggle_html = f"""
            <form action="/portal/trust-groups/whatsapp" method="post" style="margin:8px 0;">
                <input type="hidden" name="group_id" value="{group_id}">
                <input type="hidden" name="enabled" value="{'false' if whatsapp_enabled else 'true'}">
                <button type="submit" class="btn" style="padding:7px 10px; font-size:12px; background:rgba(37,211,102,.12); color:#86efac;">
                    {'🔕 Turn off WhatsApp alerts' if whatsapp_enabled else '📲 Enable WhatsApp alerts for me'}
                </button>
                <span style="font-size:11px; color:#94a3b8;">Only you control WhatsApp alerts to your number.</span>
            </form>""" if current_group_member else ""
            if group["owner_phone"] == current_user["phone"]:
                if addable_friends:
                    friend_options = "".join(
                        f'<option value="{html.escape(str(friend["friend_phone"]), quote=True)}">'
                        f'{html.escape(friend["friend_name"] or "")}</option>'
                        for friend in addable_friends
                    )
                    add_member_html = f"""
                    <form action="/portal/trust-groups/add-member" method="post" style="display:flex; gap:8px; margin:10px 0; align-items:center; flex-wrap:wrap;">
                        <input type="hidden" name="group_id" value="{group_id}">
                        <select name="friend_phone" required style="flex:1; min-width:160px; padding:9px; font-size:14px;">
                            <option value="">Invite an accepted friend…</option>{friend_options}
                        </select>
                        <button type="submit" class="btn btn-blue" style="padding:9px 12px; font-size:12px;">Send invitation</button>
                    </form>"""
                else:
                    add_member_html = '<p style="font-size:12px; color:#94a3b8; margin:8px 0;">Only the group creator can add members.</p>'
            else:
                add_member_html = ""

            trips_html = ""
            for trip in active_trips:
                async with conn.execute("""
                    SELECT f.phone, f.name, tc.timestamp, tc.xp_awarded
                    FROM trust_trip_checkins tc
                    JOIN farmers f ON f.phone = tc.farmer_phone
                    WHERE tc.trip_id = ?
                    ORDER BY tc.id DESC LIMIT 10
                """, (trip["id"],)) as cursor:
                    trip_checkins = await cursor.fetchall()
                checkin_rows = "".join(
                    f'<div style="font-size:12px; color:#cbd5e1; padding:4px 0;">'
                    f'✅ <a href="/portal/feed?active_tab=community&view_profile={html.escape(str(row["phone"]), quote=True)}" style="color:#cbd5e1;font-weight:700;text-decoration:none;">{html.escape(row["name"] or "")}</a> is OK '
                    f'<span style="color:#94a3b8;">· {html.escape(row["timestamp"])}'
                    f'{" · +5 XP" if row["xp_awarded"] else ""}</span></div>'
                    for row in trip_checkins
                ) or '<div style="font-size:12px; color:#94a3b8;">No check-ins yet.</div>'
                trip_actions = ""
                if trip["farmer_phone"] == current_user["phone"]:
                    trip_actions = f"""
                    <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;">
                        <form action="/portal/trust-groups/check-in" method="post" style="margin:0;">
                            <input type="hidden" name="trip_id" value="{trip['id']}">
                            <button type="submit" class="btn btn-emerald" style="padding:9px 14px; font-size:13px;">✅ I'm OK</button>
                        </form>
                        <form action="/portal/trust-groups/finish-trip" method="post" style="margin:0;">
                            <input type="hidden" name="trip_id" value="{trip['id']}">
                            <button type="submit" class="btn" style="padding:9px 14px; font-size:13px; background:rgba(255,255,255,.08); color:#e2e8f0;">Finish trip</button>
                        </form>
                    </div>"""
                trips_html += f"""
                <div style="background:rgba(16,185,129,.06); border:1px solid rgba(16,185,129,.2); border-radius:10px; padding:12px; margin-top:10px;">
                    <div style="font-weight:700; color:#f1f5f9;">🚗 <a href="/portal/feed?active_tab=community&view_profile={html.escape(str(trip['farmer_phone']), quote=True)}" style="color:inherit;text-decoration:none;">{html.escape(trip["name"] or "")}</a> is travelling to {html.escape(trip["destination"])}</div>
                    <div style="font-size:11px; color:#94a3b8; margin-top:4px;">Started {html.escape(trip["started_at"])}</div>
                    {f'<div style="font-size:13px; color:#cbd5e1; margin-top:6px;">{html.escape(trip["note"] or "")}</div>' if trip["note"] else ''}
                    <div style="margin-top:8px;">{checkin_rows}</div>
                    {trip_actions}
                </div>"""
            if not trips_html:
                trips_html = '<p style="font-size:13px; color:#94a3b8;">No active travel alerts in this group.</p>'

            members_html = ", ".join(
                f'<a href="/portal/feed?active_tab=community&view_profile={html.escape(str(member["phone"]), quote=True)}" '
                f'style="color:#e2e8f0;text-decoration:none;">{html.escape(member["name"] or "")}</a>'
                for member in group_members
            )
            trip_form_html = f"""
            <form action="/portal/trust-groups/travel" method="post" style="border-top:1px solid rgba(255,255,255,.08); padding-top:10px; margin-top:10px;">
                <input type="hidden" name="group_id" value="{group_id}">
                <label style="font-size:12px; margin:0 0 6px;">Starting a trip? Alert this group</label>
                <input type="text" name="destination" maxlength="120" placeholder="Where are you travelling?" required style="padding:9px; font-size:14px; margin-bottom:8px;">
                <input type="text" name="note" maxlength="240" placeholder="Optional details or estimated arrival" style="padding:9px; font-size:14px; margin-bottom:8px;">
                <button type="submit" class="btn btn-blue" style="padding:9px 14px; font-size:13px;">🚗 Start travel alert</button>
            </form>"""
            trust_groups_html += f"""
            <div style="background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.1); border-radius:12px; padding:14px; margin:10px 0;">
                <div style="font-weight:800; color:#f1f5f9; font-size:16px;">🛡️ {html.escape(group["name"])}</div>
                <div style="font-size:12px; color:#94a3b8; margin-top:4px;">Members: {members_html}</div>
                {whatsapp_toggle_html}
                {add_member_html}
                {trips_html}
                {trip_form_html}
            </div>"""
    if not trust_groups_html:
        trust_groups_html = '<p style="font-size:13px; color:#94a3b8;">Create a group and invite accepted friends. They must accept before receiving travel alerts.</p>'

    # Profile viewer: accepted friends can see and reply to each other's statuses.
    profile_card_html = ""
    profile_status_html = ""
    profile_shoutouts_html = ""
    profile_page_mode = False
    if view_profile:
        clean_view = normalize_nigerian_mobile(view_profile) or clean_phone(view_profile)
        alternate_view = None
        if clean_view.startswith("0") and len(clean_view) == 11:
            alternate_view = "234" + clean_view[1:]
        elif clean_view.startswith("234") and len(clean_view) == 13:
            alternate_view = "0" + clean_view[3:]
        guarded_profile = False
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            if clean_view != current_user["phone"] and await guard_status(
                conn, current_user["phone"], clean_view
            ):
                guarded_profile = True
                prof = None
            else:
                async with conn.execute(
                    "SELECT * FROM farmers WHERE phone IN (?, ?) AND COALESCE(is_demo, 0) = 0",
                    (clean_view, alternate_view or clean_view)
                ) as cur:
                    prof = await cur.fetchone()
            can_view_profile = bool(prof and prof["phone"] == current_user["phone"])
            is_accepted_friend = False
            if prof and not can_view_profile:
                async with conn.execute("""
                    SELECT status FROM friendships
                    WHERE (requester_phone = ? AND receiver_phone = ?)
                       OR (requester_phone = ? AND receiver_phone = ?)
                """, (current_user["phone"], prof["phone"], prof["phone"], current_user["phone"])) as cur:
                    relationship = await cur.fetchone()
                relation_status = relationship["status"] if relationship else None
                can_view_profile = relation_status in ("accepted", "pending")
                is_accepted_friend = relation_status == "accepted"
            if prof and can_view_profile and (is_accepted_friend or prof["phone"] == current_user["phone"]) and prof["status"] == STATUS_APPROVED:
                profile_page_mode = True
                async with conn.execute("""
                    SELECT s.id, s.author_phone, s.author_name, s.content, s.timestamp,
                           s.image_path, f.avatar_path,
                           (SELECT COUNT(*) FROM status_likes WHERE status_id = s.id) as likes,
                           (SELECT COUNT(*) FROM status_comments WHERE status_id = s.id) as comments
                    FROM statuses s
                    JOIN farmers f ON f.phone = s.author_phone
                    WHERE s.author_phone = ?
                      AND s.id NOT IN (SELECT status_id FROM status_hides WHERE user_phone = ?)
                    ORDER BY s.id DESC LIMIT 50
                """, (prof["phone"], current_user["phone"])) as cur:
                    prof_statuses = await cur.fetchall()
                prof_comments_map = {}
                if prof_statuses:
                    prof_status_ids = [status["id"] for status in prof_statuses]
                    placeholders = ",".join("?" * len(prof_status_ids))
                    async with conn.execute(
                        f"""SELECT status_id, author_phone, author_name, text FROM status_comments
                            WHERE status_id IN ({placeholders}) ORDER BY id ASC""",
                        prof_status_ids
                    ) as cur:
                        for comment in await cur.fetchall():
                            prof_comments_map.setdefault(comment["status_id"], []).append(comment)
                profile_status_html = "".join(
                    render_status_card(status, prof_comments_map.get(status["id"], []))
                    for status in prof_statuses
                )
                async with conn.execute(
                    """SELECT * FROM shoutouts WHERE farmer_phone = ?
                       ORDER BY id DESC LIMIT 30""",
                    (prof["phone"],),
                ) as cur:
                    prof_shoutouts = await cur.fetchall()
                profile_shoutouts_html = "".join(
                    render_shoutout_card(
                        shoutout, current_user["phone"], id_prefix="profile-"
                    )
                    for shoutout in prof_shoutouts
                )
                if not profile_status_html and not profile_shoutouts_html:
                    profile_status_html = '<p style="color:var(--text-muted); font-size:13px;">No statuses or shout-outs posted yet.</p>'
                elif not profile_status_html:
                    profile_status_html = '<p style="color:var(--text-muted); font-size:13px;">No statuses posted yet.</p>'
                elif not profile_shoutouts_html:
                    profile_shoutouts_html = '<p style="color:var(--text-muted); font-size:13px;">No shout-outs posted yet.</p>'
        if prof:
            if not can_view_profile:
                profile_card_html = '<div style="color:#fbbf24; padding:12px;">You can view this profile after they accept your friend request.</div>'
            else:
                profile_avatar_path = os.path.basename(str(prof["avatar_path"] or ""))
                profile_avatar_html = (
                    f'<img src="/media/{html.escape(profile_avatar_path, quote=True)}" alt="" '
                    'style="width:72px;height:72px;border-radius:50%;object-fit:cover;margin-right:12px;">'
                    if profile_avatar_path else ""
                )
                profile_card_html = f"""
                <div id="profile-header" style="background:linear-gradient(145deg,rgba(74,18,40,.92),rgba(40,12,30,.96));border:1px solid rgba(190,72,112,.38);border-radius:18px;padding:22px;margin-bottom:16px;box-shadow:0 16px 40px rgba(0,0,0,.3);">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <div style="display:flex;align-items:center;font-weight:800;font-size:18px;color:#fff;">{profile_avatar_html}{html.escape(prof['name'] or '')} {'✅' if prof['status']=='Approved' else ''}</div>
                        <a href="/portal/feed?active_tab=community" style="color:#94a3b8; font-size:12px; text-decoration:none;">✕ Close</a>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; font-size:14px;">
                        <div><span style="color:#94a3b8;">Phone</span><br><b style="color:#e2e8f0; font-family:monospace;">{mask_phone_number(prof['phone'])}</b></div>
                        <div><span style="color:#94a3b8;">Status</span><br><b style="color:#e2e8f0;">{html.escape(prof['status'] or '')}</b></div>
                        <div><span style="color:#94a3b8;">LGA / Sector</span><br><b style="color:#e2e8f0;">{html.escape(prof['lga'] or '')}</b></div>
                        <div><span style="color:#94a3b8;">Area</span><br><b style="color:#e2e8f0;">{html.escape(prof['area'] or '')}</b></div>
                        <div><span style="color:#94a3b8;">State</span><br><b style="color:#e2e8f0;">{html.escape(prof['state'] or '')}</b></div>
                        <div><span style="color:#94a3b8;">Grid XP</span><br><b style="color:#fbbf24;">⚡ {prof['xp'] or 0}</b></div>
                    </div>
                    <p style="font-size:12px; color:#e7b5c5; margin:12px 0 0 0;">You are viewing {html.escape(prof['name'] or 'this farmer')}'s profile. Their wall is shared with accepted friends.</p>
                </div>"""
        elif guarded_profile:
            profile_card_html = '<div style="color:#cbd5e1;padding:12px;">This profile is not available.</div>'
        else:
            profile_card_html = '<div style="color:#f87171; padding:12px;">Profile not found.</div>'

    my_spotify_options = ""
    my_spotify_list_html = ""

    leaderboard_html = ""
    for i, row in enumerate(leaderboard_rows):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
        is_me = row["phone"] == current_user["phone"]
        name_style = "color:#6ee7b7; font-weight:800;" if is_me else "color:#e2e8f0; font-weight:600;"
        leaderboard_html += f"""
        <div style="display:flex; align-items:center; gap:10px; padding:10px 0; border-bottom:1px solid rgba(255,255,255,0.05);">
            <span style="width:28px; text-align:center; font-size:16px;">{medal}</span>
            <a href="/portal/feed?active_tab=community&view_profile={html.escape(str(row['phone']), quote=True)}" style="flex:1; font-size:15px; text-decoration:none; {name_style}">{html.escape(row['name'] or 'Farmer')}{" (you)" if is_me else ""}</a>
            <span style="font-size:14px; color:#fbbf24; font-weight:700;">⚡ {row['xp']} XP</span>
        </div>"""
    if not leaderboard_html:
        leaderboard_html = '<p style="color:var(--text-muted); font-size:13px;">No ranked farmers yet.</p>'

    # Compact ticker text for tip / check-in / leaderboard
    checkin_bit = "Checked in today" if checked_in_today else f"Daily check-in available (+{CHECKIN_XP} XP)"
    ticker_text = f"🌤️ {weather['temp']} · {weather['desc']} · Humidity {weather['humidity']} · Wind {weather['wind']}   •   💡 Tip: {tip_of_day}   •   ✅ {checkin_bit}   •   🏆 Top: "
    top_names_html = " · ".join(
        f'<a href="/portal/feed?active_tab=community&view_profile={html.escape(str(row["phone"]), quote=True)}" style="color:#cbd5e1;text-decoration:none;">{html.escape(row["name"] or "Farmer")} ({row["xp"]} XP)</a>'
        for row in list(leaderboard_rows)[:3]
    ) or "No rankings yet"
    ticker_html = f"{html.escape(ticker_text)}{top_names_html}"

    products_html = ""
    for p in market_products:
        is_demo_listing = bool(p["is_demo"])
        is_mine = p["farmer_phone"] == current_user["phone"]
        is_sold = p["status"] == "Sold"
        actions = ""
        edit_button = ""
        if is_mine:
            edit_button = f"""
            <button type="button" class="edit-product-btn"
                    data-product-id="{p['id']}"
                    data-title="{html.escape(p['title'] or '', quote=True)}"
                    data-category="{html.escape(p['category'] or 'General', quote=True)}"
                    data-price="{html.escape(p['price'] or '', quote=True)}"
                    data-description="{html.escape(p['description'] or '', quote=True)}"
                    data-contact="{html.escape(p['contact_phone'] or '', quote=True)}"
                    onclick="openProductEdit(this)"
                    style="background:rgba(59,130,246,0.18); border:1px solid rgba(59,130,246,0.35); color:#93c5fd; font-size:12px; cursor:pointer; padding:6px 10px; border-radius:6px;">Edit</button>"""
        if is_mine and not is_sold:
            actions = f"""
            {edit_button}
            <form action="/portal/market/sold" method="post" style="display:inline; margin:0;">
                <input type="hidden" name="product_id" value="{p['id']}">
                <button type="submit" style="background:rgba(245,158,11,0.15); border:1px solid rgba(245,158,11,0.3); color:#fbbf24; font-size:12px; cursor:pointer; padding:4px 10px; border-radius:6px;">Mark sold</button>
            </form>
            <form action="/portal/market/remove" method="post" style="display:inline; margin:0;">
                <input type="hidden" name="product_id" value="{p['id']}">
                <button type="submit" style="background:none;border:none;color:#f87171;font-size:12px;cursor:pointer;padding:4px 8px;">Remove</button>
            </form>"""
        elif is_mine:
            actions = f"""
            {edit_button}
            <form action="/portal/market/remove" method="post" style="display:inline; margin:0;">
                <input type="hidden" name="product_id" value="{p['id']}">
                <button type="submit" style="background:none;border:none;color:#f87171;font-size:12px;cursor:pointer;padding:4px 8px;">Remove</button>
            </form>"""

        photo_html = ""
        if p["photo_path"]:
            paths = [x.strip() for x in str(p["photo_path"]).split(",") if x.strip()]
            if paths:
                imgs = []
                for i, path in enumerate(paths[:5]):
                    safe = html.escape(os.path.basename(path))
                    display = "block" if i == 0 else "none"
                    imgs.append(
                        f'<img src="/product-photo/{safe}" alt="product photo" class="prod-photo" data-idx="{i}" '
                        f'style="width:100%; height:180px; object-fit:cover; border-radius:12px; margin:0; display:{display}; background:#1e293b; cursor:pointer;" '
                        f'onclick="openPhoto(this.src)">'
                    )
                nav = ""
                if len(paths) > 1:
                    nav = f'''
                    <div style="display:flex; justify-content:center; gap:10px; margin-top:8px;">
                        <button type="button" onclick="photoPrev(this)" style="padding:6px 12px; background:#334155; color:#fff; border:none; border-radius:8px; cursor:pointer;">← Photo</button>
                        <span class="photo-counter" style="align-self:center; color:#94a3b8; font-size:13px;">1 / {len(paths)}</span>
                        <button type="button" onclick="photoNext(this)" style="padding:6px 12px; background:#334155; color:#fff; border:none; border-radius:8px; cursor:pointer;">Photo →</button>
                    </div>'''
                photo_html = f'<div class="photo-wrap" data-count="{len(paths)}" style="width:100%;"><div style="width:100%; height:180px; overflow:hidden; border-radius:12px;">{"".join(imgs)}</div>{nav}</div>'

        demo_badge = '<span style="background:rgba(245,158,11,0.2); color:#fbbf24; font-size:12px; font-weight:800; padding:4px 10px; border-radius:6px; margin-left:6px;">DEMO — NOT A REAL OFFER</span>' if is_demo_listing else ""
        sold_badge = '<span style="background:rgba(245,158,11,0.2); color:#fbbf24; font-size:12px; font-weight:800; padding:4px 10px; border-radius:6px; margin-left:6px;">SOLD</span>' if is_sold else ""
        pending_badge = '<span style="background:rgba(59,130,246,0.2); color:#93c5fd; font-size:12px; font-weight:800; padding:4px 10px; border-radius:6px; margin-left:6px;">PENDING APPROVAL</span>' if p["status"] == "Pending" else ""
        price_color = "#94a3b8" if is_sold else "#6ee7b7"
        card_opacity = "opacity:0.75;" if is_sold else ""
        contact_raw = "" if is_demo_listing else (p["contact_phone"] or p["farmer_phone"] or "")
        call_btn = ""
        msg_btn = ""
        if contact_raw and not is_sold:
            call_btn = f'<a href="tel:{html.escape(str(contact_raw))}" style="display:inline-block;padding:8px 12px;background:rgba(59,130,246,0.2);border:1px solid rgba(59,130,246,0.4);color:#93c5fd;border-radius:10px;font-size:13px;font-weight:700;text-decoration:none;white-space:nowrap;">📞 Call</a>'
            msg_btn = f'<a href="/portal/chat?with={html.escape(str(p["farmer_phone"] or ""))}" style="display:inline-block;padding:8px 12px;background:rgba(16,185,129,0.2);border:1px solid rgba(16,185,129,0.4);color:#6ee7b7;border-radius:10px;font-size:13px;font-weight:700;text-decoration:none;white-space:nowrap;">💬 Message</a>'

        interest_html = ""
        # "I am interested" button removed — buyers use Call / Message instead.

        # Safe strings for share button (no backslashes in f-string)
        safe_title = html.escape(p['title'] or '').replace("'", "\\'")
        safe_price = html.escape(p['price'] or '').replace("'", "\\'")
        if is_demo_listing:
            safety_html = (
                '<div style="margin-top:14px; padding:12px; background:rgba(245,158,11,0.08); '
                'border:1px solid rgba(245,158,11,0.25); border-radius:10px; color:#fbbf24; '
                'font-size:13px;">Demo listing for testing only. Do not contact or arrange a purchase.</div>'
            )
        else:
            safety_html = f'''
            <div style="margin-top:14px; padding:12px; background:rgba(239,68,68,0.06); border:1px solid rgba(239,68,68,0.2); border-radius:10px;">
                <div style="font-size:12px; color:#f87171; font-weight:700; margin-bottom:8px; text-transform:uppercase; letter-spacing:0.04em;">🔒 Privacy & Safety</div>
                <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
                    <form action="/portal/market/report" method="post" style="margin:0;">
                        <input type="hidden" name="product_id" value="{p['id']}">
                        <input type="hidden" name="reason" value="Scam / suspicious listing">
                        <button type="submit" style="background:rgba(239,68,68,0.25); border:1px solid rgba(239,68,68,0.5); color:#fecaca; font-size:13px; font-weight:700; padding:10px 16px; border-radius:8px; cursor:pointer;">🚩 Report Listing</button>
                    </form>
                    <form action="/portal/block-node" method="post" style="margin:0;">
                        <input type="hidden" name="target_phone" value="{html.escape(str(p['farmer_phone'] or ''))}">
                        <button type="submit" style="background:rgba(239,68,68,0.25); border:1px solid rgba(239,68,68,0.5); color:#fecaca; font-size:13px; font-weight:700; padding:10px 16px; border-radius:8px; cursor:pointer;">🚫 Block Seller</button>
                    </form>
                    <details style="display:inline;">
                        <summary style="background:rgba(59,130,246,0.2); border:1px solid rgba(59,130,246,0.4); color:#93c5fd; font-size:13px; font-weight:700; padding:10px 16px; border-radius:8px; cursor:pointer; list-style:none;">⭐ Review</summary>
                    <form action="/portal/market/review" method="post" style="margin-top:8px; background:rgba(0,0,0,0.2); padding:10px; border-radius:8px;">
                        <input type="hidden" name="product_id" value="{p['id']}">
                        <select name="rating" required style="padding:6px; margin-right:8px; background:#1e293b; color:#fff; border-radius:6px;">
                            <option value="5">★★★★★</option>
                            <option value="4">★★★★</option>
                            <option value="3">★★★</option>
                            <option value="2">★★</option>
                            <option value="1">★</option>
                        </select>
                        <input type="text" name="comment" placeholder="Short comment (optional)" maxlength="300" style="padding:6px; width:180px; background:#1e293b; color:#fff; border:1px solid #475569; border-radius:6px;">
                        <button type="submit" class="btn btn-emerald" style="padding:6px 12px; font-size:12px; margin-left:6px;">Submit</button>
                    </form>
                </details>
            </div>'''

        products_html += f"""
        <div class="product-card" id="product-card-{p['id']}" data-card="{p['id']}" style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:16px; padding:16px; {card_opacity} width:100%; box-sizing:border-box; min-width:0;">
            {photo_html}
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px; flex-wrap:wrap; margin-top:12px;">
                <div style="flex:1; min-width:140px;">
                    <div style="font-size:13px; color:#94a3b8; font-weight:700;">{html.escape(p['category'] or 'General')} · {html.escape(p['lga'] or '')}{demo_badge}{sold_badge}{pending_badge}</div>
                    <div class="prod-title" style="font-size:18px; font-weight:800; color:#f1f5f9; margin-top:6px; line-height:1.3;">{html.escape(p['title'])}</div>
                </div>
                <div style="font-size:18px; font-weight:800; color:{price_color}; white-space:nowrap;">{html.escape(p['price']) if p['price'] else ''}</div>
            </div>
            <p style="font-size:15px; color:#cbd5e1; margin:12px 0; line-height:1.5;">{html.escape(p['description'] or '')}</p>
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; font-size:14px;">
                <span style="color:#94a3b8; min-width:0;">Seller: <a href="/portal/feed?active_tab=community&view_profile={html.escape(str(p['farmer_phone']), quote=True)}" style="color:#e2e8f0;font-weight:700;text-decoration:none;">{html.escape(p['farmer_name'] or '')}</a></span>
                <span style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; max-width:100%;">{call_btn}{msg_btn}{actions}
                    <button type="button" onclick="shareListing('{safe_title}', '{safe_price}')" style="display:inline-block;padding:8px 12px;background:rgba(167,139,250,0.2);border:1px solid rgba(167,139,250,0.4);color:#c4b5fd;border-radius:10px;font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap;">🔗 Share</button>
                </span>
            </div>
            {interest_html}
            {safety_html}
        </div>
        </div>"""
    if not products_html:
        products_html = '''
        <div style="text-align:center; padding:28px 16px;">
            <div style="font-size:36px; margin-bottom:10px;">🔍</div>
            <p style="color:#e2e8f0; font-size:16px; font-weight:600; margin:0 0 8px 0;">Nothing found</p>
            <p style="color:var(--text-muted); font-size:14px; margin:0 0 16px 0;">Try a different search or clear filters.</p>
            <a href="/portal/feed?active_tab=market" class="btn btn-emerald" style="display:inline-block; padding:12px 20px; text-decoration:none;">Show all products</a>
        </div>'''

    category_options = "".join([f'<option value="{c}">{c}</option>' for c in PRODUCT_CATEGORIES]) + '<option value="General">General</option>'
    # Filter chips (preserve search + sort + mine)
    active_cat = market_cat if market_cat in PRODUCT_CATEGORIES else ""
    active_status = market_status if market_status in ("Active", "Sold", "All") else "Active"
    active_sort = market_sort if market_sort in ("newest", "oldest", "title_az", "title_za") else "newest"
    active_q = html.escape((market_q or "").strip()[:80])
    show_mine_only = (market_mine or "").lower() in ("1", "yes", "true")
    q_param = f"&market_q={html.escape((market_q or '').strip()[:80])}" if (market_q or "").strip() else ""
    sort_param = f"&market_sort={active_sort}" if active_sort != "newest" else ""
    mine_param = "&market_mine=1" if show_mine_only else ""

    chip_base = "display:inline-block;padding:12px 16px;border-radius:999px;font-size:15px;font-weight:700;text-decoration:none;margin:0 6px 8px 0;"
    filter_chips = f'<a href="/portal/feed?active_tab=market&market_status={active_status}{q_param}{sort_param}{mine_param}" style="{chip_base}{"background:#10b981;color:#fff;" if not active_cat else "background:rgba(255,255,255,0.08);color:#e2e8f0;"}">All types</a>'
    for c in PRODUCT_CATEGORIES:
        selected = active_cat == c
        filter_chips += f' <a href="/portal/feed?active_tab=market&market_cat={c}&market_status={active_status}{q_param}{sort_param}{mine_param}" style="{chip_base}{"background:#10b981;color:#fff;" if selected else "background:rgba(255,255,255,0.08);color:#e2e8f0;"}">{c}</a>'
    status_chips = ""
    for s, label in (("Active", "For sale"), ("Sold", "Sold"), ("All", "All")):
        selected = active_status == s
        cat_q = f"&market_cat={active_cat}" if active_cat else ""
        status_chips += f' <a href="/portal/feed?active_tab=market&market_status={s}{cat_q}{q_param}{sort_param}{mine_param}" style="{chip_base}{"background:#3b82f6;color:#fff;" if selected else "background:rgba(255,255,255,0.08);color:#e2e8f0;"}">{label}</a>'
    mine_chip = f'<a href="/portal/feed?active_tab=market&market_status={active_status}{"&market_cat="+active_cat if active_cat else ""}{q_param}{sort_param}{"&market_mine=1" if not show_mine_only else ""}" style="{chip_base}{"background:#a78bfa;color:#fff;" if show_mine_only else "background:rgba(255,255,255,0.08);color:#e2e8f0;"}">{"My posts ✓" if show_mine_only else "My posts"}</a>'

    sort_options = [
        ("newest", "Newest first"),
        ("oldest", "Oldest first"),
        ("title_az", "Name A–Z"),
        ("title_za", "Name Z–A"),
    ]
    sort_select_opts = "".join([
        f'<option value="{k}" {"selected" if active_sort == k else ""}>{lab}</option>'
        for k, lab in sort_options
    ])
    hidden_cat = f'<input type="hidden" name="market_cat" value="{active_cat}">' if active_cat else ""
    hidden_status = f'<input type="hidden" name="market_status" value="{active_status}">' if active_status != "Active" else ""
    hidden_mine = '<input type="hidden" name="market_mine" value="1">' if show_mine_only else ""
    has_filters = bool(active_cat or (market_q or "").strip() or show_mine_only or active_status != "Active" or active_sort != "newest")
    result_label = f'{market_result_count} product{"s" if market_result_count != 1 else ""} found · Page {market_page_num} of {market_total_pages}'
    # Build pagination links that preserve current filters
    def page_url(p):
        qs = f"/portal/feed?active_tab=market&market_page={p}"
        if active_cat: qs += f"&market_cat={active_cat}"
        if market_status: qs += f"&market_status={market_status}"
        if active_q: qs += f"&market_q={active_q}"
        if market_sort: qs += f"&market_sort={market_sort}"
        if show_mine_only: qs += "&market_mine=1"
        return qs
    prev_btn = f'<a href="{page_url(market_page_num-1)}" class="btn btn-emerald" style="padding:10px 16px; text-decoration:none;">← Previous</a>' if market_page_num > 1 else '<span style="padding:10px 16px; color:#64748b;">← Previous</span>'
    next_btn = f'<a href="{page_url(market_page_num+1)}" class="btn btn-emerald" style="padding:10px 16px; text-decoration:none;">Next →</a>' if market_page_num < market_total_pages else '<span style="padding:10px 16px; color:#64748b;">Next →</span>'
    pagination_html = f'<div style="display:flex; justify-content:center; align-items:center; gap:16px; margin:20px 0; flex-wrap:wrap;">{prev_btn}<span style="color:#e2e8f0; font-weight:700;">Page {market_page_num} of {market_total_pages}</span>{next_btn}</div>'
    clear_filters_btn = f'<a href="/portal/feed?active_tab=market" style="font-size:14px;color:#f87171;font-weight:700;text-decoration:none;">Clear all filters</a>' if has_filters else ""

    checkins_html = "".join([f"""
        <div style="display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid rgba(255,255,255,0.05); font-size:14px;">
            <a href="/portal/feed?active_tab=community&view_profile={html.escape(str(c['farmer_phone']), quote=True)}" style="color:#e2e8f0; font-weight:600;text-decoration:none;">{html.escape(c['name'])}</a>
            <span style="color:#94a3b8; font-size:12px;">OK · {c['timestamp']}</span>
        </div>""" for c in recent_checkins]) or '<p style="color:var(--text-muted); font-size:13px;">No check-ins yet today. Be the first!</p>'

    shoutouts_html = ""
    for shoutout in recent_shoutouts:
        shoutouts_html += render_shoutout_card(
            shoutout,
            current_user["phone"],
            highlighted=shoutout_posted == shoutout["id"],
        )
    if not shoutouts_html:
        shoutouts_html = '<p style="color:var(--text-muted);font-size:13px;">No shout-outs yet. Create the first celebration card!</p>'

    status_html = "".join(
        render_status_card(
            s, status_comments_map.get(s["id"], []),
            highlighted=status_posted == s["id"],
        )
        for s in status_posts
    )
    if not status_html:
        status_html = '<p style="color:var(--text-muted); font-size:13px;">No statuses yet. Be the first to post!</p>'

    nb_pending = "".join([f"""
        <div style='background:#1e293b; padding:16px; margin:10px 0; border-radius:12px; display:flex; justify-content:space-between; align-items:center;'>
            <div><div style='font-weight:600; color:#fff;'>{n['name']}</div><div style='font-size:12px; color:var(--text-muted);'>{mask_phone_number(n['phone'])}</div></div>
            <form action='/portal/approve-node' method='post' style='margin:0;'><input type='hidden' name='target_phone' value='{n['phone']}'><button type='submit' class='btn btn-emerald' style='padding:8px 16px; font-size:12px; border-radius:8px;'>🔒 Verify Identity</button></form>
        </div>""" for n in pending_neighbors])
    nb_approved_parts = []
    for f in approved_neighbors:
        fphone = f['phone']
        fstatus = friend_status_map.get(fphone)
        if fstatus == 'accepted':
            friend_btn = '<span style="color:#34d399; font-size:12px; font-weight:700;">✅ Friends</span>'
        elif fstatus == 'pending':
            friend_btn = '<span style="color:#fbbf24; font-size:12px; font-weight:700;">⏳ Pending</span>'
        else:
            friend_btn = f"""<form action='/portal/friend/request' method='post' style='margin:0;' onsubmit="return confirm('⚠️ Verify this person first!\\n\\nMake sure you know them or have verified their identity before sending a friend request.\\n\\nContinue?');">
                <input type='hidden' name='target_phone' value='{fphone}'>
                <button type='submit' class='btn' style='padding:6px 12px; font-size:12px; background:rgba(59,130,246,0.2); color:#93c5fd; border:1px solid rgba(59,130,246,0.4);'>👋 Add Friend</button>
            </form>"""
        report_farmer_form = f"""
            <details style="display:inline-block;">
                <summary style="cursor:pointer;color:#fecaca;font-size:12px;">🚩 Report</summary>
                <form action="/portal/flag-node" method="post" style="display:grid;gap:6px;min-width:220px;padding:10px;background:#111827;border-radius:8px;margin-top:6px;">
                    <input type="hidden" name="target_phone" value="{html.escape(str(fphone), quote=True)}">
                    <textarea name="reason" required minlength="5" maxlength="500" placeholder="Reason for report" style="padding:8px;background:#1e293b;color:#fff;border:1px solid #475569;border-radius:8px;"></textarea>
                    <button type="submit" class="btn btn-danger" style="padding:6px 10px;">Submit report</button>
                </form>
            </details>"""
        block_farmer_form = f"""
            <form action="/portal/block-node" method="post" style="margin:0;">
                <input type="hidden" name="target_phone" value="{html.escape(str(fphone), quote=True)}">
                <button type="submit" class="btn btn-danger" style="padding:6px 10px;font-size:12px;">🚫 Send to Guardroom</button>
            </form>"""
        nb_approved_parts.append(f"""
        <div style='padding:12px 16px; background:rgba(16,185,129,0.03); border:1px solid rgba(16,185,129,0.15); border-radius:10px; margin-bottom:8px; display:flex; align-items:center; gap:10px; flex-wrap:wrap;'>
            🟢 <div style='flex:1; min-width:120px;'>
                <a href='/portal/feed?active_tab=community&view_profile={html.escape(str(fphone), quote=True)}' style='font-weight:600; color:#f1f5f9; text-decoration:none;'>{html.escape(f['name'] or '')}</a>
                <span title="Verified & Approved" style="color:#34d399; font-size:14px; margin-left:6px;">✅</span>
            </div>
            {friend_btn}
            {report_farmer_form}
            {block_farmer_form}
            <span style='font-size:11px; color:var(--accent-emerald); background:rgba(16,185,129,0.1); padding:2px 8px; border-radius:4px;'>Verified</span>
        </div>""")
    nb_approved = "".join(nb_approved_parts)

    # --- Direct Messages / Peer Lookup logic ---
    peer_card_html = ""
    messages_log_html = ""
    send_form_html = ""
    safety_notice = ""
    clean_search = ""
    guarded_search = False
    if search_phone:
        normalized = normalize_nigerian_mobile(search_phone)
        if normalized:
            clean_search = normalized
        else:
            peer_card_html = """
            <div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.25); border-radius:10px; padding:14px 16px; margin-bottom:14px; font-size:13px; color:#f87171; text-align:center;">
                Invalid phone number. Please enter a valid Nigerian mobile<br>
                (070 / 080 / 081 / 090 / 091 — 11 digits, or with 234 country code).
            </div>"""

    # Guaranteed friend chat: if we came from the friends list, always show a working interface
    if friend_name and search_phone:
        clean_target = normalize_nigerian_mobile(search_phone) or clean_phone(search_phone)
        peer_card_html = f"""
        <div style="background:rgba(59,130,246,0.08); border:1px solid rgba(59,130,246,0.25); border-radius:14px; padding:18px; margin-bottom:16px;">
            <div style="font-weight:800; font-size:20px; color:#fff; margin-bottom:6px;"><a href="/portal/feed?active_tab=community&view_profile={html.escape(str(clean_target), quote=True)}" style="color:inherit;text-decoration:none;">{html.escape(friend_name)}</a> ✅</div>
            <div style="font-size:13px; color:var(--text-muted); font-family:monospace;">{mask_phone_number(clean_target)}</div>
        </div>"""
        # Load any existing messages
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            my_phone = current_user["phone"]
            # Try both phone formats
            alts = {clean_target}
            if clean_target.startswith("0") and len(clean_target) == 11:
                alts.add("234" + clean_target[1:])
            elif clean_target.startswith("234") and len(clean_target) == 13:
                alts.add("0" + clean_target[3:])
            placeholders = ",".join("?" * len(alts))
            async with conn.execute(f"""
                SELECT * FROM direct_messages
                WHERE (sender_phone = ? AND receiver_phone IN ({placeholders}))
                   OR (receiver_phone = ? AND sender_phone IN ({placeholders}))
                ORDER BY id ASC
            """, (my_phone,) + tuple(alts) + (my_phone,) + tuple(alts)) as mcur:
                msgs = await mcur.fetchall()
            for m in msgs:
                is_mine = m["sender_phone"] == my_phone
                align = "flex-end" if is_mine else "flex-start"
                bg = "rgba(16,185,129,0.18)" if is_mine else "rgba(255,255,255,0.06)"
                messages_log_html += f"""
                <div style="display:flex; justify-content:{align}; margin-bottom:10px;">
                    <div style="max-width:78%; background:{bg}; padding:10px 14px; border-radius:12px;">
                        <div style="font-size:13px; color:#f1f5f9;">{html.escape(m['body'])}</div>
                        <div style="font-size:10px; color:var(--text-muted); margin-top:4px;">{m['timestamp']}</div>
                    </div>
                </div>"""
        send_form_html = f"""
        <form action="/portal/messages/send" method="post" style="display:flex; gap:10px; margin-top:12px; align-items:center; background:rgba(0,0,0,0.2); padding:12px; border-radius:12px;">
            <input type="hidden" name="receiver_phone" value="{clean_target}">
            <input type="text" name="body" placeholder="Type a message to {html.escape(friend_name)}..." required autocomplete="off" maxlength="{MAX_MESSAGE_LENGTH}"
                   style="flex:1; padding:14px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px;">
            <button type="submit" class="btn btn-emerald" style="padding:14px 24px; font-size:16px; cursor:pointer;">Send</button>
        </form>
        <p style="font-size:12px; color:#94a3b8; margin:8px 0 0 0;">Press Send to deliver your message.</p>"""
        # Skip the complex lookup below
        clean_search = ""

    if clean_search:
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            peer = None
            async with conn.execute("SELECT * FROM farmers WHERE phone = ? AND COALESCE(is_demo, 0) = 0", (clean_search,)) as cur:
                peer = await cur.fetchone()
            if not peer and clean_search.startswith("0") and len(clean_search) == 11:
                alt = "234" + clean_search[1:]
                async with conn.execute("SELECT * FROM farmers WHERE phone = ? AND COALESCE(is_demo, 0) = 0", (alt,)) as cur:
                    peer = await cur.fetchone()
                if peer:
                    clean_search = peer["phone"]
            elif not peer and clean_search.startswith("234") and len(clean_search) == 13:
                alt = "0" + clean_search[3:]
                async with conn.execute("SELECT * FROM farmers WHERE phone = ? AND COALESCE(is_demo, 0) = 0", (alt,)) as cur:
                    peer = await cur.fetchone()
                if peer:
                    clean_search = peer["phone"]

            if peer:
                guarded_search = bool(await guard_status(conn, current_user["phone"], peer["phone"]))
                if guarded_search:
                    peer = None
            if peer:
                my_phone = current_user["phone"]
                peer_phone = peer["phone"]
                same_lga = peer["lga"] == current_user["lga"]
                # Check friendship
                is_friend = False
                # Normalize both phone formats for friendship check
                def phone_alts(ph):
                    alts = {ph}
                    if ph.startswith("0") and len(ph) == 11:
                        alts.add("234" + ph[1:])
                    elif ph.startswith("234") and len(ph) == 13:
                        alts.add("0" + ph[3:])
                    return alts
                my_alts = phone_alts(my_phone)
                peer_alts = phone_alts(peer_phone)
                async with conn.execute("""
                    SELECT 1 FROM friendships
                    WHERE status = 'accepted'
                      AND ((requester_phone IN ({}) AND receiver_phone IN ({}))
                        OR (requester_phone IN ({}) AND receiver_phone IN ({})))
                """.format(
                    ",".join("?" * len(my_alts)),
                    ",".join("?" * len(peer_alts)),
                    ",".join("?" * len(peer_alts)),
                    ",".join("?" * len(my_alts))
                ), tuple(my_alts) + tuple(peer_alts) + tuple(peer_alts) + tuple(my_alts)) as fcur:
                    if await fcur.fetchone():
                        is_friend = True
                # If user came from the friends list, they are already friends
                if friend_name:
                    is_friend = True
                can_message = is_friend  # Messaging only after friend request is accepted
                status_badge_class = "badge-emerald" if peer["status"] == STATUS_APPROVED else "badge-amber"

                # Check block status (either direction)
                async with conn.execute("""
                    SELECT blocker_phone FROM blocked_nodes
                    WHERE (blocker_phone = ? AND blocked_phone = ?)
                       OR (blocker_phone = ? AND blocked_phone = ?)
                """, (my_phone, peer_phone, peer_phone, my_phone)) as cur:
                    block_row = await cur.fetchone()
                i_blocked_them = False
                they_blocked_me = False
                if block_row:
                    if block_row["blocker_phone"] == my_phone:
                        i_blocked_them = True
                    else:
                        they_blocked_me = True

                # Peer profile card
                block_btn = ""
                if i_blocked_them:
                    block_btn = f"""
                    <form action="/portal/unblock-node" method="post" style="margin:0;">
                        <input type="hidden" name="target_phone" value="{peer_phone}">
                        <button type="submit" class="btn" style="padding:6px 12px; font-size:12px; background:rgba(16,185,129,0.15); color:#34d399; border:1px solid rgba(16,185,129,0.3);">Unblock</button>
                    </form>"""
                else:
                    block_btn = f"""
                    <form action="/portal/block-node" method="post" style="margin:0;">
                        <input type="hidden" name="target_phone" value="{peer_phone}">
                        <button type="submit" class="btn btn-danger" style="padding:6px 12px; font-size:12px;">Block</button>
                    </form>"""

                # Prominent privacy controls
                report_btn = f"""
                <details>
                    <summary style="background:rgba(239,68,68,0.2); border:1px solid rgba(239,68,68,0.5); color:#fecaca; font-size:13px; font-weight:700; padding:10px 16px; border-radius:8px; cursor:pointer; list-style:none;">🚩 Report farmer</summary>
                    <form action="/portal/flag-node" method="post" style="display:grid;gap:8px;margin-top:8px;padding:12px;background:rgba(0,0,0,.24);border-radius:10px;">
                        <input type="hidden" name="target_phone" value="{html.escape(str(peer_phone), quote=True)}">
                        <label style="font-size:12px;color:#cbd5e1;">Reason for report
                            <textarea name="reason" required minlength="5" maxlength="500" placeholder="Describe what happened so our team can review it." style="display:block;width:100%;box-sizing:border-box;margin-top:5px;padding:9px;background:#1e293b;color:#fff;border:1px solid #475569;border-radius:8px;"></textarea>
                        </label>
                        <button type="submit" class="btn btn-danger" style="padding:8px 12px;">Send report</button>
                    </form>
                </details>"""

                # Friend request button
                fstatus = friend_status_map.get(peer_phone)
                if is_friend or fstatus == 'accepted':
                    friend_request_btn = '<span style="color:#34d399; font-weight:700; font-size:13px;">✅ Already friends</span>'
                elif fstatus == 'pending':
                    friend_request_btn = '<span style="color:#fbbf24; font-weight:700; font-size:13px;">⏳ Pending friend request</span>'
                else:
                    friend_request_btn = (
                        f'<form action="/portal/friend/request" method="post" style="margin:0;" '
                        f'onsubmit="return confirm(\'⚠️ Verify this person first! Make sure you know them before sending a friend request. Continue?\');">'
                        f'<input type="hidden" name="target_phone" value="{peer_phone}">'
                        f'<button type="submit" class="btn btn-emerald" style="padding:8px 16px; font-size:13px;">👋 Send Friend Request</button>'
                        f'</form>'
                    )

                peer_card_html = f"""
                <div style="background:rgba(59,130,246,0.08); border:1px solid rgba(59,130,246,0.25); border-radius:14px; padding:18px; margin-bottom:16px;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap;">
                        <div>
                            <div style="font-weight:800; font-size:20px; color:#fff; margin-bottom:6px;"><a href="/portal/feed?active_tab=community&view_profile={html.escape(str(peer_phone), quote=True)}" style="color:inherit;text-decoration:none;">{html.escape(peer['name'])}</a> {'✅' if peer['status']=='Approved' else ''}</div>
                            <div style="font-size:13px; color:var(--text-muted);">LGA Sector: <b>{html.escape(peer['lga'])}</b></div>
                            <div style="font-size:13px; color:var(--text-muted); margin-top:4px;">
                                Status: <span class="badge {status_badge_class}">{html.escape(peer['status'])}</span>
                            </div>
                            <div style="font-size:12px; color:var(--text-muted); margin-top:6px; font-family:monospace;">
                                {mask_phone_number(peer_phone)}
                            </div>
                        </div>
                    </div>
                    <div style="margin-top:14px; display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
{friend_request_btn}
                    </div>
                    <div style="margin-top:14px; padding-top:12px; border-top:1px solid rgba(255,255,255,0.08);">
                        <div style="font-size:12px; color:#f87171; font-weight:700; margin-bottom:8px; text-transform:uppercase; letter-spacing:0.04em;">🔒 Privacy Controls</div>
                        <div style="display:flex; gap:10px; flex-wrap:wrap;">
                            {report_btn}
                            {block_btn}
                        </div>
                    </div>
                </div>"""

                if not can_message:
                    peer_card_html += """
                    <div style="background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.25); border-radius:10px; padding:12px 16px; margin-bottom:14px; font-size:13px; color:#fbbf24;">
                        Send a friend request first. You can message each other after they accept. Phone number stays masked until then.
                    </div>"""
                elif they_blocked_me:
                    peer_card_html += """
                    <div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.25); border-radius:10px; padding:12px 16px; margin-bottom:14px; font-size:13px; color:#f87171;">
                        This node has blocked communication with you.
                    </div>"""
                elif i_blocked_them:
                    peer_card_html += """
                    <div style="background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.2); border-radius:10px; padding:12px 16px; margin-bottom:14px; font-size:13px; color:#f87171;">
                        You have blocked this node. Unblock to resume messaging.
                    </div>"""
                else:
                    # Load conversation
                    # Load messages using both phone formats
                    my_alts_list = list(phone_alts(my_phone))
                    peer_alts_list = list(phone_alts(peer_phone))
                    async with conn.execute("""
                        SELECT * FROM direct_messages
                        WHERE (sender_phone IN ({}) AND receiver_phone IN ({}))
                           OR (sender_phone IN ({}) AND receiver_phone IN ({}))
                        ORDER BY id ASC
                    """.format(
                        ",".join("?" * len(my_alts_list)),
                        ",".join("?" * len(peer_alts_list)),
                        ",".join("?" * len(peer_alts_list)),
                        ",".join("?" * len(my_alts_list))
                    ), tuple(my_alts_list) + tuple(peer_alts_list) + tuple(peer_alts_list) + tuple(my_alts_list)) as mcur:
                        msgs = await mcur.fetchall()

                    for m in msgs:
                        is_mine = m["sender_phone"] == my_phone
                        align = "flex-end" if is_mine else "flex-start"
                        bg = "rgba(16,185,129,0.18)" if is_mine else "rgba(255,255,255,0.06)"
                        actions = f"""
                        <form action="/portal/messages/delete" method="post" style="display:inline; margin:0;">
                            <input type="hidden" name="message_id" value="{m['id']}">
                            <input type="hidden" name="return_phone" value="{peer_phone}">
                            <button type="submit" style="background:none; border:none; color:#f87171; font-size:11px; cursor:pointer; padding:0;">Delete</button>
                        </form>"""
                        if not is_mine:
                            actions += f"""
                            <form action="/portal/messages/report" method="post" style="display:inline; margin-left:10px;">
                                <input type="hidden" name="message_id" value="{m['id']}">
                                <input type="hidden" name="return_phone" value="{peer_phone}">
                                <button type="submit" style="background:none; border:none; color:#fbbf24; font-size:11px; cursor:pointer; padding:0;">Report</button>
                            </form>"""

                        messages_log_html += f"""
                        <div style="display:flex; justify-content:{align}; margin-bottom:10px;">
                            <div style="max-width:78%; background:{bg}; padding:10px 14px; border-radius:12px;">
                                <div style="font-size:13px; color:#f1f5f9;">{m['body']}</div>
                                <div style="font-size:10px; color:var(--text-muted); margin-top:4px; display:flex; gap:12px; align-items:center;">
                                    <span>{m['timestamp']}</span>
                                    {actions}
                                </div>
                            </div>
                        </div>"""

                    send_form_html = f"""
                    <form action="/portal/messages/send" method="post" style="display:flex; gap:10px; margin-top:12px; align-items:flex-start;">
                        <input type="hidden" name="receiver_phone" value="{peer_phone}">
                        <div style="flex:1;">
                            <input type="text" name="body" placeholder="Type your message..." required autocomplete="off" maxlength="{MAX_MESSAGE_LENGTH}"
                                   style="width:100%; padding:12px; background:#090d16; border:1px solid var(--border-glass); color:white; border-radius:10px; box-sizing:border-box;">
                            <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">Max {MAX_MESSAGE_LENGTH} characters</div>
                        </div>
                        <button type="submit" class="btn btn-emerald" style="padding:12px 20px; white-space:nowrap;">Send</button>
                    </form>"""
            elif guarded_search:
                peer_card_html = """
                <div role="status" style="background:rgba(15,23,42,.8);border:1px solid rgba(148,163,184,.25);border-radius:14px;padding:18px;margin-bottom:16px;text-align:center;color:#cbd5e1;">
                    This farmer is not available in search.
                </div>"""
            else:
                peer_card_html = f"""
                <div style="background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.25); border-radius:14px; padding:18px; margin-bottom:16px; text-align:center;">
                    <div style="font-size:28px; margin-bottom:8px;">📱</div>
                    <div style="font-weight:700; color:#f1f5f9; margin-bottom:6px;">Not on Farm Watch yet</div>
                    <div style="font-size:13px; color:var(--text-muted); margin-bottom:14px; font-family:monospace;">{mask_phone_number(clean_search)}</div>
                    <p style="font-size:14px; color:#cbd5e1; margin:0 0 16px 0;">This number is not registered. Send them an invite with the site link.</p>
                    <form action="/portal/invite" method="post" style="margin:0;">
                        <input type="hidden" name="target_phone" value="{clean_search}">
                        <button type="submit" class="btn btn-emerald" style="padding:12px 24px; font-size:15px;">📨 Send Invite</button>
                    </form>
                    <p style="font-size:12px; color:#94a3b8; margin-top:12px;">They will receive a WhatsApp message with the registration link.</p>
                </div>"""

    # Safety notice always shown in the messages tab
    safety_notice = f"""
    <div style="background:rgba(59,130,246,0.07); border:1px solid rgba(59,130,246,0.18); border-radius:12px; padding:14px 16px; margin-bottom:18px; font-size:13px; color:#93c5fd; line-height:1.5;">
        <strong>Community Safety:</strong> Messaging is limited to farmers in the same LGA.
        You can block any node at any time. Repeated reports will automatically restrict a sender.
        Max {MAX_MESSAGES_PER_HOUR_TO_PEER} messages per hour to the same person · {MAX_MESSAGES_PER_DAY} total per day.
    </div>"""

    tab = (active_tab or "incidents").lower()
    is_messages_tab = tab == "messages"
    is_community_tab = tab == "community"
    is_friends_tab = tab == "friends"
    is_shoutouts_tab = tab == "shoutouts"
    is_market_tab = tab == "market"
    is_farm_market_tab = tab == "farm_market"
    is_family_tab = tab == "family"
    is_incidents_tab = tab not in ("messages", "community", "friends", "shoutouts", "market", "farm_market", "family")
    tab_incidents_active = "background:rgba(16,185,129,0.2); color:#10b981;" if is_incidents_tab else "background:transparent; color:var(--text-muted);"
    tab_messages_active = "background:rgba(16,185,129,0.2); color:#10b981;" if is_messages_tab else "background:transparent; color:var(--text-muted);"
    tab_community_active = "background:rgba(16,185,129,0.2); color:#10b981;" if is_community_tab else "background:transparent; color:var(--text-muted);"
    tab_friends_active = "background:rgba(16,185,129,0.2); color:#10b981;" if is_friends_tab else "background:transparent; color:var(--text-muted);"
    tab_shoutouts_active = "background:rgba(16,185,129,0.2); color:#10b981;" if is_shoutouts_tab else "background:transparent; color:var(--text-muted);"
    tab_market_active = "background:rgba(16,185,129,0.2); color:#10b981;" if is_market_tab else "background:transparent; color:var(--text-muted);"
    tab_farm_market_active = "background:rgba(16,185,129,0.2); color:#10b981;" if is_farm_market_tab else "background:transparent; color:var(--text-muted);"
    show_incidents = "display:block;" if is_incidents_tab else "display:none;"
    show_messages = "display:block;" if is_messages_tab else "display:none;"
    show_community = "display:block;" if is_community_tab else "display:none;"
    show_friends = "display:block;" if is_friends_tab else "display:none;"
    show_shoutouts = "display:block;" if is_shoutouts_tab else "display:none;"
    show_market = "display:block;" if is_market_tab else "display:none;"
    show_farm_market = "display:block;" if is_farm_market_tab else "display:none;"
    show_family = "display:block;" if is_family_tab else "display:none;"
    profile_view_styles = """
        body.profile-view {
            min-height:100vh;
            background:radial-gradient(ellipse at top,rgba(107,28,58,.38),transparent 58%),linear-gradient(160deg,#180b13,#10090e 70%,#1d0c16);
        }
        body.profile-view .container { max-width:980px!important; padding-top:72px!important; }
        body.profile-view .portal-header,
        body.profile-view .container > form,
        body.profile-view .tab-bar,
        body.profile-view #tab_incidents,
        body.profile-view #tab_friends,
        body.profile-view #tab_shoutouts,
        body.profile-view #tab_market,
        body.profile-view #tab_farm_market,
        body.profile-view #tab_messages,
        body.profile-view #tab_family { display:none!important; }
        body.profile-view #tab_community { display:block!important; }
        body.profile-view #tab_community > :not(#profile-view) { display:none!important; }
        body.profile-view #profile-view { display:block!important; }
        body.profile-view #profile-view .portal-card,
        body.profile-view #profile-wall [id^="status-"] {
            background:linear-gradient(145deg,rgba(75,20,43,.9),rgba(36,12,28,.96))!important;
            border-color:rgba(190,72,112,.3)!important;
        }
        body.profile-view #profile-wall .shoutout-entry {
            background:linear-gradient(145deg,rgba(90,24,49,.92),rgba(42,13,31,.96))!important;
            border-color:rgba(209,91,130,.4)!important;
        }
    """
    checked_in_btn = "background:#334155; color:#94a3b8; pointer-events:none;" if checked_in_today else ""
    checked_in_label = "Checked in today ✓" if checked_in_today else f"I'm OK (+{CHECKIN_XP} XP)"
    pending_request_badge = (
        f' <span style="background:#f59e0b;color:#111827;border-radius:999px;'
        f'padding:2px 7px;font-size:11px;font-weight:800;">{pending_request_count}</span>'
        if pending_request_count else ""
    )

    echo_feed_html = ""
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        for a in active_threats:
            async with conn.execute("SELECT * FROM alert_comments WHERE alert_id = ? ORDER BY id ASC",
                                    (a['id'],)) as cc:
                comments = await cc.fetchall()
            cm_html = "".join([
                                  f"<div style='background:rgba(255,255,255,0.03); padding:8px 12px; border-radius:8px; margin-top:6px; font-size:13px;'><b style='color:var(--accent-blue);'>{c['author']}:</b> {c['text']}</div>"
                                  for c in comments])
            v_element = f'<div style="margin:12px 0;"><video src="/media/{a["video_path"]}" controls style="max-width:100%; border-radius:8px; border:1px solid rgba(255,255,255,0.1);"></video></div>' if \
            a['video_path'] else ''
            echo_feed_html += f"""
            <div style="background:rgba(255,255,255,0.01); border:1px solid var(--border-glass); padding:20px; border-radius:16px; margin-bottom:16px;">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px; flex-wrap:wrap;">
                    <div><span class="badge badge-blue">📡 {a["type"]}</span><div style="font-size:15px; color:#f1f5f9; font-weight:600; margin:8px 0;">"{a["message"]}"</div><small style="color:var(--text-muted); font-size:11px;">Origin: Transmitted by <b>{a["sender"]}</b></small></div>
                    <form action="/portal/alert/relay" method="post" onsubmit="triggerEchoAnimation(event, {a["id"]})" style="margin:0;"><input type="hidden" name="alert_id" value="{a["id"]}"><button type="submit" id="echo_btn_{a["id"]}" class="btn btn-blue" style="padding:8px 14px; font-size:12px;">🔁 Relay</button></form>
                </div>
                {v_element}
                <div style="margin-top:15px; border-top:1px solid rgba(255,255,255,0.05); padding-top:12px;">
                    <h5 style="margin:0 0 8px 0; font-size:12px; color:var(--text-muted); text-transform:uppercase;">💬 Intel Discussion Updates</h5>
                    {cm_html or '<p style="color:var(--text-muted); font-size:12px; font-style:italic; margin:0;">No updates posted by neighbors yet.</p>'}
                    <form action="/portal/alert/comment" method="post" style="margin-top:10px; display:flex; gap:8px;"><input type="hidden" name="alert_id" value="{a['id']}"><input type="text" name="comment_text" placeholder="Add verification update details..." required style="padding:10px; font-size:13px;"><button type="submit" class="btn btn-emerald" style="padding:0 16px; border-radius:12px; font-size:13px; white-space:nowrap;">Send</button></form>
                </div>
            </div>"""

    family_group_cards = []
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("""
            SELECT fg.*,
                   (SELECT COUNT(*) FROM family_group_members members
                    WHERE members.group_id = fg.id) AS member_count
            FROM family_groups fg
            JOIN family_group_members mine ON mine.group_id = fg.id
            WHERE mine.farmer_phone = ? AND ? = ?
            ORDER BY fg.created_at DESC
        """, (current_user["phone"], current_user.get("status"), STATUS_APPROVED)) as cursor:
            family_groups = await cursor.fetchall()
        for family in family_groups:
            async with conn.execute("""
                SELECT f.phone, f.name FROM family_group_members members
                JOIN farmers f ON f.phone = members.farmer_phone
                WHERE members.group_id = ? AND COALESCE(f.is_demo, 0) = 0
                ORDER BY f.name COLLATE NOCASE LIMIT 30
            """, (family["id"],)) as cursor:
                family_members = await cursor.fetchall()
            async with conn.execute("""
                SELECT author_phone, author_name, body, created_at FROM family_meeting_messages
                WHERE group_id = ? ORDER BY id DESC LIMIT 50
            """, (family["id"],)) as cursor:
                family_messages = await cursor.fetchall()

            message_rows = "".join(
                f'<div style="padding:9px 11px;margin:6px 0;background:rgba(255,255,255,0.04);border-radius:9px;">'
                f'<a href="/portal/feed?active_tab=community&view_profile={html.escape(str(message["author_phone"]), quote=True)}" '
                f'style="color:#6ee7b7;font-weight:700;text-decoration:none;">{html.escape(message["author_name"])}</a>'
                f'<span style="font-size:11px;color:#94a3b8;margin-left:8px;">{html.escape(message["created_at"] or "")}</span>'
                f'<div style="color:#e2e8f0;white-space:pre-wrap;overflow-wrap:anywhere;">{html.escape(message["body"])}</div></div>'
                for message in reversed(family_messages)
            ) or '<p style="color:#94a3b8;text-align:center;">No family messages yet. Send a greeting.</p>'
            member_names = ", ".join(
                f'<a href="/portal/feed?active_tab=community&view_profile={html.escape(str(member["phone"]), quote=True)}" '
                f'style="color:#c4b5fd;text-decoration:none;">{html.escape(member["name"] or "Farmer")}</a>'
                for member in family_members
            )
            code = html.escape(family["invite_code"])
            invite_url = f"/family/invite/{code}"
            name = html.escape(family["name"])
            town = html.escape(family["town"])
            lga = html.escape(family["lga"])
            room_url = f"https://meet.jit.si/OlodeFamily-{family['meeting_room']}"
            rotate_form = ""
            if family["owner_phone"] == current_user["phone"]:
                rotate_form = f"""
                    <form action="/portal/family/rotate-code" method="post" data-auto-refresh style="margin:0;">
                        <input type="hidden" name="group_id" value="{family['id']}">
                        <button class="btn" type="submit" style="padding:8px 11px;background:rgba(245,158,11,.12);color:#fbbf24;border:1px solid rgba(245,158,11,.3);">Renew invite code</button>
                    </form>"""
            family_group_cards.append(f"""
                <article class="portal-card" style="grid-column:1/-1;">
                    <div class="card-header">👨‍👩‍👧‍👦 <h3 class="card-title">{name}</h3></div>
                    <p style="color:#cbd5e1;margin-top:0;">📍 {town}, {lga} · {family['member_count']} member(s)</p>
                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:18px;">
                        <div>
                            <h4 style="color:#c4b5fd;margin:4px 0 8px;">Invite family</h4>
                            <p style="color:#cbd5e1;margin:4px 0;">Invite code: <strong style="color:#fff;font-size:18px;letter-spacing:.08em;">{code}</strong></p>
                            <div style="display:flex;flex-wrap:wrap;gap:8px;margin:12px 0;">
                                <button class="btn btn-emerald" type="button" data-family-name="{html.escape(family['name'], quote=True)}" data-invite-url="{html.escape(invite_url, quote=True)}" onclick="shareFamilyInvite(this)">Share invite</button>
                                <button class="btn" type="button" data-family-name="{html.escape(family['name'], quote=True)}" data-invite-url="{html.escape(invite_url, quote=True)}" onclick="shareFamilyOnSocial('whatsapp', this)" style="padding:8px 11px;background:rgba(16,185,129,.12);color:#6ee7b7;">WhatsApp</button>
                                <button class="btn" type="button" data-family-name="{html.escape(family['name'], quote=True)}" data-invite-url="{html.escape(invite_url, quote=True)}" onclick="shareFamilyOnSocial('facebook', this)" style="padding:8px 11px;background:rgba(59,130,246,.12);color:#93c5fd;">Facebook</button>
                                <button class="btn" type="button" data-family-name="{html.escape(family['name'], quote=True)}" data-invite-url="{html.escape(invite_url, quote=True)}" onclick="shareFamilyOnSocial('x', this)" style="padding:8px 11px;background:rgba(255,255,255,.08);color:#e2e8f0;">X</button>
                                {rotate_form}
                            </div>
                            <img src="/portal/family/qr/{code}" alt="QR code for the {name} family invitation" width="172" height="172" loading="lazy" style="background:#fff;padding:8px;border-radius:10px;">
                            <p style="font-size:12px;color:#94a3b8;">Scan the QR code or share the invitation link. Only approved farmers can join.</p>
                        </div>
                        <div>
                            <a class="btn btn-emerald" href="{room_url}" target="_blank" rel="noopener noreferrer" style="display:inline-block;text-decoration:none;">🎥 Open family video meeting</a>
                            <p style="font-size:12px;color:#fbbf24;line-height:1.5;">Video meetings open on Jitsi, an external service. Anyone with the meeting link may enter, so share it only with family members.</p>
                            <h4 style="color:#c4b5fd;margin:16px 0 6px;">Family members</h4>
                            <p style="color:#cbd5e1;font-size:13px;margin:0 0 14px;">{member_names or 'No members yet'}</p>
                            <h4 style="color:#c4b5fd;margin:0 0 6px;">Family notes and messages</h4>
                            <div style="max-height:230px;overflow:auto;padding:8px;background:rgba(0,0,0,.2);border-radius:10px;">{message_rows}</div>
                            <form action="/portal/family/message" method="post" data-auto-refresh style="display:flex;gap:8px;margin-top:10px;">
                                <input type="hidden" name="group_id" value="{family['id']}">
                                <input type="text" name="body" required maxlength="500" placeholder="Leave a family message..." style="flex:1;min-width:0;">
                                <button class="btn btn-emerald" type="submit">Send</button>
                            </form>
                        </div>
                    </div>
                </article>""")

    family_cards_html = "".join(family_group_cards) or (
        '<div class="portal-card" style="grid-column:1/-1;color:#cbd5e1;">'
        'You have not joined a family meeting yet. Create one or enter an invitation code below.</div>'
    )
    family_create_html = ""
    if current_user.get("status") == STATUS_APPROVED:
        family_create_html = f"""
            <form action="/portal/family/create" method="post" data-auto-refresh style="display:grid;gap:10px;">
                <label for="family_name" style="color:#e2e8f0;font-weight:700;">Family name</label>
                <input id="family_name" name="family_name" required maxlength="80" placeholder="e.g. Adeyemi Family">
                <label for="family_lga" style="color:#e2e8f0;font-weight:700;">LGA</label>
                <input id="family_lga" name="lga" required maxlength="80" value="{html.escape(current_user.get('lga') or '', quote=True)}">
                <label for="family_town" style="color:#e2e8f0;font-weight:700;">Town</label>
                <input id="family_town" name="town" required maxlength="80" value="{html.escape(current_user.get('city') or '', quote=True)}">
                <button class="btn btn-emerald" type="submit">Create family meeting</button>
            </form>"""
    else:
        family_create_html = '<p style="color:#fbbf24;">Approved farmer accounts can create family meetings.</p>'

    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        {UPGRADED_CSS}
        .portal-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 24px; margin-top: 24px; }}
        .products-grid {{
            display: grid !important;
            grid-template-columns: repeat(3, 1fr) !important;
            gap: 16px !important;
            width: 100% !important;
        }}
        .product-card {{
            width: 100% !important;
            min-width: 0 !important;
            box-sizing: border-box !important;
        }}
        .product-card img, .prod-photo {{
            width: 100% !important;
            height: 180px !important;
            max-height: 180px !important;
            min-height: 180px !important;
            object-fit: cover !important;
        }}
        @media (max-width: 900px) {{
            .products-grid {{ grid-template-columns: repeat(2, 1fr) !important; }}
        }}
        @media (max-width: 600px) {{
            .products-grid {{ grid-template-columns: 1fr !important; }}
        }}
        .portal-card {{
            background: linear-gradient(155deg, rgba(22, 52, 38, 0.88) 0%, rgba(18, 40, 48, 0.82) 100%);
            border: 1px solid rgba(110, 231, 183, 0.14);
            border-radius: 20px;
            padding: 24px;
            box-shadow: 0 12px 36px -12px rgba(0,0,0,0.4), 0 0 28px -12px rgba(52, 211, 153, 0.15);
            display: flex;
            flex-direction: column;
        }}
        .nature-card {{
            position: relative;
            isolation: isolate;
            min-width: 0;
            box-sizing: border-box;
            border-color: rgba(167, 205, 178, 0.25) !important;
            background:
                radial-gradient(ellipse at 8% 0%, rgba(167, 139, 250, 0.09), transparent 34%),
                radial-gradient(ellipse at 100% 100%, rgba(110, 231, 183, 0.08), transparent 38%),
                linear-gradient(155deg, rgba(22, 52, 38, 0.94), rgba(18, 40, 48, 0.92)) !important;
        }}
        .nature-card::before {{
            content: "";
            position: absolute;
            z-index: -1;
            pointer-events: none;
            inset: 6px;
            border: 1px solid rgba(174, 211, 183, 0.16);
            border-radius: 15px;
            background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1000 500' fill='none'%3E%3Cg stroke='%23a7d3b5' stroke-width='2' opacity='.48'%3E%3Cpath d='M18 86 C55 48 78 120 112 83 S164 55 190 94 M18 106 C52 75 78 145 116 105 M982 414 C945 452 922 380 888 417 S836 445 810 406 M982 394 C948 425 922 355 884 395'/%3E%3Cpath d='M18 414 C48 386 57 354 50 326 M982 86 C952 114 943 146 950 174'/%3E%3Cpath d='M38 72c-16-18-27-4-17 8 8 9 23 5 27-9m-3 15c15-17 28-4 18 8-8 9-22 5-27-8m919 324c16 18 27 4 17-8-8-9-23-5-27 9m3-15c-15 17-28 4-18-8 8-9 22-5 27 8'/%3E%3C/g%3E%3Cg stroke='%23cbd5e1' stroke-width='2' opacity='.4'%3E%3Cpath d='M830 40c0-10 8-18 18-18 6 0 12 3 15 8 3-8 11-13 20-13 13 0 23 10 23 23h-76Zm-736 420c0-10 8-18 18-18 6 0 12 3 15 8 3-8 11-13 20-13 13 0 23 10 23 23H94Z'/%3E%3C/g%3E%3C/svg%3E") center / 100% 100% no-repeat;
        }}
        .nature-card > * {{ min-width: 0; }}
        .nature-label {{
            border-color: rgba(167, 205, 178, 0.3) !important;
            background: linear-gradient(110deg, rgba(110, 231, 183, 0.1), rgba(167, 139, 250, 0.1)) !important;
            box-shadow: inset 0 0 14px rgba(110, 231, 183, 0.04);
        }}
        .portal-header .nature-mark {{
            width: 48px;
            height: 48px;
            flex: 0 0 48px;
            filter: drop-shadow(0 3px 12px rgba(110, 231, 183, 0.24));
        }}
        .tab-btn {{
            border: 1px solid rgba(167, 205, 178, 0.12);
            background-image: linear-gradient(145deg, rgba(110, 231, 183, 0.025), rgba(167, 139, 250, 0.025));
        }}
        .tab-btn:hover {{
            border-color: rgba(167, 205, 178, 0.34);
            background-color: rgba(110, 231, 183, 0.08) !important;
        }}
        .card-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 18px; border-bottom: 1px solid rgba(110, 231, 183, 0.1); padding-bottom: 12px; }}
        .card-title {{ font-size: 16px; font-weight: 700; color: #ecfdf5; margin: 0; }}
        .weather-value {{ font-size: 32px; font-weight: 800; color: #6ee7b7; margin: 10px 0 5px 0; font-family: monospace; text-shadow: 0 0 20px rgba(52, 211, 153, 0.35); }}
        .tab-bar {{
            display:flex; gap:6px; margin-bottom:20px; flex-wrap:wrap;
            background: linear-gradient(90deg, rgba(52, 211, 153, 0.06), rgba(167, 139, 250, 0.06));
            padding:6px; border-radius:14px; border:1px solid rgba(110, 231, 183, 0.12);
            overflow:hidden;
        }}
        .tab-btn {{ flex:1 1 auto; min-width:0; text-align:center; padding:10px 8px; border-radius:10px; font-weight:700; font-size:13px; cursor:pointer; text-decoration:none; transition:all 0.25s; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
        @media (max-width: 640px) {{
            .tab-bar {{ gap:4px; padding:4px; }}
            .tab-btn {{ flex:1 1 45%; padding:10px 6px; font-size:12px; }}
        }}
        {profile_view_styles}
    </style></head>
    <body class="{'profile-view' if profile_page_mode else ''}">
        <div class="container" style="max-width:1400px; width:100%; padding:20px 16px; margin:0 auto;">
            <div class="portal-header" style="background:var(--panel-glass); border:1px solid var(--border-glass); border-radius:24px; padding:24px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:15px; margin-bottom:24px;">
                <div style="display:flex; align-items:center; gap:16px;">
                    <svg class="nature-mark" viewBox="0 0 64 64" role="img" aria-label="Olode nature mark" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <circle cx="32" cy="32" r="29" fill="rgba(16,54,41,.72)" stroke="rgba(167,211,181,.55)" stroke-width="1.5"/>
                        <path d="M32 47V27" stroke="#a7d3b5" stroke-width="2.5" stroke-linecap="round"/>
                        <path d="M32 36C22 36 17 30 18 21c9 0 15 4 14 13Zm0-6c0-10 6-16 16-16 0 10-5 16-16 16Z" fill="rgba(110,231,183,.2)" stroke="#a7d3b5" stroke-width="2" stroke-linejoin="round"/>
                        <path d="M21 47h22M25 51h14" stroke="#d6c49a" stroke-width="2" stroke-linecap="round"/>
                        <circle cx="47" cy="18" r="4" fill="#e8dba9"/>
                    </svg>
                    <div><h1 style="margin:0; font-size:22px; font-weight:800; color:#fff;">Farmstead: <a href="/portal/feed?active_tab=community&view_profile={html.escape(str(current_user['phone']), quote=True)}" style="color:inherit;text-decoration:none;">{html.escape(current_user['name'])}</a> {'🌿' if current_user.get('status') == 'Approved' else ''}</h1><span class="badge badge-emerald nature-label" style="margin-top:6px;">🌱 {html.escape(current_user['lga'])} Community</span></div>
                </div>
                <div class="portal-header-actions"><span id="grid_score_display" class="badge badge-amber nature-label" style="font-weight:800; padding:8px 16px; font-size:13px;">🌿 {current_user['xp']} Growth Points</span>
                    {admin_dashboard_link}
                        <button class="btn" type="button" data-profile-phone="{html.escape(str(current_user['phone']), quote=True)}" onclick="shareMyProfile(this)" style="background:rgba(16,185,129,.12);color:#6ee7b7;border:1px solid rgba(16,185,129,.3);padding:10px 14px;font-size:13px;border-radius:10px;">🌱 Invite friends to grow with me</button>
                        <button class="btn" type="button" onclick="shareOlodeSite()" style="background:rgba(167,139,250,.12);color:#c4b5fd;border:1px solid rgba(167,139,250,.3);padding:10px 14px;font-size:13px;border-radius:10px;">🍃 Share Olode.com.ng</button>
                        <a href="/portal/guardroom" class="btn" style="background:rgba(110,231,183,.1);color:#a7f3d0;border:1px solid rgba(110,231,183,.25);padding:10px 14px;font-size:13px;border-radius:10px;">🛡️ Guardroom</a>
                        <a href="/portal/profile/edit" class="btn" style="background:rgba(59,130,246,0.15); color:#93c5fd; border:1px solid rgba(59,130,246,0.3); padding:10px 16px; font-size:13px; border-radius:10px;">✏️ Edit Profile</a>
                    <a href="/portal/logout" class="btn btn-danger" style="padding:10px 20px; font-size:13px; border-radius:10px;">🔌 Disconnect</a></div>
            </div>
            {('<div role="status" style="margin:-8px 0 16px;padding:12px 16px;background:rgba(110,231,183,.1);border:1px solid rgba(110,231,183,.25);border-radius:12px;color:#a7f3d0;">Thank you for helping keep the site safe. Your report has been sent to the team for review.</div>') if report_sent else ''}

            <form action="/portal/feed" method="get" style="margin-bottom:12px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; background:var(--panel-glass); border:1px solid var(--border-glass); border-radius:12px; padding:8px 12px;">
                <input type="hidden" name="active_tab" value="community">
                <span style="font-size:13px; font-weight:600; color:#94a3b8; white-space:nowrap;">🔍 Find a Farmer</span>
                <input type="text" name="search_phone" list="friend-phone-suggestions" placeholder="0803 123 4567" required inputmode="numeric" autocomplete="tel"
                       style="flex:1; min-width:140px; padding:8px 10px; font-size:14px; background:#0f172a; border:1px solid rgba(52,211,153,0.25); color:#f0fdf4; border-radius:8px; margin:0;">
                <datalist id="friend-phone-suggestions">{friend_suggestion_options}</datalist>
                <button type="submit" class="btn btn-emerald" style="padding:8px 14px; font-size:13px; white-space:nowrap;">Search</button>
            </form>
            {f'<div style="margin-bottom:16px;">{peer_card_html}</div>' if search_phone and peer_card_html else ''}

            <div class="tab-bar">
                <a href="/portal/feed?active_tab=incidents" class="tab-btn" style="{tab_incidents_active}">🌿 Alerts</a>
                <a href="/portal/feed?active_tab=community" class="tab-btn" style="{tab_community_active}">🌳 Community</a>
                <a href="/portal/feed?active_tab=friends" class="tab-btn" style="{tab_friends_active}">🍀 Friends & Requests{pending_request_badge}</a>
                <a href="/portal/feed?active_tab=shoutouts" class="tab-btn" style="{tab_shoutouts_active}">🌸 Shout Out</a>
                <a href="/portal/feed?active_tab=market" class="tab-btn" style="{tab_market_active}">🥕 Find Products</a>
                <a href="/portal/feed?active_tab=farm_market" class="tab-btn" style="{tab_farm_market_active}">🧺 Farm Market{product_notification_badge}</a>
                <a href="/portal/feed?active_tab=family" class="tab-btn" style="{'background:rgba(16,185,129,0.2); color:#10b981;' if is_family_tab else 'background:transparent; color:var(--text-muted);'}">🌱 Family Meeting</a>
                <a id="messages-nav-link" href="/portal/messages" class="tab-btn" style="background:transparent; color:var(--text-muted);">🐦 Messages{unread_badge}</a>
                <button type="button" onclick="enableMessageNotifications()" class="tab-btn" style="background:transparent; color:var(--text-muted); border:0; cursor:pointer;">🌼 Enable alerts</button>
            </div>

            <div id="tab_incidents" style="{show_incidents}">
                <div class="portal-grid" style="grid-template-columns: 1fr; margin-top:24px;">
                    <div class="portal-card" style="border-color: rgba(239,68,68,0.2);"><div class="card-header" style="border-color: rgba(239,68,68,0.15);">🛡️ <h3 class="card-title" style="color:#ef4444;">Active Sector Threat Vectors</h3></div>{echo_feed_html or '<div style="text-align:center; padding:20px; color:var(--text-muted); font-style:italic; font-size:14px;">🟢 Secure baseline. Local sector is quiet.</div>'}</div>
                    <div class="portal-card" style="border-color: rgba(245,158,11,0.2);">
                        <div class="card-header" style="border-color: rgba(245,158,11,0.15);">🚨 <h3 class="card-title" style="color:var(--accent-amber);">Broadcast Emergency Panic Vector</h3></div>
                        <form id="emergency_form" action="/portal/alert/raise" method="post" enctype="multipart/form-data" onsubmit="executeTransmissionSequence(event)">
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:15px; margin-bottom:15px;">
                                <div>
                                    <label style="display:block; margin-bottom:8px; font-size:12px; color:var(--text-muted); font-weight:700; text-transform:uppercase; letter-spacing:0.04em;">Classification</label>
                                    <select id="alert_type" name="alert_type" style="width:100%; padding:14px 16px; font-size:15px; background:#0f172a; border:1.5px solid rgba(239,68,68,0.4); color:#f1f5f9; border-radius:12px; appearance:none; background-image:url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%228%22><path fill=%22%2394a3b8%22 d=%22M0 0l6 8 6-8z%22/></svg>'); background-repeat:no-repeat; background-position:right 14px center; cursor:pointer;">
                                        <option value="Intruder Spotted">Intruder Spotted</option>
                                        <option value="Critical Disaster">Critical Disaster</option>
                                        <option value="Armed Attack">Armed Attack</option>
                                        <option value="Police Brutality">Police Brutality</option>
                                        <option value="Kidnapping">Kidnapping</option>
                                        <option value="Assault">Assault</option>
                                        <option value="Child Abuse">Child Abuse</option>
                                        <option value="Rape">Rape</option>
                                        <option value="Land Grabbing">Land Grabbing</option>
                                    </select>
                                </div>
                                <div><label style="display:block; margin-bottom:8px; font-size:12px; color:var(--text-muted); font-weight:700;">Tactical Coordinates</label><input type="text" id="alert_message" name="message" placeholder="State coordinates..." required></div>
                            </div>
                            <div style="margin-bottom:20px;"><label style="display:block; margin-bottom:8px; font-size:12px; color:var(--text-muted); font-weight:700;">📷 Attach Video Clip Evidence (Optional, MP4/MOV/WebM/AVI, up to 15 MB)</label><input type="file" name="video_evidence" accept="video/mp4,video/quicktime,video/webm,video/x-msvideo,.mp4,.mov,.webm,.avi" style="background:#090d16; color:white; padding:10px; border-radius:12px; border:1px solid var(--border-glass); width:100%;"></div>
                            <div style="margin-bottom:16px; background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.4); border-radius:12px; padding:14px;">
                                <div style="font-size:13px; font-weight:800; color:#fecaca; margin-bottom:8px; text-transform:uppercase; letter-spacing:0.04em;">⚠️ Strict Warning — Fake News</div>
                                <p style="font-size:14px; color:#fecaca; margin:0 0 12px 0; line-height:1.5;">Broadcasting false or unverified information is a serious offence. Fake alerts can cause panic, harm neighbours, and will lead to account restriction or reporting to authorities.</p>
                                <label style="display:flex; align-items:flex-start; gap:10px; font-size:15px; color:#fff; cursor:pointer;">
                                    <input type="checkbox" name="attest_real" required style="margin-top:3px; width:18px; height:18px; accent-color:#ef4444;">
                                    <span>I attest that this alert is real and not fake. I understand the consequences of broadcasting false information.</span>
                                </label>
                            </div>
                            <button type="submit" id="panic_btn" class="btn" style="width:100%; padding:16px; background:#ef4444; color:white; font-size:15px; font-weight:bold; box-shadow: 0 4px 20px rgba(239,68,68,0.25);">📡 Execute Strategic Grid Alarm</button>
                        </form>
                    </div>
                </div>
            </div>

            <div id="tab_community" style="{show_community}">
                <section id="profile-view" style="display:{'block' if profile_page_mode else 'none'};max-width:920px;margin:0 auto 22px;">
                    {profile_card_html}
                    {f'<div id="profile-wall" class="portal-card" style="margin-bottom:20px;background:linear-gradient(155deg,rgba(74,18,40,.88),rgba(40,12,30,.94));border-color:rgba(190,72,112,.3);"><div class="card-header" style="border-color:rgba(190,72,112,.25);"><h3 class="card-title">📝 Wall: statuses and shout-outs</h3></div><h4 style="color:#f0c2d0;margin:8px 0;">Statuses</h4>{profile_status_html}<h4 style="color:#f0c2d0;margin:18px 0 8px;">Shout-outs</h4>{profile_shoutouts_html}</div>' if profile_page_mode else ''}
                </section>
                <div class="portal-grid">
                    <div class="portal-card">
                        <div class="card-header">🌤️ <h3 class="card-title">Live Weather</h3></div>
                        <div class="weather-value">{weather['temp']}</div>
                        <div style="color:#6ee7b7; font-weight:600; font-size:15px; margin-bottom:14px;">{weather['desc']}</div>
                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; font-size:14px; margin-bottom:14px;">
                            <div style="background:rgba(255,255,255,0.04); padding:10px 12px; border-radius:10px;">
                                <div style="color:var(--text-muted); font-size:12px;">Humidity</div>
                                <div style="font-weight:700; color:#f1f5f9; font-size:16px;">{weather['humidity']}</div>
                            </div>
                            <div style="background:rgba(255,255,255,0.04); padding:10px 12px; border-radius:10px;">
                                <div style="color:var(--text-muted); font-size:12px;">Wind</div>
                                <div style="font-weight:700; color:#f1f5f9; font-size:16px;">{weather['wind']}</div>
                            </div>
                            <div style="background:rgba(255,255,255,0.04); padding:10px 12px; border-radius:10px; grid-column:span 2;">
                                <div style="color:var(--text-muted); font-size:12px;">Rain (now)</div>
                                <div style="font-weight:700; color:#f1f5f9; font-size:16px;">{weather['rain']}</div>
                            </div>
                        </div>
                        <div style="border-top:1px solid rgba(255,255,255,0.06); padding-top:12px;">
                            <div style="font-size:12px; color:var(--text-muted); text-transform:uppercase; margin-bottom:8px; font-weight:700;">3-Day Forecast</div>
                            {"".join([f'''
                            <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid rgba(255,255,255,0.04); font-size:14px;">
                                <span style="font-weight:600; color:#e2e8f0; min-width:70px;">{fd['day']}</span>
                                <span style="color:#f1f5f9;">{fd['high']} / {fd['low']}</span>
                                <span style="color:#94a3b8; font-size:13px;">{fd['rain']}</span>
                            </div>''' for fd in weather.get('forecast', [])]) or '<div style="color:var(--text-muted); font-size:13px;">Forecast unavailable</div>'}
                        </div>
                    </div>

                    <div class="portal-card">
                        <div class="card-header">🌱 <h3 class="card-title">Soil Sensors</h3></div>
                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:14px;">
                            <div style="background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.2); padding:14px; border-radius:12px; text-align:center;">
                                <div style="font-size:12px; color:var(--text-muted); margin-bottom:4px;">Moisture</div>
                                <div style="font-size:22px; font-weight:800; color:#6ee7b7;">{soil['moisture_label'].split('—')[0].strip() if soil.get('moisture') is not None else '—'}</div>
                                <div style="font-size:12px; color:#94a3b8; margin-top:4px;">{soil['moisture_label'].split('—')[1].strip() if soil.get('moisture') is not None and '—' in soil['moisture_label'] else ''}</div>
                            </div>
                            <div style="background:rgba(59,130,246,0.08); border:1px solid rgba(59,130,246,0.2); padding:14px; border-radius:12px; text-align:center;">
                                <div style="font-size:12px; color:var(--text-muted); margin-bottom:4px;">pH Level</div>
                                <div style="font-size:22px; font-weight:800; color:#93c5fd;">{soil['ph_label'].split('—')[0].strip() if soil.get('ph') is not None else '—'}</div>
                                <div style="font-size:12px; color:#94a3b8; margin-top:4px;">{soil['ph_label'].split('—')[1].strip() if soil.get('ph') is not None and '—' in soil['ph_label'] else ''}</div>
                            </div>
                        </div>
                        <div style="font-size:13px; color:#cbd5e1; line-height:1.45; margin-bottom:14px;">{soil['advice']}</div>
                        {f'<div style="font-size:11px; color:var(--text-muted); margin-bottom:12px;">Last reading: {soil["timestamp"]}</div>' if soil.get('timestamp') else ''}
                        {('<div style="background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.3); border-radius:10px; padding:10px 14px; margin-bottom:12px; color:#6ee7b7; font-weight:700; font-size:14px;">✅ Soil reading saved!</div>') if soil_saved else ''}
                        <div style="margin-bottom:12px;"><a href="/portal/soil/history" style="color:#6ee7b7; font-size:13px; font-weight:700; text-decoration:none;">📊 View reading history →</a></div>
                        <form action="/portal/sensors/submit" method="post" style="border-top:1px solid rgba(255,255,255,0.06); padding-top:14px;">
                            <div style="font-size:13px; font-weight:700; color:#e2e8f0; margin-bottom:10px;">Enter new reading</div>
                            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
                                <div>
                                    <label style="font-size:12px; color:var(--text-muted);">Moisture %</label>
                                    <input type="text" name="moisture" placeholder="e.g. 45" required inputmode="decimal"
                                           style="width:100%; padding:10px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; box-sizing:border-box;">
                                </div>
                                <div>
                                    <label style="font-size:12px; color:var(--text-muted);">pH (0–14)</label>
                                    <input type="text" name="ph" placeholder="e.g. 6.5" required inputmode="decimal"
                                           style="width:100%; padding:10px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; box-sizing:border-box;">
                                </div>
                            </div>
                            <button type="submit" class="btn btn-emerald" style="width:100%; padding:12px; font-size:15px;">Save Soil Reading</button>
                        </form>
                    </div>

                    <div class="portal-card"><div class="card-header">👥 <h3 class="card-title">Active Neighbors ({len(approved_neighbors)})</h3></div><div style="flex:1; max-height:220px; overflow-y:auto;">{nb_approved or '<p style="color:var(--text-muted); font-size:13px; margin:0;">No active nodes nearby.</p>'}</div></div>
                    <div class="portal-card">
                        <div class="card-header">🛡️ <h3 class="card-title">Trust Groups</h3></div>
                        <p style="font-size:13px; color:#cbd5e1; margin:0 0 10px;">Create a private group and invite accepted friends. They must accept before joining or receiving alerts. Travel alerts and every “I'm OK” check-in appear here for group members. Enable WhatsApp alerts for yourself if you want messages too; {whatsapp_delivery_note} Twilio/WhatsApp messaging charges may apply. Earn +5 XP for your first 3 check-ins per trip; later check-ins still notify the group.</p>
                        {pending_trust_group_invites_html}
                        <form action="/portal/trust-groups/create" method="post" style="display:flex; gap:8px; margin-bottom:12px;">
                            <input type="text" name="name" maxlength="60" placeholder="New group name (e.g. Family)" required style="padding:9px; font-size:14px;">
                            <button type="submit" class="btn btn-emerald" style="padding:9px 12px; font-size:12px; white-space:nowrap;">Create group</button>
                        </form>
                        {trust_groups_html}
                    </div>
                    {faith_card_html}
                </div>

                <!-- Farm Radio Receiver -->
                <div class="portal-card nature-card" style="margin-top:24px; border-color: rgba(168,85,247,0.25);">
                    <div class="card-header" style="border-color: rgba(168,85,247,0.2);">
                        📻 <h3 class="card-title" style="color:#c4b5fd;">Farm Radio</h3>
                    </div>
                    <p style="font-size:14px; color:#cbd5e1; margin:0 0 16px 0; line-height:1.45;">
                        Listen to radio while you work. Choose a station, then adjust Bass, Mid and High to your liking.
                    </p>

                    <div style="display:flex; flex-wrap:wrap; gap:10px; margin-bottom:16px; align-items:center;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0; margin:0;">Station</label>
                        <select id="radio_station" style="flex:1; min-width:200px; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px;">
                            <option value="">— Select a station —</option>
                            <optgroup label="🇳🇬 Nigerian FM">
                                <option value="https://wazobiafmlagos951-atunwadigital.streamguys1.com/wazobiafmlagos951">Wazobia FM 95.1 Lagos</option>
                                <option value="https://wazobiafmabuja995-atunwadigital.streamguys1.com/wazobiafmabuja995">Wazobia FM 99.5 Abuja</option>
                                <option value="https://wazobiafmph941-atunwadigital.streamguys1.com/wazobiafmph941">Wazobia FM 94.1 Port Harcourt</option>
                                <option value="https://coolfmlagos969-atunwadigital.streamguys1.com/coolfmlagos969">Cool FM 96.9 Lagos</option>
                                <option value="https://coolfmabuja969-atunwadigital.streamguys1.com/coolfmabuja969">Cool FM 96.9 Abuja</option>
                                <option value="https://servidor28.brlogic.com:7024/live">RayPower 100.5 FM Lagos</option>
                                <option value="https://stream.zeno.fm/0fxekubhg6quv">Rave FM 91.7 Osogbo</option>
                                <option value="https://c26.radioboss.fm:8285/stream">Pidgin Radio Lagos</option>
                            </optgroup>
                            <optgroup label="🌍 International">
                                <option value="https://stream.live.vc.bbcmedia.co.uk/bbc_world_service">BBC World Service</option>
                                <option value="https://ice1.somafm.com/groovesalad-128-mp3">SomaFM Groove Salad</option>
                                <option value="https://ice1.somafm.com/secretagent-128-mp3">SomaFM Secret Agent</option>
                            </optgroup>
                        </select>
                        <button type="button" id="radio_play_btn" onclick="toggleRadio()" class="btn btn-emerald" style="padding:12px 20px; font-size:16px; min-width:100px;">Play</button>
                    </div>

                    <div style="background:rgba(0,0,0,0.25); border-radius:14px; padding:16px; margin-bottom:8px;">
                        <div style="font-size:13px; font-weight:700; color:#c4b5fd; margin-bottom:14px; text-transform:uppercase; letter-spacing:0.04em;">Tone Controls</div>
                        <div style="display:grid; gap:14px;">
                            <div>
                                <div style="display:flex; justify-content:space-between; font-size:14px; margin-bottom:6px;">
                                    <span style="color:#e2e8f0; font-weight:600;">Bass</span>
                                    <span id="bass_val" style="color:#94a3b8;">0</span>
                                </div>
                                <input type="range" id="eq_bass" min="-15" max="15" value="0" step="1"
                                       style="width:100%; height:28px; accent-color:#a78bfa;"
                                       oninput="setEq('bass', this.value)">
                            </div>
                            <div>
                                <div style="display:flex; justify-content:space-between; font-size:14px; margin-bottom:6px;">
                                    <span style="color:#e2e8f0; font-weight:600;">Mid</span>
                                    <span id="mid_val" style="color:#94a3b8;">0</span>
                                </div>
                                <input type="range" id="eq_mid" min="-15" max="15" value="0" step="1"
                                       style="width:100%; height:28px; accent-color:#a78bfa;"
                                       oninput="setEq('mid', this.value)">
                            </div>
                            <div>
                                <div style="display:flex; justify-content:space-between; font-size:14px; margin-bottom:6px;">
                                    <span style="color:#e2e8f0; font-weight:600;">High</span>
                                    <span id="high_val" style="color:#94a3b8;">0</span>
                                </div>
                                <input type="range" id="eq_high" min="-15" max="15" value="0" step="1"
                                       style="width:100%; height:28px; accent-color:#a78bfa;"
                                       oninput="setEq('high', this.value)">
                            </div>
                        </div>
                        <div style="margin-top:14px; display:flex; gap:10px; align-items:center;">
                            <span style="font-size:14px; color:#e2e8f0; font-weight:600;">Volume</span>
                            <input type="range" id="radio_volume" min="0" max="100" value="70"
                                   style="flex:1; height:28px; accent-color:#34d399;"
                                   oninput="setRadioVolume(this.value)">
                            <span id="vol_val" style="font-size:14px; color:#94a3b8; min-width:36px;">70%</span>
                        </div>
                    </div>
                    <p id="radio_status" style="font-size:13px; color:#94a3b8; margin:8px 0 0 0;">Stopped — choose a station and press Play</p>
                    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;align-items:center;">
                        <span style="font-size:12px;color:#cbd5e1;font-weight:700;">Share this station via</span>
                        <button class="btn" type="button" onclick="shareRadioStation('whatsapp')" style="padding:7px 10px;background:rgba(16,185,129,.12);color:#6ee7b7;">WhatsApp</button>
                        <button class="btn" type="button" onclick="shareRadioStation('facebook')" style="padding:7px 10px;background:rgba(59,130,246,.12);color:#93c5fd;">Facebook</button>
                        <button class="btn" type="button" onclick="shareRadioStation('x')" style="padding:7px 10px;background:rgba(255,255,255,.08);color:#e2e8f0;">X</button>
                    </div>
                    <audio id="radio_audio" crossorigin="anonymous" preload="none" style="display:none;"></audio>

                    {('<div class="portal-card" style="grid-column:1/-1; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.3); padding:16px;"><div style="color:#6ee7b7; font-weight:700;">✅ Friend request sent! It will appear under their Requests.</div></div>') if friend_sent else ''}
                    {('<div id="profile-updated-notice" class="portal-card" style="grid-column:1/-1; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.3); padding:16px;"><div style="color:#6ee7b7; font-weight:700;">✅ Profile updated successfully.</div></div>') if profile_updated else ''}
                    <div class="portal-card nature-card" style="grid-column:1 / -1;">
                        <div id="status-feed" class="card-header">📝 <h3 class="card-title">Status Feed</h3></div>
                        <p style="font-size:13px; color:#94a3b8; margin:0 0 12px 0;">Post an update. Friends can like, comment, or repost to grow the network.</p>
                        <form action="/portal/status/post" method="post" enctype="multipart/form-data" style="display:grid;grid-template-columns:1fr auto;gap:10px;margin-bottom:16px;">
                            <input type="text" name="content" maxlength="280" placeholder="What's happening on the farm…"
                                   style="grid-column:1/-1;padding:12px;font-size:16px;background:#1e293b;border:2px solid #475569;color:#f8fafc;border-radius:10px;">
                            <input type="file" name="photo" accept="image/jpeg,image/png,image/webp" style="min-width:0;font-size:13px;color:#cbd5e1;">
                            <button type="submit" class="btn btn-emerald" style="padding:12px 18px;">Post</button>
                        </form>
                        <p style="font-size:12px;color:#94a3b8;margin:-8px 0 12px;">Add a photo or text. Photos are automatically resized and compressed (up to 8 MB before upload).</p>
                        <div style="max-height:480px; overflow-y:auto;">{status_html}</div>
                    </div>

                    <a href="/portal/feed?active_tab=shoutouts" class="portal-card nature-card" style="grid-column:1/-1;display:block;text-decoration:none;color:inherit;">
                        <div class="card-header">🎊 <h3 class="card-title">Shout Out</h3></div>
                        <p style="color:#cbd5e1;margin:0;">Create a birthday, naming, wedding, harvest, or thank-you card to share with your community.</p>
                    </a>

                    <div class="portal-card nature-card">
                        <div class="card-header">🎯 <h3 class="card-title">Rolling Dart</h3></div>
                        <p style="font-size:13px; color:#94a3b8; margin:0 0 12px 0;">Tap <b>Roll</b> — score 50+ to earn {DART_WIN_XP} XP</p>
                        <div id="dart_board" style="position:relative; width:220px; height:220px; margin:0 auto 14px; border-radius:50%; background:radial-gradient(circle, #fef3c7 0%, #f59e0b 35%, #dc2626 60%, #1e293b 61%, #334155 100%); border:4px solid #64748b; display:flex; align-items:center; justify-content:center;">
                            <div id="dart_score_display" style="font-size:42px; font-weight:900; color:#fff; text-shadow:0 2px 8px rgba(0,0,0,0.5);">0</div>
                        </div>
                        <button type="button" onclick="playDart()" class="btn btn-emerald" style="width:100%; padding:14px; font-size:16px;">Roll Dart</button>
                        <form id="dart_score_form" action="/portal/games/score" method="post" style="display:none;">
                            <input type="hidden" name="game_name" value="dart">
                            <input type="hidden" name="score" id="dart_score_input" value="0">
                        </form>
                        <p id="dart_msg" style="font-size:13px; color:#94a3b8; text-align:center; margin-top:10px;"></p>
                    </div>

                    <div class="portal-card nature-card">
                        <div class="card-header">🌾 <h3 class="card-title">XP Hunt</h3></div>
                        <p style="font-size:13px; color:#94a3b8; margin:0 0 12px 0;">Find the golden seed! Tap tiles — 3 finds = {HUNT_WIN_XP} XP</p>
                        <div id="hunt_grid" style="display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:14px;"></div>
                        <button type="button" onclick="startHunt()" class="btn btn-emerald" style="width:100%; padding:14px; font-size:16px;">New Hunt</button>
                        <form id="hunt_score_form" action="/portal/games/score" method="post" style="display:none;">
                            <input type="hidden" name="game_name" value="hunt">
                            <input type="hidden" name="score" id="hunt_score_input" value="0">
                        </form>
                        <p id="hunt_msg" style="font-size:13px; color:#94a3b8; text-align:center; margin-top:10px;">Press New Hunt to start</p>
                    </div>
                </div>
            </div>

            <div id="tab_friends" style="{show_friends}">
                <div class="portal-grid">{friends_tab_content}</div>
            </div>

            <div id="tab_shoutouts" style="{show_shoutouts}">
                <div class="portal-card nature-card" style="max-width:900px;margin:0 auto 20px;">
                    <div class="card-header">🎊 <h3 class="card-title">Shout Out</h3></div>
                    <p style="color:#cbd5e1;line-height:1.55;">Celebrate birthdays, naming ceremonies, weddings, harvests, and other joyful moments. Choose from 200 lightweight designs, add your own words and an optional photo, then share or print your card.</p>
                    <form id="shoutout-form" action="/portal/shoutout" method="post" enctype="multipart/form-data" style="display:grid;gap:12px;background:rgba(0,0,0,.2);padding:16px;border-radius:14px;">
                        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;">
                            <label style="color:#cbd5e1;font-size:13px;">Occasion
                                <select name="category" required style="width:100%;margin-top:5px;">
                                    {"".join(f'<option value="{html.escape(category, quote=True)}">{html.escape(category)}</option>' for category in SHOUTOUT_CATEGORIES)}
                                </select>
                            </label>
                            <label style="color:#cbd5e1;font-size:13px;">Celebrant / recipient (optional)
                                <input name="recipient" maxlength="60" placeholder="Who are you celebrating?" style="width:100%;margin-top:5px;box-sizing:border-box;">
                            </label>
                            <label style="color:#cbd5e1;font-size:13px;">Card design
                                <select name="template_key" required style="width:100%;margin-top:5px;">
                                    {"".join(f'<option value="{key}">{emoji} {key.replace("-", " ").title()}</option>' for key, (emoji, _) in SHOUTOUT_TEMPLATES.items())}
                                </select>
                            </label>
                        </div>
                        <label style="color:#cbd5e1;font-size:13px;">Your message
                            <textarea name="message" maxlength="{MAX_SHOUTOUT_LEN}" required rows="3" placeholder="Write your own warm message…" style="width:100%;box-sizing:border-box;margin-top:5px;"></textarea>
                        </label>
                        <label style="color:#cbd5e1;font-size:13px;">Optional celebration photo (up to 15 MB)
                            <input type="file" name="photo" accept="image/*" style="display:block;width:100%;margin-top:5px;color:#e2e8f0;">
                        </label>
                        <button type="submit" class="btn btn-emerald" style="justify-self:start;padding:12px 18px;">Post Shout Out (+{SHOUTOUT_XP} XP)</button>
                    </form>
                </div>
                <div style="max-width:900px;margin:0 auto;">
                    <h3 style="color:#e2e8f0;">Celebrations from {html.escape(current_user['lga'] or 'your community')}</h3>
                    <div id="shoutout-list">{shoutouts_html}</div>
                </div>
            </div>

            <div id="tab_market" style="{show_market}">
                <div class="portal-card" style="width:100%; max-width:none; margin:0;">
                    <div class="card-header">📦 <h3 class="card-title">Find products</h3></div>
                    <form action="/portal/feed" method="get" style="margin-bottom:16px;">
                        <input type="hidden" name="active_tab" value="market">
                        {hidden_cat}
                        {hidden_status}
                        {hidden_mine}
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0; display:block; margin-bottom:6px;">Search</label>
                        <input type="text" name="market_q" value="{active_q}" placeholder="Type crop name, seller or town…"
                               style="width:100%; padding:14px; font-size:17px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:12px; box-sizing:border-box; margin-bottom:12px;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0; display:block; margin-bottom:6px;">Sort by</label>
                        <div style="display:flex; flex-wrap:wrap; gap:10px; align-items:center;">
                            <select name="market_sort" style="flex:1; min-width:140px; padding:14px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:12px;">
                                {sort_select_opts}
                            </select>
                            <button type="submit" class="btn btn-emerald" style="padding:14px 22px; font-size:16px;">Search</button>
                        </div>
                    </form>
                    <div style="font-size:14px; font-weight:700; color:#94a3b8; margin-bottom:8px;">Type of product</div>
                    <div style="margin-bottom:12px;">{filter_chips}</div>
                    <div style="font-size:14px; font-weight:700; color:#94a3b8; margin-bottom:8px;">Status</div>
                    <div style="margin-bottom:12px;">{status_chips}{mine_chip}</div>
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:14px; padding-top:8px; border-top:1px solid rgba(255,255,255,0.06);">
                        <span style="font-size:15px; color:#e2e8f0; font-weight:600;">{result_label}</span>
                        {clear_filters_btn}
                    </div>
                    <div class="products-grid" style="display:grid; grid-template-columns:repeat(3, 1fr); gap:16px; width:100%;">
                        {products_html}
                    </div>
                    <div id="productEditModal" style="display:none; position:fixed; inset:0; z-index:2500; background:rgba(2,6,23,0.88); padding:20px; overflow-y:auto;" onclick="if(event.target===this) closeProductEdit()">
                        <form id="productEditForm" action="/portal/market/edit" method="post" enctype="multipart/form-data" style="max-width:620px; margin:5vh auto; padding:22px; background:#0f172a; border:1px solid rgba(148,163,184,0.25); border-radius:16px; box-sizing:border-box;">
                            <input type="hidden" name="product_id">
                            <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:14px;">
                                <h3 style="margin:0; color:#f8fafc;">Edit your listing</h3>
                                <button type="button" onclick="closeProductEdit()" aria-label="Close" style="background:none; border:0; color:#cbd5e1; font-size:24px; cursor:pointer;">✕</button>
                            </div>
                            <label style="display:block; color:#e2e8f0; margin:12px 0 6px;">Product title</label>
                            <input name="title" required maxlength="{MAX_PRODUCT_TITLE}" style="width:100%; box-sizing:border-box; padding:12px; background:#1e293b; border:1px solid #475569; color:#fff; border-radius:8px;">
                            <label style="display:block; color:#e2e8f0; margin:12px 0 6px;">Category</label>
                            <select name="category" style="width:100%; box-sizing:border-box; padding:12px; background:#1e293b; border:1px solid #475569; color:#fff; border-radius:8px;">{category_options}</select>
                            <label style="display:block; color:#e2e8f0; margin:12px 0 6px;">Price</label>
                            <input name="price" maxlength="40" style="width:100%; box-sizing:border-box; padding:12px; background:#1e293b; border:1px solid #475569; color:#fff; border-radius:8px;">
                            <label style="display:block; color:#e2e8f0; margin:12px 0 6px;">Details</label>
                            <textarea name="description" maxlength="{MAX_PRODUCT_DESC}" rows="4" style="width:100%; box-sizing:border-box; padding:12px; background:#1e293b; border:1px solid #475569; color:#fff; border-radius:8px;"></textarea>
                            <label style="display:block; color:#e2e8f0; margin:12px 0 6px;">Contact phone</label>
                            <input name="contact_phone" inputmode="numeric" style="width:100%; box-sizing:border-box; padding:12px; background:#1e293b; border:1px solid #475569; color:#fff; border-radius:8px;">
                            <label style="display:block; color:#e2e8f0; margin:12px 0 6px;">Replace photos (optional, up to 5)</label>
                            <input type="file" name="photos" accept="image/*" multiple style="width:100%; color:#cbd5e1;">
                            <label style="display:flex; align-items:center; gap:8px; color:#cbd5e1; font-size:13px; margin:12px 0;">
                                <input type="checkbox" name="remove_photos" value="1"> Remove current photos
                            </label>
                            <p style="font-size:12px; color:#fbbf24; line-height:1.5;">Edited listings are sent back for admin approval before appearing in the market.</p>
                            <div style="display:flex; gap:10px;">
                                <button type="submit" class="btn btn-emerald" style="flex:1; padding:12px;">Save changes</button>
                                <button type="button" onclick="closeProductEdit()" style="padding:12px 18px; border-radius:8px; background:#334155; color:#fff; border:0; cursor:pointer;">Cancel</button>
                            </div>
                        </form>
                    </div>
                    {pagination_html}
                    <style>
                        @media (max-width: 900px) {{ .products-grid {{ grid-template-columns: repeat(2, 1fr) !important; }} }}
                        @media (max-width: 600px) {{ .products-grid {{ grid-template-columns: 1fr !important; }} }}
                    </style>
                </div>
            </div>

            <div id="tab_farm_market" style="{show_farm_market}">
                <div class="portal-card" style="max-width:720px; margin:0 auto 20px;">
                    <div class="card-header">🛒 <h3 class="card-title">Farm Market</h3></div>
                    {('<div style="background:rgba(245,158,11,0.15); border:1px solid rgba(245,158,11,0.4); border-radius:12px; padding:14px; margin-bottom:14px; color:#fbbf24; font-weight:700;">✅ Listing submitted. An admin must approve it before it goes live.</div>') if posted else ''}
                    {('<div style="background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.4); border-radius:12px; padding:14px; margin-bottom:14px; color:#fecaca; font-weight:700;">Please enter a product title before posting.</div>') if post_err == "title" else ''}
                    <div style="background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.35); border-radius:12px; padding:14px 16px; margin-bottom:16px; font-size:14px; color:#fecaca; line-height:1.5;">
                        <strong>⚠️ Scam Warning:</strong> Never send money before seeing the goods. Meet in a public place. Use the <b>Report</b> button if a listing looks suspicious. Farm Watch does not handle payments.
                    </div>
                    <p style="font-size:14px; color:#cbd5e1; margin:0 0 16px 0; line-height:1.45;">
                        Promote your crops, livestock, tools or produce. Neighbours can contact you directly.
                        Posting earns <b style="color:#6ee7b7;">+{PRODUCT_POST_XP} XP</b>.
                    </p>
                    <a href="/portal/feed?active_tab=market&market_mine=1" class="btn btn-emerald" style="display:inline-block; padding:10px 16px; margin-bottom:14px; text-decoration:none;">Manage my listings</a>
                    <form action="/portal/market/post" method="post" enctype="multipart/form-data" style="background:rgba(0,0,0,0.2); padding:16px; border-radius:14px; margin-bottom:8px;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">What are you selling?</label>
                        <input type="text" name="title" required maxlength="{MAX_PRODUCT_TITLE}" placeholder="e.g. Fresh cassava, 50kg bags"
                               style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; box-sizing:border-box; margin-bottom:12px;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Category</label>
                        <select name="category" id="prod_category" onchange="toggleLivestock()" style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; margin-bottom:12px;">
                            {category_options}
                        </select>
                        <div id="livestock_fields" style="display:none; background:rgba(16,185,129,0.06); border:1px solid rgba(16,185,129,0.2); border-radius:12px; padding:12px; margin-bottom:12px;">
                            <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Animal</label>
                            <select name="animal_type" id="animal_type" onchange="toggleAnimal()" style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; margin:6px 0 12px;">
                                <option value="">Select animal</option>
                                {"".join([f'<option value="{a}">{a}</option>' for a in LIVESTOCK_TYPES])}
                            </select>
                            <div id="sex_fields" style="display:none;">
                                <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Sex</label>
                                <select name="animal_sex" style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; margin:6px 0 12px;">
                                    <option value="">Optional</option>
                                    <option value="Male">Male</option>
                                    <option value="Female">Female</option>
                                    <option value="Both">Both</option>
                                </select>
                            </div>
                            <div id="cow_fields" style="display:none;">
                                <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Cow breed</label>
                                <select name="cow_breed" id="cow_breed" onchange="toggleBreed()" style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; margin:6px 0 12px;">
                                    <option value="">Select breed</option>
                                    {"".join([f'<option value="{b}">{b}</option>' for b in COW_BREEDS])}
                                </select>
                                <div id="breed_custom_wrap" style="display:none;">
                                    <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Enter breed (optional)</label>
                                    <input type="text" name="breed_custom" maxlength="40" placeholder="Type breed name"
                                           style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; margin:6px 0 12px; box-sizing:border-box;">
                                </div>
                            </div>
                            <div id="exotic_fields" style="display:none;">
                                <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Exotic pet type (optional)</label>
                                <input type="text" name="exotic_type" maxlength="40" placeholder="e.g. Parrot, Rabbit, Tortoise"
                                       style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; margin:6px 0 12px; box-sizing:border-box;">
                            </div>
                        </div>
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Price</label>
                        <input type="text" name="price" placeholder="e.g. ₦15,000 per bag" maxlength="40"
                               style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; box-sizing:border-box; margin-bottom:12px;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Details</label>
                        <input type="text" name="description" maxlength="{MAX_PRODUCT_DESC}" placeholder="Quality, quantity, location notes…"
                               style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; box-sizing:border-box; margin-bottom:12px;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Photos (optional, up to 5)</label>
                        <input type="file" name="photos" accept="image/*" multiple
                               style="width:100%; padding:12px; font-size:14px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; box-sizing:border-box; margin-bottom:12px;">
                        <p style="font-size:12px; color:#94a3b8; margin:0 0 12px 0;">iPhone and Android photos are accepted. Images are resized automatically.</p>
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Contact phone (optional)</label>
                        <input type="text" name="contact_phone" placeholder="Leave blank to use your registered number" inputmode="numeric"
                               style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; box-sizing:border-box; margin-bottom:14px;">
                        <button type="submit" class="btn btn-emerald" style="width:100%; padding:16px; font-size:17px;">Post to Market</button>
                    </form>
                </div>
            </div>
            <div id="tab_messages" style="{show_messages}">
                <div class="portal-card" style="max-width:720px; margin:0 auto; min-height:400px;">
                    <div class="card-header">💬 <h3 class="card-title">Messages</h3></div>
                    {('<div style="background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.3); border-radius:10px; padding:12px 16px; margin-bottom:14px; color:#6ee7b7; font-weight:700;">✅ Invite sent!</div>') if invite_sent else ''}
                    {peer_card_html or '<div style="padding:20px; text-align:center; color:#94a3b8;">Select a friend from Community or search below.</div>'}
                    <div style="max-height:300px; overflow-y:auto; margin:12px 0; padding:12px; background:rgba(0,0,0,0.25); border-radius:12px; min-height:100px;">
                        {messages_log_html or '<p style="color:var(--text-muted); font-size:14px; text-align:center; margin:20px 0;">No messages yet. Say hello!</p>'}
                    </div>
                    {send_form_html or ''}
                    <form action="/portal/feed" method="get" style="margin-top:20px; display:flex; gap:10px;">
                        <input type="hidden" name="active_tab" value="messages">
                        <input type="text" name="search_phone" placeholder="Or search a number..." value=""
                               style="flex:1; padding:12px; background:#1e293b; border:1px solid #475569; color:white; border-radius:10px;">
                        <button type="submit" class="btn btn-emerald" style="padding:12px 20px;">Search</button>
                    </form>
                </div>
            </div>
            <div id="tab_family" style="{show_family}">
                <div class="portal-card" style="margin-bottom:20px;border-color:rgba(167,139,250,.25);">
                    <div class="card-header" style="border-color:rgba(167,139,250,.2);">👨‍👩‍👧‍👦 <h3 class="card-title" style="color:#c4b5fd;">Family & Descendants Meetings</h3></div>
                    <p style="color:#cbd5e1;line-height:1.55;">Create a family circle, invite relatives with a code or QR scan, leave messages, and open a video call together. Meetings are limited to signed-in, approved farmer members.</p>
                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px;">
                        <div style="background:rgba(0,0,0,.2);padding:16px;border-radius:12px;">
                            <h4 style="color:#6ee7b7;margin-top:0;">Start a family meeting</h4>
                            {family_create_html}
                        </div>
                        <div style="background:rgba(0,0,0,.2);padding:16px;border-radius:12px;">
                            <h4 style="color:#c4b5fd;margin-top:0;">Join with an invite code</h4>
                            <form action="/portal/family/join" method="post" data-auto-refresh style="display:grid;gap:10px;">
                                <label for="family_invite_code" style="color:#e2e8f0;">Enter the 16-character code</label>
                                <input id="family_invite_code" name="invite_code" required minlength="16" maxlength="16" pattern="[A-Fa-f0-9]{{16}}" placeholder="e.g. 8F3A10B7C24D9901" style="text-transform:uppercase;">
                                <button class="btn btn-emerald" type="submit">Join family</button>
                            </form>
                            <p style="font-size:12px;color:#94a3b8;">Or open the invitation link / scan its QR code and sign in to join.</p>
                        </div>
                    </div>
                </div>
                <div class="portal-grid">{family_cards_html}</div>
            </div>
        </div>
        <div id="radar_screen" class="glass-panel" style="max-width: 550px; margin: 60px auto; text-align: center; display: none;"><div class="radar-spinner"></div><span class="badge badge-amber pulse" style="margin-bottom: 16px;">Transmission Channel Engaged</span><h2>Transmitting...</h2></div>
        <div id="nature_moment" role="status" aria-live="polite" style="display:none; position:fixed; right:16px; bottom:84px; z-index:2100; width:min(340px, calc(100vw - 32px)); box-sizing:border-box; background:#0f172a; border:1px solid rgba(110,231,183,0.25); border-radius:16px; padding:14px 16px; box-shadow:0 12px 32px rgba(0,0,0,0.4);">
            <div style="display:flex; align-items:flex-start; gap:12px;">
                <div id="nature_moment_emoji" aria-hidden="true" style="font-size:34px; line-height:1.2;">🐇🥕</div>
                <div style="flex:1; min-width:0;">
                    <div id="nature_moment_title" style="font-weight:800; color:#e2e8f0; margin-bottom:4px;">A garden visitor</div>
                    <div id="nature_moment_text" style="font-size:13px; line-height:1.45; color:#cbd5e1;"></div>
                </div>
                <button type="button" onclick="hideNatureMoment()" aria-label="Close nature moment" style="background:transparent; border:0; color:#cbd5e1; font-size:22px; line-height:1; cursor:pointer; padding:0 2px;">×</button>
            </div>
        </div>
        <div id="radio_mini_player" role="region" aria-label="Farm Radio controls" style="display:none; position:fixed; top:12px; right:12px; z-index:2200; width:min(380px, calc(100vw - 24px)); box-sizing:border-box; background:#0f172a; border:1px solid rgba(167,139,250,0.4); border-radius:12px; padding:10px 12px; box-shadow:0 8px 24px rgba(0,0,0,0.35);">
            <div style="display:flex; align-items:center; gap:10px;">
                <div style="flex:1; min-width:0;">
                    <div style="font-size:12px; color:#c4b5fd; font-weight:800;">📻 Farm Radio</div>
                    <div id="radio_mini_station" style="font-size:13px; color:#e2e8f0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">No station selected</div>
                    <div id="radio_mini_status" aria-live="polite" style="font-size:11px; color:#94a3b8;">Stopped</div>
                </div>
                <button id="radio_mini_toggle" type="button" onclick="toggleRadioPlayback()" class="btn" aria-label="Pause radio" style="padding:8px 10px; background:rgba(16,185,129,0.15); color:#6ee7b7; border:1px solid rgba(16,185,129,0.35);">Pause</button>
                <button type="button" onclick="stopRadio()" class="btn" aria-label="Stop radio" style="padding:8px 10px; background:rgba(239,68,68,0.12); color:#fecaca; border:1px solid rgba(239,68,68,0.3);">Stop</button>
            </div>
        </div>
        <script>
            async function triggerEchoAnimation(e, aId) {{ e.preventDefault(); const btn = document.getElementById('echo_btn_' + aId); btn.disabled = true; btn.innerText = "📡 Relaying..."; try {{ const res = await fetch('/portal/alert/relay', {{ method: 'POST', body: new FormData(e.target) }}); if (res.status === 200) {{ const newXp = await res.text(); document.getElementById('grid_score_display').innerText = "⚡ " + newXp + " Grid XP"; btn.className = "btn"; btn.style.background = "#10b981"; btn.innerText = "✅ Dispatched"; }} }} catch(err) {{ console.error(err); }} }}
            async function executeTransmissionSequence(e) {{
                e.preventDefault();
                const form = e.currentTarget;
                const radarScreen = document.getElementById('radar_screen');
                const submitButton = form.querySelector('button[type="submit"]');
                if (submitButton) submitButton.disabled = true;
                if (radarScreen) radarScreen.style.display = 'block';
                try {{
                    const res = await fetch(form.action, {{ method: form.method, body: new FormData(form), credentials: 'same-origin' }});
                    if (!res.ok) {{
                        let errorMessage = 'Alert could not be sent. Please check the form and try again.';
                        try {{
                            const errorData = await res.json();
                            if (typeof errorData.detail === 'string') errorMessage = errorData.detail;
                        }} catch (parseError) {{
                            console.error('Could not read alert error response:', parseError);
                        }}
                        throw new Error(errorMessage);
                    }}
                    form.reset();
                    showFlash('Alert sent successfully', false);
                }} catch (err) {{
                    showFlash(err.message || 'Alert could not be sent. Please try again.', true);
                }} finally {{
                    if (radarScreen) radarScreen.style.display = 'none';
                    if (submitButton) submitButton.disabled = false;
                }}
            }}

            // ----- Farm Radio with Bass / Mid / High EQ -----
            let radioCtx = null, radioSource = null, bassFilter = null, midFilter = null, highFilter = null, radioGain = null;
            let radioPlaying = false;

            function openSocialShare(platform, text, url) {{
                const encodedUrl = encodeURIComponent(url);
                const encodedText = encodeURIComponent(text);
                let target;
                if (platform === 'facebook') {{
                    target = 'https://www.facebook.com/sharer/sharer.php?u=' + encodedUrl + '&quote=' + encodedText;
                }} else if (platform === 'x') {{
                    target = 'https://twitter.com/intent/tweet?text=' + encodedText + '&url=' + encodedUrl;
                }} else {{
                    target = 'https://wa.me/?text=' + encodeURIComponent(text + ' ' + url);
                }}
                window.open(target, '_blank', 'noopener,noreferrer');
            }}

            async function shareOlodeSite() {{
                const url = window.location.origin;
                const title = 'Olode.com.ng';
                const text = 'Join Olode.com.ng — a farming community for connection, safety, and shared knowledge.';
                if (navigator.share) {{
                    try {{
                        await navigator.share({{ title, text, url }});
                        return;
                    }} catch (error) {{
                        if (error.name === 'AbortError') return;
                        console.error('Could not open the share sheet:', error);
                    }}
                }}
                openSocialShare('whatsapp', text, url);
            }}

            async function shareMyProfile(button) {{
                const profileUrl = new URL('/portal/feed', window.location.origin);
                profileUrl.searchParams.set('active_tab', 'community');
                profileUrl.searchParams.set('view_profile', button.dataset.profilePhone || '');
                const url = profileUrl.toString();
                const text = 'Follow me on Olode.com.ng — let’s share farming stories, updates, and community moments.';
                if (navigator.share) {{
                    try {{
                        await navigator.share({{ title: 'Follow me on Olode.com.ng', text, url }});
                        return;
                    }} catch (error) {{
                        if (error.name === 'AbortError') return;
                        console.error('Could not open the profile share sheet:', error);
                    }}
                }}
                openSocialShare('whatsapp', text, url);
            }}

            function getShoutoutCard(id, button) {{
                return button?.closest('.shoutout-entry')?.querySelector('.shoutout-card')
                    || document.getElementById('shoutout-card-' + id);
            }}

            async function shareShoutout(id, button) {{
                const card = getShoutoutCard(id, button);
                if (!card) return;
                const url = new URL('/portal/feed', window.location.origin);
                url.searchParams.set('active_tab', 'shoutouts');
                url.hash = 'shoutout-' + id;
                const text = card.innerText.trim() + '\\n\\nOlode.com.ng';
                try {{
                    const blob = await createShoutoutImage(card);
                    const imageFile = new File([blob], 'olode-shout-out.png', {{ type: 'image/png' }});
                    if (navigator.share && navigator.canShare && navigator.canShare({{ files: [imageFile] }})) {{
                        await navigator.share({{
                            files: [imageFile],
                            title: 'A celebration from Olode.com.ng',
                            text,
                            url: url.toString()
                        }});
                        return;
                    }}
                    const downloadUrl = URL.createObjectURL(blob);
                    const downloadLink = document.createElement('a');
                    downloadLink.href = downloadUrl;
                    downloadLink.download = 'olode-shout-out.png';
                    downloadLink.click();
                    window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
                }} catch (error) {{
                    if (error.name === 'AbortError') return;
                    console.error('Could not create or share the shout-out image:', error);
                }}
                if (navigator.share) {{
                    try {{
                        await navigator.share({{ title: 'A celebration from Olode.com.ng', text, url: url.toString() }});
                        return;
                    }} catch (error) {{
                        if (error.name === 'AbortError') return;
                        console.error('Could not open the shout-out share sheet:', error);
                    }}
                }}
                openSocialShare('whatsapp', text, url.toString());
            }}

            async function createShoutoutImage(card) {{
                const canvas = document.createElement('canvas');
                canvas.width = 1200;
                canvas.height = 630;
                const context = canvas.getContext('2d');
                if (!context) throw new Error('Image export is not supported by this browser.');
                const palettes = {{
                    sunrise: 30,
                    garden: 145,
                    celebration: 320,
                    royal: 260,
                    harvest: 45,
                    ocean: 190,
                    love: 345,
                    simple: 215
                }};
                const templateParts = (card.dataset.template || 'garden-01').split('-');
                const baseHue = palettes[templateParts[0]] ?? palettes.garden;
                const hue = (baseHue + (Number(templateParts[1] || 1) - 1) * 7) % 360;
                const gradient = context.createLinearGradient(0, 0, 1200, 630);
                gradient.addColorStop(0, `hsl(${{hue}} 72% 22%)`);
                gradient.addColorStop(0.55, `hsl(${{hue}} 78% 48%)`);
                gradient.addColorStop(1, `hsl(${{hue}} 90% 82%)`);
                context.fillStyle = gradient;
                context.fillRect(0, 0, canvas.width, canvas.height);
                context.fillStyle = 'rgba(255,255,255,.16)';
                context.beginPath();
                context.arc(1100, 40, 210, 0, Math.PI * 2);
                context.fill();
                context.fillStyle = '#ffffff';
                context.textAlign = 'left';
                context.font = 'bold 25px system-ui, sans-serif';
                context.fillText(card.querySelector('.shoutout-category')?.textContent.trim() || 'CELEBRATION', 72, 90);
                context.font = 'bold 50px system-ui, sans-serif';
                const recipient = card.querySelector('.shoutout-recipient')?.textContent.trim() || '';
                if (recipient) context.fillText(recipient.slice(0, 34), 72, 170);
                const message = card.querySelector('.shoutout-message')?.textContent.trim() || '';
                context.font = '30px system-ui, sans-serif';
                const words = message.split(/\\s+/);
                let line = '';
                let y = recipient ? 245 : 190;
                for (const word of words) {{
                    const nextLine = line ? line + ' ' + word : word;
                    if (context.measureText(nextLine).width > 720 && line) {{
                        context.fillText(line, 72, y);
                        y += 46;
                        line = word;
                        if (y > 480) break;
                    }} else {{
                        line = nextLine;
                    }}
                }}
                if (line && y <= 480) context.fillText(line, 72, y);
                const photo = card.querySelector('img');
                if (photo && photo.complete && photo.naturalWidth) {{
                    const box = {{ x: 850, y: 145, width: 280, height: 350 }};
                    const scale = Math.min(box.width / photo.naturalWidth, box.height / photo.naturalHeight);
                    const width = photo.naturalWidth * scale;
                    const height = photo.naturalHeight * scale;
                    context.save();
                    context.beginPath();
                    context.roundRect(box.x, box.y, box.width, box.height, 22);
                    context.clip();
                    context.drawImage(photo, box.x + (box.width - width) / 2, box.y + (box.height - height) / 2, width, height);
                    context.restore();
                }}
                context.font = 'bold 24px system-ui, sans-serif';
                context.fillText('Olode.com.ng', 72, 565);
                return await new Promise((resolve, reject) => {{
                    canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not export the celebration image.')), 'image/png');
                }});
            }}

            function printShoutout(id, button) {{
                const card = getShoutoutCard(id, button);
                if (!card) return;
                const printWindow = window.open('', '_blank');
                if (!printWindow) {{
                    window.alert('Allow pop-ups to print this celebration card.');
                    return;
                }}
                printWindow.document.write('<!doctype html><html><head><title>Olode.com.ng Shout Out</title><style>body{{font-family:Arial,sans-serif;padding:24px;color:#0f172a}}.card{{max-width:680px;margin:0 auto;border-radius:20px;padding:32px;text-align:center;print-color-adjust:exact;-webkit-print-color-adjust:exact}}img{{display:block;width:144px!important;height:180px!important;max-width:100%;object-fit:contain!important;object-position:center;background:#e2e8f0;border-radius:16px;margin:14px auto;print-color-adjust:exact;-webkit-print-color-adjust:exact}}</style></head><body><main class="card">' + card.innerHTML + '</main></body></html>');
                printWindow.document.close();
                printWindow.focus();
                printWindow.print();
            }}

            function shareRadioStation(platform) {{
                const stationSelect = document.getElementById('radio_station');
                const station = stationSelect && stationSelect.value;
                if (!station) {{
                    const status = document.getElementById('radio_status');
                    status.innerText = 'Choose a station before sharing it.';
                    status.style.color = '#fbbf24';
                    return;
                }}
                const stationName = stationSelect.selectedOptions[0].text;
                const text = 'Listen to ' + stationName + ' (' + station + ') with Farm Radio on Olode.com.ng.';
                openSocialShare(platform, text, window.location.origin);
            }}

            async function shareFamilyInvite(button) {{
                const familyName = button.dataset.familyName || 'our family';
                const url = window.location.origin + button.dataset.inviteUrl;
                const title = familyName + ' family meeting | Olode.com.ng';
                const text = 'You are invited to join ' + familyName + ' on Olode.com.ng. Sign in as an approved farmer to join.';
                if (navigator.share) {{
                    try {{
                        await navigator.share({{ title, text, url }});
                        return;
                    }} catch (error) {{
                        if (error.name === 'AbortError') return;
                        console.error('Could not open the share sheet:', error);
                    }}
                }}
                openSocialShare('whatsapp', text, url);
            }}

            function shareFamilyOnSocial(platform, button) {{
                const familyName = button.dataset.familyName || 'our family';
                const url = window.location.origin + button.dataset.inviteUrl;
                const text = 'Join ' + familyName + ' for family meetings on Olode.com.ng.';
                openSocialShare(platform, text, url);
            }}

            function initRadioAudio() {{
                if (radioCtx) return;
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                radioCtx = new AudioContext();
                const audio = document.getElementById('radio_audio');
                radioSource = radioCtx.createMediaElementSource(audio);

                bassFilter = radioCtx.createBiquadFilter();
                bassFilter.type = 'lowshelf';
                bassFilter.frequency.value = 200;
                bassFilter.gain.value = 0;

                midFilter = radioCtx.createBiquadFilter();
                midFilter.type = 'peaking';
                midFilter.frequency.value = 1000;
                midFilter.Q.value = 1;
                midFilter.gain.value = 0;

                highFilter = radioCtx.createBiquadFilter();
                highFilter.type = 'highshelf';
                highFilter.frequency.value = 3200;
                highFilter.gain.value = 0;

                radioGain = radioCtx.createGain();
                radioGain.gain.value = 0.7;

                radioSource.connect(bassFilter);
                bassFilter.connect(midFilter);
                midFilter.connect(highFilter);
                highFilter.connect(radioGain);
                radioGain.connect(radioCtx.destination);
            }}

            function setEq(band, value) {{
                const v = parseFloat(value);
                if (band === 'bass') {{
                    document.getElementById('bass_val').innerText = v > 0 ? '+' + v : v;
                    if (bassFilter) bassFilter.gain.value = v;
                }} else if (band === 'mid') {{
                    document.getElementById('mid_val').innerText = v > 0 ? '+' + v : v;
                    if (midFilter) midFilter.gain.value = v;
                }} else if (band === 'high') {{
                    document.getElementById('high_val').innerText = v > 0 ? '+' + v : v;
                    if (highFilter) highFilter.gain.value = v;
                }}
            }}

            function setRadioVolume(value) {{
                const v = parseFloat(value) / 100;
                document.getElementById('vol_val').innerText = value + '%';
                if (radioGain) radioGain.gain.value = v;
                const audio = document.getElementById('radio_audio');
                if (audio) audio.volume = v;
            }}

            function updateRadioMiniPlayer() {{
                const audio = document.getElementById('radio_audio');
                const mini = document.getElementById('radio_mini_player');
                const stationSelect = document.getElementById('radio_station');
                const miniStation = document.getElementById('radio_mini_station');
                const miniStatus = document.getElementById('radio_mini_status');
                const miniToggle = document.getElementById('radio_mini_toggle');
                if (!audio || !mini || !stationSelect || !miniStation || !miniStatus || !miniToggle) return;
                const hasStation = Boolean(audio.currentSrc || audio.src);
                mini.style.display = hasStation ? 'block' : 'none';
                miniStation.textContent = stationSelect.selectedOptions[0]?.text || 'Farm Radio';
                miniStatus.textContent = radioPlaying ? 'Playing' : 'Paused';
                miniToggle.textContent = radioPlaying ? 'Pause' : 'Resume';
                miniToggle.setAttribute('aria-label', radioPlaying ? 'Pause radio' : 'Resume radio');
            }}

            async function toggleRadio() {{
                const audio = document.getElementById('radio_audio');
                const station = document.getElementById('radio_station').value;
                const btn = document.getElementById('radio_play_btn');
                const status = document.getElementById('radio_status');

                if (!station) {{
                    status.innerText = 'Please select a station first';
                    status.style.color = '#fbbf24';
                    return;
                }}

                try {{
                    initRadioAudio();
                    if (radioCtx.state === 'suspended') await radioCtx.resume();

                    if (radioPlaying) {{
                        audio.pause();
                        radioPlaying = false;
                        btn.innerText = 'Play';
                        status.innerText = 'Paused';
                        status.style.color = '#94a3b8';
                    }} else {{
                        if (audio.src !== station) {{
                            audio.src = station;
                            status.innerText = 'Tuning in...';
                            status.style.color = '#93c5fd';
                        }}
                        await audio.play();
                        radioPlaying = true;
                        btn.innerText = 'Pause';
                        const name = document.getElementById('radio_station').selectedOptions[0].text;
                        status.innerText = 'Playing: ' + name;
                        status.style.color = '#6ee7b7';
                    }}
                    updateRadioMiniPlayer();
                }} catch (err) {{
                    status.innerText = 'Could not play this station. Try another one.';
                    status.style.color = '#f87171';
                    radioPlaying = false;
                    btn.innerText = 'Play';
                    updateRadioMiniPlayer();
                    console.error(err);
                }}
            }}

            async function toggleRadioPlayback() {{
                const audio = document.getElementById('radio_audio');
                const btn = document.getElementById('radio_play_btn');
                const status = document.getElementById('radio_status');
                if (!audio || !audio.src) return;
                try {{
                    if (radioPlaying) {{
                        audio.pause();
                        radioPlaying = false;
                        if (btn) btn.innerText = 'Play';
                        if (status) {{
                            status.innerText = 'Paused';
                            status.style.color = '#94a3b8';
                        }}
                    }} else {{
                        if (radioCtx && radioCtx.state === 'suspended') await radioCtx.resume();
                        await audio.play();
                        radioPlaying = true;
                        if (btn) btn.innerText = 'Pause';
                        const name = document.getElementById('radio_station').selectedOptions[0].text;
                        if (status) {{
                            status.innerText = 'Playing: ' + name;
                            status.style.color = '#6ee7b7';
                        }}
                    }}
                }} catch (err) {{
                    radioPlaying = false;
                    if (btn) btn.innerText = 'Play';
                    if (status) {{
                        status.innerText = 'Could not resume this station. Try selecting it again.';
                        status.style.color = '#f87171';
                    }}
                    console.error(err);
                }}
                updateRadioMiniPlayer();
            }}

            function stopRadio() {{
                const audio = document.getElementById('radio_audio');
                const btn = document.getElementById('radio_play_btn');
                const status = document.getElementById('radio_status');
                if (audio) {{
                    audio.pause();
                    audio.removeAttribute('src');
                    audio.load();
                }}
                radioPlaying = false;
                if (btn) btn.innerText = 'Play';
                if (status) {{
                    status.innerText = 'Stopped — choose a station and press Play';
                    status.style.color = '#94a3b8';
                }}
                updateRadioMiniPlayer();
            }}

            const radioStationEl = document.getElementById('radio_station');
            if (radioStationEl) radioStationEl.addEventListener('change', function() {{
                const audio = document.getElementById('radio_audio');
                if (audio) {{
                    audio.pause();
                    audio.removeAttribute('src');
                    audio.load();
                }}
                radioPlaying = false;
                document.getElementById('radio_play_btn').innerText = 'Play';
                document.getElementById('radio_status').innerText = 'Station changed — press Play';
                document.getElementById('radio_status').style.color = '#94a3b8';
                updateRadioMiniPlayer();
            }});

            document.addEventListener('submit', async event => {{
                const form = event.target;
                if (!(form instanceof HTMLFormElement) || !form.hasAttribute('data-auto-refresh') || event.defaultPrevented) return;
                event.preventDefault();
                const submitButton = form.querySelector('button[type="submit"], input[type="submit"]');
                const originalLabel = submitButton && (submitButton.innerText || submitButton.value);
                let feedback = form.querySelector('[data-submit-feedback]');
                if (!feedback) {{
                    feedback = document.createElement('p');
                    feedback.dataset.submitFeedback = 'true';
                    feedback.setAttribute('role', 'status');
                    feedback.style.cssText = 'grid-column:1/-1;margin:4px 0;color:#fca5a5;font-size:13px;';
                    form.appendChild(feedback);
                }}
                if (submitButton) {{
                    submitButton.disabled = true;
                    if (submitButton instanceof HTMLButtonElement) submitButton.innerText = 'Updating…';
                    else submitButton.value = 'Updating…';
                }}
                feedback.textContent = '';
                try {{
                    const response = await fetch(form.action, {{
                        method: form.method || 'POST',
                        body: new FormData(form),
                        credentials: 'same-origin',
                        cache: 'no-store'
                    }});
                    if (!response.ok || !response.redirected) {{
                        let errorMessage = 'This action could not be completed. Please try again.';
                        try {{
                            const payload = await response.json();
                            if (typeof payload.detail === 'string') errorMessage = payload.detail;
                        }} catch (parseError) {{
                            console.error('Could not read the family meeting response:', parseError);
                        }}
                        throw new Error(errorMessage);
                    }}
                    const refreshUrl = new URL(response.url, window.location.origin);
                    if (refreshUrl.origin !== window.location.origin) throw new Error('The update returned an unexpected destination.');
                    refreshUrl.searchParams.set('_refresh', String(Date.now()));
                    window.location.replace(refreshUrl.toString());
                }} catch (error) {{
                    feedback.textContent = error.message || 'This action could not be completed. Please try again.';
                    if (submitButton) {{
                        submitButton.disabled = false;
                        if (submitButton instanceof HTMLButtonElement) submitButton.innerText = originalLabel;
                        else submitButton.value = originalLabel;
                    }}
                    console.error('Could not update the family meeting:', error);
                }}
            }});

            // Switch the portal's pre-rendered tabs without unloading the radio audio element.
            const portalTabPanels = {{
                incidents: document.getElementById('tab_incidents'),
                messages: document.getElementById('tab_messages'),
                community: document.getElementById('tab_community'),
                friends: document.getElementById('tab_friends'),
                shoutouts: document.getElementById('tab_shoutouts'),
                market: document.getElementById('tab_market'),
                farm_market: document.getElementById('tab_farm_market'),
                family: document.getElementById('tab_family')
            }};
            function showPortalTab(tab, updateHistory, targetUrl) {{
                if (!portalTabPanels[tab]) return;
                Object.entries(portalTabPanels).forEach(([name, panel]) => {{
                    if (panel) panel.style.display = name === tab ? 'block' : 'none';
                }});
                document.querySelectorAll('.tab-bar a').forEach(link => {{
                    const isActive = link === document.getElementById('messages-nav-link')
                        ? tab === 'messages'
                        : new URL(link.href, window.location.href).searchParams.get('active_tab') === tab;
                    link.style.background = isActive ? 'rgba(16,185,129,0.2)' : 'transparent';
                    link.style.color = isActive ? '#10b981' : 'var(--text-muted)';
                    link.setAttribute('aria-current', isActive ? 'page' : 'false');
                }});
                if (updateHistory && targetUrl) history.pushState({{ activeTab: tab }}, '', targetUrl);
            }}

            function portalTabFromLocation() {{
                if (window.location.pathname === '/portal/messages') return 'messages';
                const tab = new URLSearchParams(window.location.search).get('active_tab') || 'incidents';
                return portalTabPanels[tab] ? tab : 'incidents';
            }}

            async function navigateProfile(url, addHistory) {{
                const targetUrl = new URL(url, window.location.href);
                if (targetUrl.origin !== window.location.origin || targetUrl.pathname !== '/portal/feed') {{
                    window.location.assign(targetUrl.href);
                    return;
                }}
                try {{
                    const response = await fetch(targetUrl.href, {{
                        credentials: 'same-origin',
                        cache: 'no-store'
                    }});
                    if (!response.ok) throw new Error('Could not load this profile.');
                    const page = new DOMParser().parseFromString(await response.text(), 'text/html');
                    const incomingProfile = page.getElementById('profile-view');
                    const currentProfile = document.getElementById('profile-view');
                    if (!incomingProfile || !currentProfile) throw new Error('Profile content was not available.');
                    const isProfilePage = page.body.classList.contains('profile-view');
                    currentProfile.replaceWith(incomingProfile);
                    document.body.classList.toggle('profile-view', isProfilePage);
                    showPortalTab(portalTabFromUrl(targetUrl), false);
                    if (addHistory) history.pushState({{ profileView: isProfilePage }}, '', targetUrl);
                    window.scrollTo(0, 0);
                }} catch (error) {{
                    console.error('Could not navigate to profile without reloading:', error);
                    window.location.assign(targetUrl.href);
                }}
            }}

            function portalTabFromUrl(url) {{
                if (url.pathname === '/portal/messages') return 'messages';
                const tab = url.searchParams.get('active_tab') || 'incidents';
                return portalTabPanels[tab] ? tab : 'incidents';
            }}

            document.addEventListener('click', event => {{
                if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                if (!(event.target instanceof Element)) return;
                const link = event.target.closest('a[href]');
                if (!link) return;
                const url = new URL(link.href, window.location.href);
                const isProfileLink = url.pathname === '/portal/feed' && url.searchParams.has('view_profile');
                const isProfileClose = document.body.classList.contains('profile-view')
                    && link.closest('#profile-view')
                    && url.pathname === '/portal/feed';
                if (!isProfileLink && !isProfileClose) return;
                event.preventDefault();
                navigateProfile(url, true);
            }});

            document.querySelectorAll('.tab-bar a').forEach(link => {{
                link.addEventListener('click', event => {{
                    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                    const url = new URL(link.href, window.location.href);
                    const tab = link === document.getElementById('messages-nav-link')
                        ? 'messages'
                        : url.searchParams.get('active_tab');
                    if (!portalTabPanels[tab]) return;
                    event.preventDefault();
                    const nextUrl = tab === 'messages'
                        ? new URL('/portal/feed?active_tab=messages', window.location.origin)
                        : url;
                    showPortalTab(tab, true, nextUrl);
                }});
            }});

            window.addEventListener('popstate', () => {{
                const url = new URL(window.location.href);
                if (url.pathname === '/portal/feed' && (url.searchParams.has('view_profile') || document.body.classList.contains('profile-view'))) {{
                    navigateProfile(url, false);
                    return;
                }}
                document.body.classList.remove('profile-view');
                showPortalTab(portalTabFromUrl(url), false);
            }});
            showPortalTab(portalTabFromLocation(), false);
            if (window.location.hash.startsWith('#status-') || window.location.hash.startsWith('#shoutout-')) {{
                window.requestAnimationFrame(() => {{
                    const target = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
                    if (target) target.scrollIntoView({{ block: 'center' }});
                }});
            }}
            updateRadioMiniPlayer();
            const profileUpdatedNotice = document.getElementById('profile-updated-notice');
            if (profileUpdatedNotice) {{
                window.setTimeout(() => profileUpdatedNotice.remove(), 200);
            }}

            // ----- Occasional, gentle nature moments for the community tab -----
            const natureMomentStories = [
                {{ emoji: '🐇🥕', title: 'A rabbit found a carrot!', text: 'Hop along for a tiny garden adventure. Can you spot another carrot near the vegetables?' }},
                {{ emoji: '🦋🌼', title: 'Butterfly garden visit', text: 'A butterfly is looking for a flower. Take a gentle breath and imagine where it will land.' }},
                {{ emoji: '🌧️⛈️', title: 'A gentle rain is passing', text: 'The clouds are watering the crops. Stay cosy until the rain has passed.' }},
                {{ emoji: '🐞🍃', title: 'Little garden explorer', text: 'A ladybird is checking the leaves for a sunny place to rest.' }}
            ];
            let natureMomentTimer = null;
            let natureMomentHideTimer = null;

            function hideNatureMoment() {{
                const box = document.getElementById('nature_moment');
                if (box) box.style.display = 'none';
                if (natureMomentHideTimer) clearTimeout(natureMomentHideTimer);
            }}

            function scheduleNatureMoment(delay) {{
                if (natureMomentTimer) clearTimeout(natureMomentTimer);
                natureMomentTimer = setTimeout(showNatureMoment, delay);
            }}

            function showNatureMoment() {{
                const community = document.getElementById('tab_community');
                const box = document.getElementById('nature_moment');
                if (!community || !box || document.hidden || getComputedStyle(community).display === 'none') {{
                    scheduleNatureMoment(60000);
                    return;
                }}
                const now = Date.now();
                let lastShown = 0;
                try {{ lastShown = Number(sessionStorage.getItem('farmwatch_last_nature_moment') || 0); }}
                catch (error) {{ console.warn('Could not read nature-moment timing:', error); }}
                const cooldown = 5 * 60 * 1000;
                if (now - lastShown < cooldown) {{
                    scheduleNatureMoment(cooldown - (now - lastShown));
                    return;
                }}

                const story = natureMomentStories[Math.floor(Math.random() * natureMomentStories.length)];
                document.getElementById('nature_moment_emoji').textContent = story.emoji;
                document.getElementById('nature_moment_title').textContent = story.title;
                document.getElementById('nature_moment_text').textContent = story.text;
                box.style.display = 'block';
                try {{ sessionStorage.setItem('farmwatch_last_nature_moment', String(now)); }}
                catch (error) {{ console.warn('Could not save nature-moment timing:', error); }}
                natureMomentHideTimer = setTimeout(hideNatureMoment, 15000);
                scheduleNatureMoment(5 * 60 * 1000 + Math.floor(Math.random() * 4 * 60 * 1000));
            }}

            scheduleNatureMoment(60000 + Math.floor(Math.random() * 60000));

            // ----- Simple game sounds (Web Audio) -----
            let sfxCtx = null;
            function ensureSfx() {{
                if (!sfxCtx) sfxCtx = new (window.AudioContext || window.webkitAudioContext)();
                if (sfxCtx.state === 'suspended') sfxCtx.resume();
                return sfxCtx;
            }}
            function playTone(freq, duration, type, vol) {{
                try {{
                    const ctx = ensureSfx();
                    const o = ctx.createOscillator();
                    const g = ctx.createGain();
                    o.type = type || 'sine';
                    o.frequency.value = freq;
                    g.gain.value = vol || 0.15;
                    o.connect(g); g.connect(ctx.destination);
                    o.start();
                    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
                    o.stop(ctx.currentTime + duration);
                }} catch (e) {{}}
            }}
            function sfxDart(score) {{
                playTone(200 + score * 4, 0.12, 'square', 0.12);
                if (score >= 50) {{
                    setTimeout(() => playTone(520, 0.15, 'sine', 0.18), 100);
                    setTimeout(() => playTone(780, 0.2, 'sine', 0.15), 220);
                }}
            }}
            function sfxHit() {{
                playTone(660, 0.1, 'sine', 0.16);
                setTimeout(() => playTone(880, 0.12, 'sine', 0.12), 80);
            }}
            function sfxMiss() {{
                playTone(180, 0.08, 'triangle', 0.08);
            }}
            function sfxWin() {{
                playTone(523, 0.12, 'sine', 0.15);
                setTimeout(() => playTone(659, 0.12, 'sine', 0.15), 120);
                setTimeout(() => playTone(784, 0.2, 'sine', 0.18), 240);
            }}

            // ----- XP toast (no page reload) -----
            function showXpToast(amount, balance) {{
                const t = document.createElement('div');
                t.style.cssText = 'position:fixed; top:80px; right:20px; background:rgba(16,185,129,0.95); color:#fff; padding:12px 18px; border-radius:12px; font-weight:800; font-size:16px; z-index:2000; box-shadow:0 8px 24px rgba(0,0,0,0.3); opacity:1; transition:opacity 0.6s;';
                t.innerHTML = '+' + amount + ' XP<br><span style="font-size:13px; font-weight:600;">Balance: ' + balance + '</span>';
                document.body.appendChild(t);
                const el = document.getElementById('grid_score_display');
                if (el) el.innerText = '⚡ ' + balance + ' Grid XP';
                setTimeout(() => {{ t.style.opacity = '0'; }}, 1800);
                setTimeout(() => t.remove(), 2500);
            }}

            // ----- Market one-at-a-time viewer -----
            let marketCards = [];
            let marketIndex = 0;
            function initMarketViewer() {{
                const wrap = document.getElementById('market-cards');
                if (!wrap) return;
                marketCards = Array.from(wrap.children).filter(el => el.classList && el.classList.contains('product-card'));
                if (marketCards.length === 0) return;
                marketCards.forEach((c, i) => {{
                    c.style.display = i === 0 ? 'block' : 'none';
                }});
                updateMarketCounter();
                const listInner = document.getElementById('market-list-inner');
                if (listInner) {{
                    marketCards.forEach((card, i) => {{
                        const titleEl = card.querySelector('.prod-title');
                        const title = titleEl ? titleEl.textContent.trim() : 'Listing';
                        const btn = document.createElement('button');
                        btn.type = 'button';
                        btn.style.cssText = 'text-align:left; padding:12px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:12px; color:#e2e8f0; cursor:pointer; font-weight:600;';
                        btn.textContent = (i + 1) + '. ' + title.slice(0, 70);
                        btn.onclick = () => {{ showMarketSingle(); marketGo(i); }};
                        listInner.appendChild(btn);
                    }});
                }}
            }}
            function updateMarketCounter() {{
                const el = document.getElementById('market-counter');
                if (el && marketCards.length) el.textContent = (marketIndex + 1) + ' / ' + marketCards.length;
            }}
            function marketGo(i) {{
                if (!marketCards.length) return;
                marketIndex = Math.max(0, Math.min(i, marketCards.length - 1));
                marketCards.forEach((c, idx) => c.style.display = idx === marketIndex ? 'block' : 'none');
                updateMarketCounter();
            }}
            function marketPrev() {{ marketGo(marketIndex - 1); }}
            function marketNext() {{ marketGo(marketIndex + 1); }}
            function showMarketList() {{
                const s = document.getElementById('market-single');
                const l = document.getElementById('market-list');
                if (s) s.style.display = 'none';
                if (l) l.style.display = 'block';
            }}
            function showMarketSingle() {{
                const s = document.getElementById('market-single');
                const l = document.getElementById('market-list');
                if (l) l.style.display = 'none';
                if (s) s.style.display = 'block';
            }}
            // Photo pager inside a listing
            function photoPrev(btn) {{
                const wrap = btn.closest('.photo-wrap');
                if (!wrap) return;
                const imgs = wrap.querySelectorAll('.prod-photo');
                let cur = 0;
                imgs.forEach((img, i) => {{ if (img.style.display !== 'none') cur = i; }});
                const next = (cur - 1 + imgs.length) % imgs.length;
                imgs.forEach((img, i) => img.style.display = i === next ? 'block' : 'none');
                const counter = wrap.querySelector('.photo-counter');
                if (counter) counter.textContent = (next + 1) + ' / ' + imgs.length;
            }}
            function photoNext(btn) {{
                const wrap = btn.closest('.photo-wrap');
                if (!wrap) return;
                const imgs = wrap.querySelectorAll('.prod-photo');
                let cur = 0;
                imgs.forEach((img, i) => {{ if (img.style.display !== 'none') cur = i; }});
                const next = (cur + 1) % imgs.length;
                imgs.forEach((img, i) => img.style.display = i === next ? 'block' : 'none');
                const counter = wrap.querySelector('.photo-counter');
                if (counter) counter.textContent = (next + 1) + ' / ' + imgs.length;
            }}
            // Full-screen photo expand
            function openPhoto(src) {{
                let overlay = document.getElementById('photo-overlay');
                if (!overlay) {{
                    overlay = document.createElement('div');
                    overlay.id = 'photo-overlay';
                    overlay.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.92); z-index:99999; display:flex; align-items:center; justify-content:center; flex-direction:column;';
                    overlay.innerHTML = '<img id="photo-overlay-img" style="max-width:92%; max-height:80vh; border-radius:12px;"><button type="button" onclick="closePhoto()" style="margin-top:16px; padding:10px 20px; background:#10b981; color:#fff; border:none; border-radius:10px; font-weight:700; cursor:pointer;">Close</button>';
                    overlay.onclick = (e) => {{ if (e.target === overlay) closePhoto(); }};
                    document.body.appendChild(overlay);
                }}
                document.getElementById('photo-overlay-img').src = src;
                overlay.style.display = 'flex';
            }}
            function closePhoto() {{
                const o = document.getElementById('photo-overlay');
                if (o) o.style.display = 'none';
            }}
            document.addEventListener('DOMContentLoaded', initMarketViewer);
            // Keyboard left/right
            document.addEventListener('keydown', (e) => {{
                if (document.getElementById('market-single') && document.getElementById('market-single').style.display !== 'none') {{
                    if (e.key === 'ArrowLeft') marketPrev();
                    if (e.key === 'ArrowRight') marketNext();
                }}
            }});
            // Simple swipe
            let touchStartX = 0;
            document.addEventListener('touchstart', (e) => {{ touchStartX = e.changedTouches[0].screenX; }}, {{passive:true}});
            document.addEventListener('touchend', (e) => {{
                if (!document.getElementById('market-single') || document.getElementById('market-single').style.display === 'none') return;
                const dx = e.changedTouches[0].screenX - touchStartX;
                if (dx > 50) marketPrev();
                if (dx < -50) marketNext();
            }}, {{passive:true}});

            // ----- Share listing (professional message) -----
            function shareListing(title, price) {{
                const site = "https://olode.com.ng";
                const priceBit = price ? " for " + price : "";
                const text = "I just found this on Farm Watch: " + title + priceBit + ".\\n\\nBrowse more farm produce and livestock at " + site + " — connecting Nigerian farmers and protecting our communities.";
                if (navigator.share) {{
                    navigator.share({{ title: title, text: text, url: site }}).catch(() => {{}});
                }} else {{
                    navigator.clipboard.writeText(text).then(() => {{
                        showFlash("Share message copied — paste it anywhere");
                    }}).catch(() => {{
                        prompt("Copy this message to share:", text);
                    }});
                }}
            }}

            // General success flash (3 seconds, no page jump)
            function showFlash(message, isError) {{
                const t = document.createElement('div');
                const bg = isError ? 'rgba(239,68,68,0.95)' : 'rgba(16,185,129,0.95)';
                t.style.cssText = 'position:fixed; top:24px; left:50%; transform:translateX(-50%); background:' + bg + '; color:#fff; padding:14px 28px; border-radius:14px; font-weight:800; font-size:16px; z-index:9999; box-shadow:0 10px 30px rgba(0,0,0,0.4); opacity:1; transition:opacity 0.5s, transform 0.3s; text-align:center; max-width:90%;';
                t.innerHTML = (isError ? '⚠️ ' : '✅ ') + message;
                document.body.appendChild(t);
                setTimeout(() => {{ t.style.opacity = '0'; t.style.transform = 'translateX(-50%) translateY(-10px)'; }}, 2700);
                setTimeout(() => t.remove(), 3300);
            }}

            function enableMessageNotifications() {{
                if (!('Notification' in window)) {{
                    showFlash('This browser does not support desktop notifications', true);
                    return;
                }}
                Notification.requestPermission().then(permission => {{
                    showFlash(permission === 'granted'
                        ? 'Message and friend request alerts enabled'
                        : 'Allow notifications in your browser settings to receive desktop alerts',
                        permission !== 'granted');
                }});
            }}

            function showProductStatusNotification(notification) {{
                const toast = document.createElement('a');
                toast.href = '/portal/feed?active_tab=farm_market&market_mine=1';
                toast.style.cssText = 'position:fixed;top:24px;right:20px;z-index:10001;display:block;width:min(360px,calc(100vw - 40px));padding:16px;background:#0f172a;color:#f8fafc;border:1px solid rgba(52,211,153,.5);border-radius:14px;box-shadow:0 12px 36px rgba(0,0,0,.45);text-decoration:none;';
                const heading = document.createElement('strong');
                heading.textContent = notification.status === 'Active'
                    ? '✅ Your advert was approved'
                    : 'ℹ️ Your advert was not approved';
                const title = document.createElement('div');
                title.textContent = notification.title;
                title.style.cssText = 'margin-top:7px;color:#cbd5e1;font-size:14px;line-height:1.4;overflow-wrap:anywhere;';
                const hint = document.createElement('div');
                hint.textContent = 'Tap to view your marketplace listings';
                hint.style.cssText = 'margin-top:8px;color:#6ee7b7;font-size:12px;font-weight:700;';
                toast.append(heading, title, hint);
                document.body.appendChild(toast);
                setTimeout(() => toast.remove(), 9000);
            }}

            async function pollFarmProductNotifications() {{
                try {{
                    const response = await fetch('/portal/market/notifications', {{
                        credentials: 'same-origin',
                        cache: 'no-store'
                    }});
                    if (!response.ok) return;
                    const data = await response.json();
                    const notifications = data.notifications || [];
                    if (!notifications.length) return;
                    const badge = document.getElementById('market-notification-count');
                    if (badge) {{
                        badge.textContent = '0';
                        badge.style.display = 'none';
                    }}
                    notifications.forEach(showProductStatusNotification);
                }} catch (error) {{
                    console.error('Could not check advert notifications:', error);
                }}
            }}
            pollFarmProductNotifications();
            setInterval(pollFarmProductNotifications, 15000);

            function showIncomingMessageNotification(message, totalNew) {{
                const title = message.kind === 'marketplace' ? 'Marketplace message' : 'New friend message';
                const toast = document.createElement('a');
                toast.href = '/portal/chat?with=' + encodeURIComponent(message.sender_phone);
                toast.style.cssText = 'position:fixed;top:24px;right:20px;z-index:10000;display:block;width:min(360px,calc(100vw - 40px));padding:16px;background:#0f172a;color:#f8fafc;border:1px solid rgba(52,211,153,.5);border-radius:14px;box-shadow:0 12px 36px rgba(0,0,0,.45);text-decoration:none;';
                const heading = document.createElement('strong');
                heading.textContent = title + ' from ' + message.sender_name;
                const preview = document.createElement('div');
                preview.textContent = message.body;
                preview.style.cssText = 'margin-top:7px;color:#cbd5e1;font-size:14px;line-height:1.4;overflow-wrap:anywhere;';
                const count = document.createElement('div');
                count.textContent = totalNew > 1 ? totalNew + ' unread messages — tap to open' : 'Tap to open message';
                count.style.cssText = 'margin-top:8px;color:#6ee7b7;font-size:12px;font-weight:700;';
                toast.append(heading, preview, count);
                document.body.appendChild(toast);
                setTimeout(() => toast.remove(), 9000);
                if ('Notification' in window && Notification.permission === 'granted') {{
                    const notification = new Notification(title, {{
                        body: message.sender_name + ': ' + message.body.slice(0, 120),
                        tag: 'farmwatch-message-' + message.id
                    }});
                    notification.onclick = () => {{
                        window.focus();
                        window.location.href = toast.href;
                    }};
                }}
            }}

            let notifiedFriendRequestIds = new Set(
                Array.from(document.querySelectorAll('#pending-friend-request-list [data-friend-request-id]'))
                    .map(request => String(request.dataset.friendRequestId))
            );
            try {{
                const storedFriendRequestIds = JSON.parse(sessionStorage.getItem('farmwatch_notified_friend_requests') || '[]');
                if (Array.isArray(storedFriendRequestIds)) {{
                    storedFriendRequestIds.forEach(id => notifiedFriendRequestIds.add(String(id)));
                }}
            }} catch (error) {{
                console.warn('Could not restore friend-request notification state:', error);
            }}

            function showIncomingFriendRequestNotification(request) {{
                const profileUrl = new URL('/portal/feed', window.location.origin);
                profileUrl.searchParams.set('active_tab', 'friends');
                const toast = document.createElement('a');
                toast.href = profileUrl.pathname + profileUrl.search;
                toast.style.cssText = 'position:fixed;top:24px;right:20px;z-index:10002;display:block;width:min(360px,calc(100vw - 40px));padding:16px;background:#1f1020;color:#f8fafc;border:1px solid rgba(244,114,182,.55);border-radius:14px;box-shadow:0 12px 36px rgba(0,0,0,.45);text-decoration:none;';
                const heading = document.createElement('strong');
                heading.textContent = '👋 New friend request';
                const sender = document.createElement('div');
                sender.textContent = request.requester_name + ' would like to connect';
                sender.style.cssText = 'margin-top:7px;color:#e2e8f0;font-size:14px;line-height:1.4;overflow-wrap:anywhere;';
                const hint = document.createElement('div');
                hint.textContent = 'Tap to review the request';
                hint.style.cssText = 'margin-top:8px;color:#f9a8d4;font-size:12px;font-weight:700;';
                toast.append(heading, sender, hint);
                document.body.appendChild(toast);
                setTimeout(() => toast.remove(), 9000);
                if ('Notification' in window && Notification.permission === 'granted') {{
                    const notification = new Notification('New friend request', {{
                        body: request.requester_name + ' would like to connect',
                        tag: 'farmwatch-friend-request-' + request.id
                    }});
                    notification.onclick = () => {{
                        window.focus();
                        window.location.href = toast.href;
                    }};
                }}
            }}

            function updateFriendRequestPanel(data) {{
                const requests = Array.isArray(data.friend_requests) ? data.friend_requests : [];
                const count = Number(data.friend_request_count) || 0;
                const counter = document.getElementById('friend-request-count');
                const badge = document.getElementById('friend-request-tab-badge');
                const list = document.getElementById('pending-friend-request-list');
                if (counter) counter.textContent = String(count);
                if (badge) {{
                    badge.textContent = String(count);
                    badge.style.display = count ? 'inline-block' : 'none';
                }}
                if (list) {{
                    list.replaceChildren();
                    if (!requests.length) {{
                        const empty = document.createElement('p');
                        empty.textContent = 'No new friend requests right now.';
                        empty.style.cssText = 'color:var(--text-muted);font-size:13px;margin:0;';
                        list.appendChild(empty);
                    }} else {{
                        requests.forEach(request => {{
                            const row = document.createElement('div');
                            row.dataset.friendRequestId = String(request.id);
                            row.style.cssText = 'background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.25);border-radius:10px;padding:12px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;';
                            const profileUrl = new URL('/portal/feed', window.location.origin);
                            profileUrl.searchParams.set('active_tab', 'community');
                            profileUrl.searchParams.set('view_profile', request.requester_phone);
                            const name = document.createElement('a');
                            name.href = profileUrl.pathname + profileUrl.search;
                            name.textContent = request.requester_name || 'A farmer';
                            name.style.cssText = 'font-weight:600;color:#f1f5f9;text-decoration:none;';
                            const actions = document.createElement('div');
                            actions.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;';
                            const view = document.createElement('a');
                            view.href = name.href;
                            view.textContent = '👤 View Profile';
                            view.style.cssText = 'background:rgba(59,130,246,0.2);border:1px solid rgba(59,130,246,0.4);color:#93c5fd;font-size:12px;font-weight:700;padding:6px 12px;border-radius:8px;text-decoration:none;';
                            actions.append(name, view);
                            for (const [action, label, buttonClass] of [
                                ['/portal/friend/accept', 'Accept', 'btn btn-emerald'],
                                ['/portal/friend/reject', 'Reject', 'btn btn-danger']
                            ]) {{
                                const form = document.createElement('form');
                                form.action = action;
                                form.method = 'post';
                                form.style.margin = '0';
                                const input = document.createElement('input');
                                input.type = 'hidden';
                                input.name = 'requester_phone';
                                input.value = request.requester_phone;
                                const button = document.createElement('button');
                                button.type = 'submit';
                                button.className = buttonClass;
                                button.textContent = label;
                                button.style.cssText = 'padding:6px 12px;font-size:12px;';
                                form.append(input, button);
                                actions.appendChild(form);
                            }}
                            row.append(name, actions);
                            list.appendChild(row);
                        }});
                    }}
                }}
                const newRequests = requests.filter(request => !notifiedFriendRequestIds.has(String(request.id)));
                newRequests.forEach(request => {{
                    notifiedFriendRequestIds.add(String(request.id));
                    showIncomingFriendRequestNotification(request);
                }});
                try {{
                    sessionStorage.setItem('farmwatch_notified_friend_requests', JSON.stringify([...notifiedFriendRequestIds].slice(-100)));
                }} catch (error) {{
                    console.warn('Could not save friend-request notification state:', error);
                }}
            }}

            let notifiedMessageIds = new Set();
            try {{
                const storedMessageIds = JSON.parse(sessionStorage.getItem('farmwatch_notified_messages') || '[]');
                if (Array.isArray(storedMessageIds)) notifiedMessageIds = new Set(storedMessageIds.map(String));
            }} catch (error) {{
                console.warn('Could not restore message notification state:', error);
            }}

            async function pollMessageNotifications() {{
                const badge = document.getElementById('unread-message-badge');
                if (!badge) return;
                try {{
                    const response = await fetch('/portal/messages/notifications', {{
                        credentials: 'same-origin',
                        cache: 'no-store'
                    }});
                    if (!response.ok) return;
                    const data = await response.json();
                    updateFriendRequestPanel(data);
                    const count = Number(data.unread_count) || 0;
                    badge.textContent = count;
                    badge.style.display = count ? 'inline-block' : 'none';
                    const newMessages = (data.messages || []).filter(message => !notifiedMessageIds.has(String(message.id)));
                    for (const message of newMessages) notifiedMessageIds.add(String(message.id));
                    try {{
                        sessionStorage.setItem('farmwatch_notified_messages', JSON.stringify([...notifiedMessageIds].slice(-100)));
                    }} catch (error) {{
                        console.warn('Could not save message notification state:', error);
                    }}
                    if (newMessages.length) {{
                        showIncomingMessageNotification(newMessages[0], count);
                    }}
                }} catch (error) {{
                    console.error('Could not check for new messages:', error);
                }}
            }}
            pollMessageNotifications();
            setInterval(pollMessageNotifications, 15000);

            async function refreshShoutoutList(response, action) {{
                if (!response.redirected) throw new Error('The shout-out action did not return an updated page.');
                const page = new DOMParser().parseFromString(await response.text(), 'text/html');
                const incomingList = page.getElementById('shoutout-list');
                const currentList = document.getElementById('shoutout-list');
                if (!incomingList || !currentList) throw new Error('Could not refresh the shout-out list.');
                currentList.replaceChildren(...Array.from(incomingList.childNodes, node => document.importNode(node, true)));
                const destination = new URL(response.url, window.location.origin);
                showPortalTab('shoutouts', false);
                history.replaceState(history.state, '', destination.href);
                let targetId = destination.hash ? decodeURIComponent(destination.hash.slice(1)) : '';
                const postedId = destination.searchParams.get('shoutout_posted');
                if (postedId) targetId = 'shoutout-' + postedId;
                if (action.endsWith('/shoutout/delete')) targetId = 'shoutout-list';
                const target = document.getElementById(targetId)
                    || (targetId === 'shoutout-list' ? currentList : currentList.querySelector('.shoutout-entry'))
                    || currentList;
                target.scrollIntoView({{ block: target === currentList ? 'start' : 'center', behavior: 'smooth' }});
            }}

            // Intercept form submits so actions stay on the page (no jump to top)
            document.addEventListener('submit', async function(e) {{
                if (e.defaultPrevented) return;
                const form = e.target;
                if (!form || form.tagName !== 'FORM') return;
                const method = (form.method || 'get').toLowerCase();
                if (method !== 'post') return;
                // Keep authentication flows as full navigations; other portal actions stay on the page.
                const action = form.action || '';
                if (action.includes('/portal/auth') || action.includes('/submit-registration') || action.includes('/admin/login') || action.includes('/portal/alert/raise') || action.includes('/portal/trust-groups/')) {{
                    return; // let normal submit happen
                }}
                e.preventDefault();
                const btn = form.querySelector('button[type="submit"], input[type="submit"]');
                const originalText = btn ? btn.innerHTML : '';
                if (btn) {{ btn.disabled = true; btn.style.opacity = '0.6'; }}
                try {{
                    const fd = new FormData(form);
                    const res = await fetch(action, {{ method: 'POST', body: fd, credentials: 'same-origin' }});
                    const redirectedToLogin = res.redirected && new URL(res.url).pathname === '/portal/login';
                    if (action.includes('/portal/block-node') || action.includes('/portal/unblock-node') || action.includes('/portal/guardroom/')) {{
                        if (!res.ok || redirectedToLogin || new URL(res.url).origin !== window.location.origin) {{
                            throw new Error('Could not update the Guardroom. Please try again.');
                        }}
                        window.location.assign(res.url);
                        return;
                    }}
                    if (action.includes('/portal/shoutout')) {{
                        if (!res.ok || redirectedToLogin) {{
                            let errorMessage = 'Could not update the shout-out. Please try again.';
                            try {{
                                const payload = await res.json();
                                if (typeof payload.detail === 'string') errorMessage = payload.detail;
                            }} catch (parseError) {{
                                console.error('Could not read the shout-out response:', parseError);
                            }}
                            throw new Error(errorMessage);
                        }}
                        await refreshShoutoutList(res, action);
                        if (action.endsWith('/shoutout/delete')) showFlash('Shout-out deleted', false);
                        else if (action.endsWith('/shoutout/remove-photo')) showFlash('Celebration photo removed', false);
                        else showFlash('Shout-out posted', false);
                        if (action.endsWith('/portal/shoutout')) form.reset();
                        return;
                    }}
                    if (action.includes('/portal/market/edit')) {{
                        const result = await res.json();
                        if (!res.ok) throw new Error(result.detail || 'Could not update listing.');
                        closeProductEdit();
                        const editedCard = document.getElementById('product-card-' + result.product_id);
                        if (editedCard) editedCard.remove();
                        showFlash(result.message, false);
                        return;
                    }}
                    const succeeded = res.ok && !redirectedToLogin;
                    // Determine friendly message from the endpoint
                    let msg = 'Done';
                    if (action.includes('/portal/market/post')) msg = 'Listing submitted; awaiting admin approval';
                    else if (action.includes('/friend/request')) msg = 'Your request has been sent';
                    else if (action.includes('/friend/accept')) msg = 'Friend request accepted';
                    else if (action.includes('/friend/reject')) msg = 'Request declined';
                    else if (action.includes('/messages/send')) msg = 'Your message has been sent';
                    else if (action.includes('/status/like')) msg = 'Liked';
                    else if (action.includes('/status/comment')) msg = 'Comment posted';
                    else if (action.includes('/status/repost')) msg = 'Reposted';
                    else if (action.includes('/status/hide')) msg = 'Post hidden';
                    else if (action.includes('/status/report')) msg = 'Report submitted';
                    else if (action.includes('/market/report')) msg = 'Listing reported';
                    else if (action.includes('/market/review')) msg = 'Review submitted';
                    else if (action.includes('/market/interest')) msg = 'Your message has been sent';
                    else if (action.includes('/shoutout')) msg = 'Shout-out posted';
                    else if (action.includes('/flag-node')) msg = 'Thank you for helping keep the site safe. Your report has been sent for review.';
                    else if (action.includes('/checkin')) msg = 'Checked in';
                    else if (action.includes('/block-node')) msg = 'Blocked';
                    else if (action.includes('/unblock-node')) msg = 'Unblocked';
                    else if (action.includes('/sensors/submit')) msg = 'Soil reading saved';
                    else if (succeeded) msg = 'Success';
                    else msg = 'Something went wrong';
                    showFlash(msg, !succeeded);
                    if (succeeded && (action.includes('/friend/accept') || action.includes('/friend/reject'))) {{
                        pollMessageNotifications();
                    }}
                    // Light UI updates without reload
                    if (succeeded && action.includes('/status/like') && btn) {{
                        const m = btn.innerText.match(/\\d+/);
                        const n = m ? parseInt(m[0], 10) + 1 : 1;
                        btn.innerHTML = '👍 ' + n;
                    }}
                    if (succeeded && action.includes('/friend/request') && btn) {{
                        btn.outerHTML = '<span style="color:#fbbf24; font-size:12px; font-weight:700;">⏳ Pending</span>';
                    }}
                    if (succeeded && action.includes('/portal/market/post')) {{
                        form.reset();
                    }} else if (succeeded && (form.querySelector('input[name="body"]') || form.querySelector('input[name="content"]') || form.querySelector('input[name="text"]') || form.querySelector('input[name="message"]'))) {{
                        form.reset();
                    }}
                }} catch (err) {{
                    showFlash(err.message || 'Network error — try again', true);
                }} finally {{
                    if (btn && btn.parentNode) {{ btn.disabled = false; btn.style.opacity = '1'; if (originalText) btn.innerHTML = originalText; }}
                }}
            }});
            async function submitScore(game, score) {{
                const fd = new FormData();
                fd.append('game_name', game);
                fd.append('score', score);
                const res = await fetch('/portal/games/score', {{ method: 'POST', body: fd }});
                if (res.ok) {{
                    const data = await res.json();
                    if (data.xp_earned > 0) showXpToast(data.xp_earned, data.balance);
                }}
            }}

            // ----- Rolling Dart -----
            function playDart() {{
                const score = Math.floor(Math.random() * 100) + 1;
                document.getElementById('dart_score_display').innerText = score;
                sfxDart(score);
                const msg = document.getElementById('dart_msg');
                if (score >= 50) {{
                    msg.innerText = 'Great throw! +XP coming…';
                    msg.style.color = '#6ee7b7';
                    submitScore('dart', score);
                }} else {{
                    msg.innerText = 'Score ' + score + ' — try again for 50+';
                    msg.style.color = '#fbbf24';
                }}
            }}

            // ----- XP Hunt (find golden seeds) -----
            let huntFinds = 0, huntActive = false, huntSeeds = new Set();
            function startHunt() {{
                huntFinds = 0;
                huntActive = true;
                huntSeeds = new Set();
                while (huntSeeds.size < 3) huntSeeds.add(Math.floor(Math.random() * 9));
                const grid = document.getElementById('hunt_grid');
                grid.innerHTML = '';
                playTone(400, 0.08, 'sine', 0.1);
                for (let i = 0; i < 9; i++) {{
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.style.cssText = 'aspect-ratio:1; border:none; border-radius:12px; background:#1e293b; font-size:28px; cursor:pointer; color:#64748b;';
                    btn.innerText = '🌱';
                    btn.onclick = (function(idx, el) {{
                        return function() {{
                            if (!huntActive) return;
                            el.disabled = true;
                            if (huntSeeds.has(idx)) {{
                                el.innerText = '⭐';
                                el.style.background = 'rgba(245,158,11,0.3)';
                                huntFinds++;
                                sfxHit();
                                document.getElementById('hunt_msg').innerText = 'Found ' + huntFinds + ' of 3';
                                document.getElementById('hunt_msg').style.color = '#6ee7b7';
                                if (huntFinds >= 3) {{
                                    huntActive = false;
                                    sfxWin();
                                    document.getElementById('hunt_msg').innerText = 'All seeds found!';
                                    submitScore('hunt', 3);
                                }}
                            }} else {{
                                el.innerText = '·';
                                el.style.background = '#0f172a';
                                sfxMiss();
                            }}
                        }};
                    }})(i, btn);
                    grid.appendChild(btn);
                }}
                document.getElementById('hunt_msg').innerText = 'Tap tiles to find 3 golden seeds';
                document.getElementById('hunt_msg').style.color = '#94a3b8';
            }}

            // ----- Auto XP every 20 seconds while on the page -----
            setInterval(async () => {{
                try {{
                    if (document.hidden) return;
                    const res = await fetch('/portal/xp/tick', {{ method: 'POST' }});
                    if (res.ok) {{
                        const data = await res.json();
                        const el = document.getElementById('grid_score_display');
                        if (el && data.xp !== undefined) {{
                            el.innerText = '⚡ ' + data.xp + ' Grid XP';
                        }}
                    }}
                }} catch (e) {{
                    // Silent fail - network or auth issue
                }}
            }}, 20000);

        </script>
        <div id="photoPreview" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85); z-index:3000; align-items:center; justify-content:center;" onclick="this.style.display='none'" oncontextmenu="return false;">
            <img id="photoPreviewImg" style="max-width:90%; max-height:85%; border-radius:12px; pointer-events:none; user-select:none; -webkit-user-drag:none;" draggable="false">
            <div style="position:absolute; top:16px; right:20px; color:#fff; font-size:28px; cursor:pointer;">✕</div>
        </div>
        <script>
        function openProductEdit(button) {{
            const form = document.getElementById('productEditForm');
            form.elements.namedItem('product_id').value = button.dataset.productId;
            form.elements.namedItem('title').value = button.dataset.title || '';
            form.elements.namedItem('category').value = button.dataset.category || 'General';
            form.elements.namedItem('price').value = button.dataset.price || '';
            form.elements.namedItem('description').value = button.dataset.description || '';
            form.elements.namedItem('contact_phone').value = button.dataset.contact || '';
            form.elements.namedItem('photos').value = '';
            form.elements.namedItem('remove_photos').checked = false;
            document.getElementById('productEditModal').style.display = 'block';
            form.elements.namedItem('title').focus();
        }}
        function closeProductEdit() {{
            document.getElementById('productEditModal').style.display = 'none';
        }}
        function toggleLivestock() {{
            var cat = document.getElementById('prod_category');
            var box = document.getElementById('livestock_fields');
            if (cat && box) box.style.display = (cat.value === 'Livestock') ? 'block' : 'none';
        }}
        function toggleAnimal() {{
            var a = document.getElementById('animal_type');
            var v = a ? a.value : '';
            var sex = document.getElementById('sex_fields');
            var cow = document.getElementById('cow_fields');
            var exo = document.getElementById('exotic_fields');
            if (sex) sex.style.display = v ? 'block' : 'none';
            if (cow) cow.style.display = (v === 'Cow') ? 'block' : 'none';
            if (exo) exo.style.display = (v === 'Exotic Pets') ? 'block' : 'none';
        }}
        function toggleBreed() {{
            var b = document.getElementById('cow_breed');
            var wrap = document.getElementById('breed_custom_wrap');
            if (b && wrap) wrap.style.display = (b.value === 'Other') ? 'block' : 'none';
        }}
        function previewProtected(src) {{
            var box = document.getElementById('photoPreview');
            document.getElementById('photoPreviewImg').src = src;
            box.style.display = 'flex';
        }}
        document.addEventListener('contextmenu', function(e) {{
            if (e.target.closest('#photoPreview') || e.target.closest('[oncontextmenu]')) e.preventDefault();
        }});
        </script>
        <div style="position:fixed; bottom:0; left:0; right:0; background:rgba(15,23,42,0.95); border-top:1px solid rgba(52,211,153,0.3); padding:8px 0; z-index:1000; overflow:hidden;">
            <div style="display:flex; align-items:center; gap:12px; padding:0 12px;">
                <form action="/portal/checkin" method="post" style="margin:0; flex-shrink:0;">
                    <button type="submit" style="background:rgba(16,185,129,0.2); border:1px solid rgba(16,185,129,0.4); color:#6ee7b7; padding:6px 12px; border-radius:8px; font-size:12px; font-weight:700; cursor:pointer; {checked_in_btn}">{checked_in_label}</button>
                </form>
                <div style="flex:1; overflow:hidden; white-space:nowrap;">
                    <div style="display:inline-block; animation:ticker 40s linear infinite; color:#cbd5e1; font-size:14px;">
                        {ticker_html} &nbsp;&nbsp;&nbsp; {ticker_html}
                    </div>
                </div>
            </div>
        </div>
        <style>
            @keyframes ticker {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}
            body {{ padding-bottom: 70px !important; }}
        </style>
    </body></html>"""


@app.post("/portal/alert/comment")
async def farmer_post_comment(alert_id: int = Form(...), comment_text: str = Form(...),
                              current_user=Depends(get_current_farmer)):
    if not current_user: raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("INSERT INTO alert_comments (alert_id, author, text) VALUES (?, ?, ?)",
                           (alert_id, current_user['name'], sanitize(comment_text)))
        await conn.commit()
    return RedirectResponse(url="/portal/feed", status_code=303)


@app.post("/portal/alert/raise")
async def farmer_raise_alert(alert_type: str = Form(...), message: str = Form(...),
                             attest_real: Optional[str] = Form(None),
                             video_evidence: Optional[UploadFile] = File(None),
                             current_user=Depends(get_current_farmer)):
    if not current_user: raise HTTPException(status_code=401, detail="Unauthorized")
    if not attest_real:
        raise HTTPException(status_code=400, detail="You must attest that this alert is real and not fake.")
    v_name = None

    if video_evidence and video_evidence.filename:
        content_bytes = await video_evidence.read(MAX_UPLOAD_SIZE + 1)
        if len(content_bytes) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=413, detail="Video file too large. Maximum size is 15 MB.")

        file_head = content_bytes[:12]
        if len(file_head) >= 12 and file_head[4:8] == b"ftyp":
            extension = ".mov" if file_head[8:12] == b"qt  " else ".mp4"
        elif file_head[:4] == bytes.fromhex("1A45DFA3"):
            extension = ".webm"
        elif file_head[:4] == b"RIFF" and file_head[8:12] == b"AVI ":
            extension = ".avi"
        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported video format. Upload an MP4, MOV, WebM, or AVI video.",
            )

        v_name = f"{hashlib.md5(os.urandom(16)).hexdigest()}{extension}"
        with open(os.path.join(MEDIA_DIR, v_name), "wb") as f:
            f.write(content_bytes)

    a_type, msg = sanitize(alert_type), sanitize(message)
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "INSERT INTO alerts_log (type, sender, lga, message, status, video_path) VALUES (?, ?, ?, ?, 'Active', ?)",
            (a_type, current_user['name'], current_user['lga'], msg, v_name))
        await conn.commit()

    override = a_type in ["Critical Disaster", "Armed Attack"]
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        q = "SELECT phone FROM farmers WHERE status = 'Approved' AND phone != ? AND COALESCE(is_demo, 0) = 0" if override else "SELECT phone FROM farmers WHERE status = 'Approved' AND lga = ? AND phone != ? AND COALESCE(is_demo, 0) = 0"
        p = (current_user['phone'],) if override else (current_user['lga'], current_user['phone'])
        async with conn.execute(q, p) as cursor: targets = [r["phone"] for r in await cursor.fetchall()]

    alert_text = f"🚨 ALERT [{a_type.upper()}] from Sector [{current_user['lga']}]: {msg}"
    for phone in targets:
        asyncio.create_task(async_dispatch_whatsapp(phone, alert_text))
    return Response(status_code=200)


@app.post("/portal/alert/relay")
async def farmer_relay_alert(alert_id: int = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user: raise HTTPException(status_code=401, detail="Session validation failed")
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT type, sender, message, lga FROM alerts_log WHERE id = ?",
                                (alert_id,)) as cursor: alert = await cursor.fetchone()
    new_xp = current_user['xp']
    if alert:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute("UPDATE farmers SET xp = xp + 15 WHERE phone = ?", (current_user['phone'],))
            async with conn.execute("SELECT xp FROM farmers WHERE phone = ?", (current_user['phone'],)) as res_cursor:
                res_row = await res_cursor.fetchone()
                if res_row:
                    new_xp = res_row[0] if isinstance(res_row, (tuple, list)) else res_row["xp"]
            await conn.commit()
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT phone FROM farmers WHERE status = 'Approved' AND lga = ? AND phone != ? AND COALESCE(is_demo, 0) = 0",
                                    (alert['lga'], current_user['phone'])) as cursor: targets = [r["phone"] for r in
                                                                                                 await cursor.fetchall()]
        relay_text = f"📡 [GRID RELAY] Forwarded by {current_user['name']} | ORIGINAL ALERT [{alert['type'].upper()}] from {alert['sender']}: {alert['message']}"
        for phone in targets: asyncio.create_task(async_dispatch_whatsapp(phone, relay_text))
    return Response(content=str(new_xp), status_code=200)


@app.post("/incoming-alert")
async def handle_incoming_alert(From: Optional[str] = Form(None), Body: Optional[str] = Form(None)):
    if not From or not Body:
        return Response(content="<Response></Response>", media_type="application/xml")
    sender_number = clean_phone(From.replace("whatsapp:", ""))
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM farmers WHERE phone = ? AND status = 'Approved' AND COALESCE(is_demo, 0) = 0",
                                (sender_number,)) as cursor: farmer = await cursor.fetchone()
    if not farmer: return Response(content="<Response></Response>", media_type="application/xml")
    alert_type, msg_lower = "General Anomaly", Body.lower()
    if "fire" in msg_lower or "flood" in msg_lower:
        alert_type = "Critical Disaster"
    elif "thief" in msg_lower or "intruder" in msg_lower:
        alert_type = "Intruder Spotted"
    elif "attack" in msg_lower or "armed" in msg_lower:
        alert_type = "Armed Attack"
    elif "police" in msg_lower or "brutality" in msg_lower:
        alert_type = "Police Brutality"
    elif "kidnap" in msg_lower:
        alert_type = "Kidnapping"
    elif "assault" in msg_lower or "beat" in msg_lower:
        alert_type = "Assault"
    elif "child" in msg_lower and ("abuse" in msg_lower or "molest" in msg_lower):
        alert_type = "Child Abuse"
    elif "rape" in msg_lower or "sexual" in msg_lower:
        alert_type = "Rape"
    elif "land" in msg_lower and ("grab" in msg_lower or "seize" in msg_lower):
        alert_type = "Land Grabbing"
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "INSERT INTO alerts_log (type, sender, lga, message, status, video_path) VALUES (?, ?, ?, ?, 'Active', NULL)",
            (alert_type, farmer['name'], farmer['lga'], sanitize(Body)))
        await conn.commit()
    return Response(content="<Response></Response>", media_type="application/xml")


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(next_page: str = "/dashboard", error: str = ""):
    if not next_page.startswith("/") or next_page.startswith("//"):
        next_page = "/dashboard"
    error_html = (
        '<p style="color:#fecaca; background:rgba(239,68,68,.15); padding:12px; '
        'border-radius:10px;">Admin login failed. Check your credentials and try again.</p>'
        if error else ""
    )
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>{UPGRADED_CSS}</style></head>
        <body><div class="glass-panel" style="max-width:440px; margin:60px auto;">
            <h2 style="margin-top:0;">🔐 Admin sign-in</h2>
            <p style="color:#cbd5e1;">Enter the administrator credentials to open the dashboard.</p>
            {error_html}
            <form action="/admin/login" method="post">
                <input type="hidden" name="next_page" value="{html.escape(next_page, quote=True)}">
                <label>Admin username</label>
                <input type="text" name="username" required autocomplete="username">
                <label>Admin password</label>
                <input type="password" name="password" required autocomplete="current-password">
                <button type="submit" class="btn btn-emerald" style="width:100%; margin-top:18px;">Sign in to Admin</button>
            </form>
            <p style="margin-top:18px;"><a href="/" style="color:#93c5fd;">Back to home</a></p>
        </div></body></html>"""


@app.post("/admin/login")
async def admin_login(
    username: str = Form(...),
    password: str = Form(...),
    next_page: str = Form("/dashboard"),
):
    if not next_page.startswith("/") or next_page.startswith("//"):
        next_page = "/dashboard"
    input_hash = hashlib.sha256(password.encode()).hexdigest()
    valid_password = bool(
        ADMIN_SECRET_HASH
        and hmac.compare_digest(username, ADMIN_USERNAME)
        and hmac.compare_digest(input_hash, ADMIN_SECRET_HASH)
    )
    if valid_password:
        resp = RedirectResponse(next_page, status_code=303)
        resp.set_cookie(
            "admin_session",
            sign_admin_session(ADMIN_USERNAME),
            httponly=True,
            secure=os.getenv("COOKIE_SECURE", "0") == "1",
            samesite="lax",
            max_age=ADMIN_SESSION_TTL_SECONDS,
        )
        return resp
    return RedirectResponse(url="/admin/login?error=1", status_code=303)

@app.get("/admin/logout")
def admin_logout():
    r = RedirectResponse("/", status_code=303)
    r.delete_cookie("admin_session")
    return r

@app.get("/", response_class=HTMLResponse)
def community_homepage(admin_error: Optional[str] = None):
    clean_logo_svg = """
    <svg width="90" height="90" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 16px rgba(16,185,129,0.35)); margin-bottom: 10px;">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        <path d="M12 8a3 3 0 0 0-3 3c0 3 3 7 3 7s3-4 3-7a3 3 0 0 0-3-3z"/>
        <circle cx="12" cy="11" r="1" fill="#10b981"/>
    </svg>
    """
    error_html = ""
    if admin_error:
        error_html = '''
        <div style="background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.3); color:#f87171; padding:12px; border-radius:10px; margin-bottom:16px; font-size:14px;">
            Enter correct login or email admin.
        </div>
        '''
    return f"""<html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            {UPGRADED_CSS}
            .welcome-title {{ margin: 5px 0 8px 0; font-size: 32px; font-weight: 900; letter-spacing: -0.02em; color: #fff; }}
            .subtitle {{ color: #cbd5e1; line-height: 1.65; font-size: 17px; margin: 0 auto 32px auto; max-width: 420px; }}
            .action-link {{ padding: 20px; font-size: 18px; font-weight: 800; color: #ffffff; border-radius: 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }}
            details summary {{ cursor: pointer; list-style: none; }}
            details summary::-webkit-details-marker {{ display: none; }}
            .admin-toggle {{
                width: 100%;
                box-sizing: border-box;
                text-align: center;
                margin-top: 14px;
            }}
        </style>
    </head>
    <body>
        <div class="glass-panel" style="max-width: 520px; margin: 40px auto; text-align: center;">
            <div>
                {clean_logo_svg}
                <h1 class="welcome-title">olode.com.ng</h1>
                <span class="badge badge-emerald" style="font-size: 12px; font-weight: 800; letter-spacing: 0.04em; padding: 6px 14px;">🌾 Farm Watch Network</span>
            </div>
            <hr style="border: 0; border-top: 1px solid var(--border-glass); margin: 24px 0;">
            <p class="subtitle">
                Join your neighbours to watch over the community.<br>
                Share warnings quickly and help protect our farms.
            </p>
            <div style="display: grid; gap: 14px;">
                <a href="/register" class="btn btn-emerald action-link">Register My Farm</a>
                <a href="/portal/login" class="btn action-link" style="background: rgba(59,130,246,0.15); border: 2px solid rgba(59,130,246,0.4); color: #93c5fd;">
                    I Already Have an Account — Sign In
                </a>
                <details id="admin-login" class="admin-toggle" style="margin-top:0;">
                    <summary class="btn action-link" style="background:rgba(245,158,11,0.12); color:#fbbf24; border:2px solid rgba(245,158,11,0.4); width:100%; box-sizing:border-box;">
                        Admin Command Center Login
                    </summary>
                    <div style="margin-top:16px; padding:16px; background:rgba(0,0,0,0.2); border-radius:12px; text-align:left;">
                        {error_html}
                        <form action="/admin/login" method="post">
                            <label style="color:var(--text-muted); font-size:13px;">Admin Username</label>
                            <input type="text" name="username" required style="width:100%; padding:12px; margin:6px 0 12px; background:#090d16; border:1px solid var(--border-glass); color:#fff; border-radius:10px; box-sizing:border-box;">
                            <label style="color:var(--text-muted); font-size:13px;">Admin Password</label>
                            <input type="password" name="password" required style="width:100%; padding:12px; margin:6px 0 16px; background:#090d16; border:1px solid var(--border-glass); color:#fff; border-radius:10px; box-sizing:border-box;">
                            <button type="submit" class="btn btn-emerald" style="width:100%;">Enter Command Center</button>
                        </form>
                        <p style="font-size:11px; color:#64748b; margin-top:10px; text-align:center;">For authorized administrators only.</p>
                    </div>
                </details>
            </div>
        </div>
        <script>
            if (window.location.hash === "#admin-login") {{
                const adminLogin = document.getElementById("admin-login");
                if (adminLogin) {{
                    adminLogin.open = true;
                    adminLogin.scrollIntoView();
                }}
            }}
        </script>
    </body>
    </html>"""
