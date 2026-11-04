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
import html
import httpx
import asyncio
import aiosqlite
from typing import Optional, Dict, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, Form, Response, Depends, HTTPException, status, Cookie, File, UploadFile, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "chief")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "securepassword123")
ADMIN_SECRET_HASH = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
COOKIE_SIGNING_KEY = os.getenv("COOKIE_SECRET_KEY", "grid-security-core-token-991").encode()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "AC436cb01fff8036da72eda4b89ef1366d")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "9beab2f0af9f6e78b079e27348073269")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "whatsapp:+14155238886")

DB_FILE = "farm_watch.db"
MEDIA_DIR = "static_media"

os.makedirs(MEDIA_DIR, exist_ok=True)

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
MAX_MESSAGES_PER_HOUR_TO_PEER = 8
MAX_MESSAGES_PER_DAY = 25
REPORTS_TO_AUTO_FLAG = 2

# Engagement / games
CHECKIN_XP = 5
SHOUTOUT_XP = 3
DART_WIN_XP = 15
HUNT_WIN_XP = 10
PRODUCT_POST_XP = 8
MAX_SHOUTOUT_LEN = 120
MAX_PRODUCT_TITLE = 80
MAX_PRODUCT_DESC = 300
PRODUCT_CATEGORIES = ("Crops", "Livestock", "Tools", "Seeds", "Produce", "Other")

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
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS farmers (
                phone TEXT PRIMARY KEY, name TEXT, country TEXT, state TEXT, 
                city TEXT, lga TEXT, area TEXT, token TEXT, status TEXT, xp INTEGER DEFAULT 100
            );
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
                body TEXT
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blocker_phone TEXT NOT NULL,
                blocked_phone TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(blocker_phone, blocked_phone)
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
        try:
            await conn.execute("ALTER TABLE alerts_log ADD COLUMN video_path TEXT;")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE farm_products ADD COLUMN photo_path TEXT;")
        except Exception:
            pass
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS spotify_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                farmer_phone TEXT NOT NULL,
                title TEXT NOT NULL,
                embed_path TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.commit()
    yield


app = FastAPI(title="Farm Watch Enterprise Node", version="5.2.1", lifespan=lifespan)
security = HTTPBasic()
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


def clean_phone(phone: str) -> str:
    """Strip all non-digit characters from a phone number."""
    return "".join(c for c in phone if c.isdigit())


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


def sign_cookie_value(value: str) -> str:
    signature = hmac.new(COOKIE_SIGNING_KEY, value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{signature}"


def verify_cookie_value(signed_value: Optional[str]) -> Optional[str]:
    if not signed_value or "." not in signed_value:
        return None
    value, signature = signed_value.rsplit(".", 1)
    expected = hmac.new(COOKIE_SIGNING_KEY, value.encode(), hashlib.sha256).hexdigest()
    return value if hmac.compare_digest(signature, expected) else None


def mask_phone_number(phone: str) -> str:
    clean = clean_phone(phone)
    if len(clean) <= 6: return "••••" + clean[-2:] if len(clean) > 2 else "••••"
    return f"{clean[:4]}••••{clean[-3:]}"


async def async_dispatch_whatsapp(to_number: str, message_text: str):
    async with DISPATCH_SEMAPHORE:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
        clean_target = f"whatsapp:+{clean_phone(to_number)}" if not to_number.startswith(
            "+") else f"whatsapp:{to_number}"
        payload = {"To": clean_target, "From": TWILIO_PHONE_NUMBER, "Body": message_text}
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                res = await client.post(url, data=payload, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
                print(f"📡 Background Dispatch Status: {res.status_code}")
            except Exception as e:
                print(f"❌ Non-blocking network alert exception: {e}")


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


def authenticate_admin(credentials: HTTPBasicCredentials = Depends(security)):
    input_hash = hashlib.sha256(credentials.password.encode()).hexdigest()
    if not (hmac.compare_digest(credentials.username, ADMIN_USERNAME) and hmac.compare_digest(input_hash,
                                                                                              ADMIN_SECRET_HASH)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Node Credentials",
                            headers={"WWW-Authenticate": "Basic"})
    return credentials.username


async def get_current_farmer(farmer_session: Optional[str] = Cookie(None)):
    verified_phone = verify_cookie_value(farmer_session)
    if not verified_phone: return None
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM farmers WHERE phone = ?", (verified_phone,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


@app.post("/portal/auth")
async def farmer_authentication(phone: str = Form(...)):
    target = normalize_nigerian_mobile(phone)
    if not target:
        return RedirectResponse(
            url="/portal/login?error=Invalid phone number. Use a valid Nigerian mobile (070/080/081/090/091).",
            status_code=303
        )
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM farmers WHERE phone = ?", (target,)) as cursor:
            farmer = await cursor.fetchone()
    if farmer:
        if farmer["status"] == "Pending":
            return RedirectResponse(url="/portal/login?error=Access Restricted. Awaiting verification clearance.",
                                    status_code=303)
        if farmer["status"] == STATUS_REPORTED:
            return RedirectResponse(
                url="/portal/login?error=Access Restricted. Your node has been reported and is under review.",
                status_code=303
            )
        res = RedirectResponse(url="/portal/feed", status_code=303)
        signed_token = sign_cookie_value(target)
        res.set_cookie(key="farmer_session", value=signed_token, max_age=31536000, httponly=True, secure=False)
        return res
    return RedirectResponse(url="/portal/login?error=Phone number not recognized on network scale.", status_code=303)


@app.post("/submit-registration")
async def handle_registration(name: str = Form(...), phone: str = Form(...), city_manual: str = Form(...)):
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

    lookup = city_manual.strip().lower()
    geo = CITY_AUTOFILL_MAP.get(lookup,
                                {"country": "Nigeria", "state": "Region", "lga": city_manual, "area": "General Hub"})
    unique_token = hashlib.sha256(os.urandom(24)).hexdigest()[:16]
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("""
            INSERT OR REPLACE INTO farmers (phone, name, country, state, city, lga, area, token, status, xp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', 100)
        """, (clean_p, sanitize(name), geo["country"], geo["state"], sanitize(city_manual), geo["lga"], geo["area"],
              unique_token))
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
    body::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        z-index: 0;
        opacity: 0.4;
        background-image:
            radial-gradient(circle at 20% 80%, rgba(134, 239, 172, 0.08) 0%, transparent 25%),
            radial-gradient(circle at 80% 40%, rgba(45, 212, 191, 0.07) 0%, transparent 30%);
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
    input[type="text"], select {
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
    input[type="text"]::placeholder, select::placeholder {
        color: #7d9b8c;
        font-size: 16px;
        font-weight: 400;
        opacity: 1;
    }
    input[type="text"]:focus, select:focus {
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
    mock_farmers = [
        ("2348031112221", "Bello Kano", "Kano Municipal", "Kano City Center", 245),
        ("2348031112225", "Adewale Osogbo", "Osogbo", "Ataoja Sector", 410),
        ("2348031112226", "Arowolo Ife", "Ile-Ife", "Ife Central Town", 295)
    ]
    async with aiosqlite.connect(DB_FILE) as conn:
        for phone, name, lga, area, xp in mock_farmers:
            await conn.execute("""
                INSERT OR REPLACE INTO farmers (phone, name, country, state, city, lga, area, token, status, xp)
                VALUES (?, ?, 'Nigeria', 'Region', 'City', ?, ?, 'mock_token', 'Approved', ?)
            """, (phone, name, lga, area, xp))
        await conn.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/admin/flush-grid")
async def admin_flush_grid_data(username: str = Depends(authenticate_admin)):
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("DELETE FROM farmers;")
        await conn.execute("DELETE FROM alerts_log;")
        await conn.execute("DELETE FROM alert_comments;")
        await conn.execute("DELETE FROM direct_messages;")
        await conn.execute("DELETE FROM blocked_nodes;")
        await conn.execute("DELETE FROM message_reports;")
        await conn.execute("DELETE FROM sensor_readings;")
        await conn.execute("DELETE FROM checkins;")
        await conn.execute("DELETE FROM shoutouts;")
        await conn.execute("DELETE FROM game_scores;")
        await conn.execute("DELETE FROM farm_products;")
        await conn.execute("DELETE FROM spotify_links;")
        await conn.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(username: str = Depends(authenticate_admin)):
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

    total_nodes = len(all_farmers)
    pending_clearance = sum(1 for f in all_farmers if f["status"] in RESTRICTED_STATUSES)
    active_threats = len(active_alerts)
    pulse_class = "pulse" if pending_clearance > 0 else ""

    # Safe data preparation for JavaScript extraction
    map_nodes_js = ",".join([f"{{name:'{f['name']}', lga:'{f['lga']}', status:'{f['status']}'}}" for f in all_farmers if
                             f['status'] == 'Approved'])
    map_threats_js = ",".join([f"{{type:'{a['type']}', lga:'{a['lga']}'}}" for a in active_alerts])

    pending_html = ""
    for f in all_farmers:
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
    for f in all_farmers:
        if f['status'] == 'Approved':
            if rank <= 5:
                leaderboard_html += f"<tr><td>🏅 <b>#{rank}</b></td><td>{f['name']}</td><td><span class='badge badge-blue'>{f['lga']}</span></td><td style='color:var(--accent-amber); font-weight:bold;'>{f['xp']} XP</td></tr>"
                rank += 1
            active_nodes_html += f"""
            <tr>
                <td style="font-weight: 600; color: #fff;">{f['name']}</td>
                <td style="font-family: monospace; color: var(--text-muted);">{mask_phone_number(f['phone'])}</td>
                <td>{f['state']} &rarr; {f['lga']}</td>
                <td><span class="badge badge-emerald">Operational</span></td>
                <td><form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{f['phone']}"><button type="submit" class="btn btn-danger" style="padding: 6px 12px; font-size: 12px; border-radius: 8px;">Remove Node</button></form></td>
            </tr>"""

    pending_table = f'<div style="overflow-x: auto;"><table class="data-table"><thead><tr><th>Node Name</th><th>Phone</th><th>Sector / Status</th><th>Actions</th></tr></thead><tbody>{pending_html}</tbody></table></div>' if pending_clearance > 0 else '<p style="color: var(--text-muted); font-style: italic; margin: 0; font-size: 14px;">No new registrations or reported nodes awaiting clearance.</p>'
    active_table = f'<div style="overflow-x: auto;"><table class="data-table"><thead><tr><th>Node Name</th><th>Phone Address</th><th>Geographic Network Path</th><th>Status</th><th>Management</th></tr></thead><tbody>{active_nodes_html}</tbody></table></div>' if active_nodes_html else '<p style="color: var(--text-muted); font-style: italic; text-align: center;">No active nodes operating on current security grid.</p>'

    reports_rows = ""
    for r in recent_reports:
        reports_rows += f"""
        <tr>
            <td style="font-size:12px; color:var(--text-muted);">{r['timestamp']}</td>
            <td style="font-family:monospace; font-size:12px;">{mask_phone_number(r['reporter_phone'])}</td>
            <td style="font-family:monospace; font-size:12px;">{mask_phone_number(r['sender_phone'])}</td>
            <td style="font-size:13px; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{html.escape(r['body'][:80])}</td>
        </tr>"""
    reports_table = f"""
    <div style="overflow-x:auto;">
        <table class="data-table">
            <thead><tr><th>When</th><th>Reporter</th><th>Sender</th><th>Message Preview</th></tr></thead>
            <tbody>{reports_rows or "<tr><td colspan='4' style='color:var(--text-muted); font-style:italic;'>No message reports yet.</td></tr>"}</tbody>
        </table>
    </div>"""

    html_template_head = f"""
    <html>
    <head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{UPGRADED_CSS} .map-container {{ background: #040814; border: 1px solid var(--border-glass); border-radius: 20px; padding: 20px; margin-bottom: 30px; position: relative; overflow: hidden; }} .grid-bg {{ stroke: rgba(59, 130, 246, 0.05); stroke-width: 1; fill: none; }} .map-dot {{ transition: all 0.5s ease; cursor: pointer; }} .map-pulse {{ animation: map-pulse-ring 1.5s infinite ease-out; transform-origin: center; }} @keyframes map-pulse-ring {{ 0% {{ r: 6; opacity: 1; }} 100% {{ r: 25; opacity: 0; }} }}</style></head>
    <body>
        <div class="container">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-glass); padding-bottom: 24px; flex-wrap: wrap; gap: 15px;">
                <div><h1>📡 Global Command Control</h1><p style="margin: 4px 0 0 0; color: var(--text-muted); font-size: 14px;">Farm Watch Security Operations Matrix</p></div>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <a href="/" class="btn" style="background: rgba(255,255,255,0.08); color: #e2e8f0; border: 1px solid var(--border-glass); padding: 10px 18px; font-size: 13px;">🏠 Exit to Home</a>
                    <form action="/admin/simulate-grid" method="post" style="margin:0;"><button type="submit" class="btn btn-emerald">⚙️ Inject Mock Data</button></form>
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
                <svg id="vector_map" width="100%" height="320" style="background:#030712; border-radius:12px; border:1px solid rgba(255,255,255,0.02)"><defs><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 40 0 L 0 0 0 40" class="grid-bg"/></pattern></defs><rect width="100%" height="100%" fill="url(#grid)" /><g id="map_hardware_layer"></g></svg>
            </div>
            <div class="glass-panel" style="margin-bottom: 30px; padding: 30px;"><h3>🏆 Node Reliability Leaderboard</h3><table class="data-table"><thead><tr><th>Rank</th><th>Farmer Deployed Node Name</th><th>Grid Sector Focus</th><th>Network Rating</th></tr></thead><tbody>{leaderboard_html or "<tr><td colspan='4' style='color:var(--text-muted); font-style:italic;'>No XP metrics available.</td></tr>"}</tbody></table></div>
            <div class="glass-panel" style="margin-bottom: 30px; padding: 30px;"><h3><span style="color: #ef4444;" class="pulse">&bull;</span> Real-Time Emergency Vector Feed</h3><div id="live_threat_feed_target"><p style="color: var(--text-muted); font-style: italic; margin: 0; font-size: 14px;">Connecting link matrix...</p></div></div>
            <div class="glass-panel" style="margin-bottom: 30px; padding: 30px;"><h3>⏳ Executive Node Approvals Pending</h3>{pending_table}</div>
            <div class="glass-panel" style="margin-bottom: 30px; padding: 30px;"><h3>🚩 Recent Message Reports</h3>{reports_table}</div>
            <div class="glass-panel" style="padding: 30px;"><h3>🗂️ Active Grid Infrastructure Map</h3>{active_table}</div>
        </div>
    """
    # Pure raw string for the script layout ensures Python doesn't look at javascript literals like ${p.x}
    html_template_script = """
        <script>
            const container = document.getElementById('live_threat_feed_target');
            const geographicSectorCoordinates = {"OSOGBO": {x: 150, y: 220}, "ILE-IFE": {x: 280, y: 240}, "IBADAN": {x: 110, y: 140}, "OGBOMOSO": {x: 180, y: 80}, "KANO MUNICIPAL": {x: 620, y: 70}, "FAGGE": {x: 740, y: 90}, "IKEJA": {x: 450, y: 260}, "LEKKI": {x: 520, y: 280}};
            function renderTacticalVectorMap() { 
                const layer = document.getElementById('map_hardware_layer'); 
                if(!layer) return; 
                layer.innerHTML = ""; 
                const deploymentNodes = [REPLACE_NODES_DATA], operationalThreats = [REPLACE_THREATS_DATA]; 
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
            async function pullLiveThreatStream() { try { const e = await fetch('/admin/threats/stream'); if (200 === e.status && container) { const t = await e.text(); if (container.innerHTML !== t) { container.innerHTML = t; renderTacticalVectorMap(); } } } catch (err) { console.error(err); } }
            setInterval(pullLiveThreatStream, 2000); window.onload = () => { pullLiveThreatStream(); renderTacticalVectorMap(); };
        </script>
    </body></html>
    """.replace("REPLACE_NODES_DATA", map_nodes_js).replace("REPLACE_THREATS_DATA", map_threats_js)

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

                <br>
                <button type='submit' class='btn btn-emerald' style='width:100%; font-size:18px; padding:18px; margin-top:8px;'>
                    Register My Farm
                </button>
            </form>

            <p style="text-align:center; margin-top:28px; font-size:15px; color:#94a3b8;">
                Already registered?
                <a href="/portal/login" style="color:#6ee7b7; font-weight:700; text-decoration:none;"> Sign in here</a>
            </p>
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
def farmer_login_page(error: str = None):
    err_msg = f"<p style='color:#fecaca; background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.3); padding:12px 14px; border-radius:10px; font-size:15px; line-height:1.4; margin-bottom:16px;'>{error}</p>" if error else ""
    return f"""<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>{UPGRADED_CSS}</style></head>
    <body><div class='glass-panel' style='max-width:420px; margin:60px auto;'>
        <h2 style="font-size:26px; margin-bottom:8px;">Member Sign In</h2>
        <p style="color:#94a3b8; font-size:15px; margin-bottom:20px;">Enter your registered phone number</p>
        {err_msg}
        <form action='/portal/auth' method='post'>
            <label>Phone Number</label>
            <input type='text' name='phone' placeholder='e.g. 0803 123 4567' required inputmode='numeric'>
            <p style='font-size:14px; color:#cbd5e1; margin:8px 0 18px 0; line-height:1.4;'>
                Nigerian mobile only — <b style="color:#f8fafc;">070, 080, 081, 090, 091</b>
            </p>
            <button type='submit' class='btn btn-emerald' style='width:100%; font-size:17px; padding:16px;'>Sign In</button>
        </form>
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
    return RedirectResponse(url="/portal/feed?active_tab=incidents", status_code=303)


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
async def post_shoutout(message: str = Form(...), current_user=Depends(get_current_farmer)):
    """Post a short greeting to the LGA wall."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    msg = sanitize(message)[:MAX_SHOUTOUT_LEN]
    if not msg:
        return RedirectResponse(url="/portal/feed?active_tab=community", status_code=303)
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "INSERT INTO shoutouts (farmer_phone, farmer_name, lga, message) VALUES (?, ?, ?, ?)",
            (current_user["phone"], current_user["name"], current_user["lga"], msg)
        )
        await conn.execute(
            "UPDATE farmers SET xp = xp + ? WHERE phone = ?",
            (SHOUTOUT_XP, current_user["phone"])
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=community", status_code=303)


@app.post("/portal/market/post")
async def post_farm_product(
    title: str = Form(...),
    description: str = Form(""),
    price: str = Form(""),
    category: str = Form("General"),
    contact_phone: str = Form(""),
    photo: Optional[UploadFile] = File(None),
    current_user=Depends(get_current_farmer)
):
    """Post a farm product listing (optional photo)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    title_c = sanitize(title)[:MAX_PRODUCT_TITLE]
    if not title_c:
        return RedirectResponse(url="/portal/feed?active_tab=market", status_code=303)
    desc_c = sanitize(description)[:MAX_PRODUCT_DESC]
    price_c = sanitize(price)[:40]
    cat = sanitize(category)[:30] if category else "General"
    contact = normalize_nigerian_mobile(contact_phone) or current_user["phone"]

    photo_path = None
    if photo and photo.filename:
        head = await photo.read(12)
        await photo.seek(0)
        # Allow JPEG / PNG / WebP
        is_image = (
            head.startswith(b"\xff\xd8\xff")
            or head.startswith(b"\x89PNG")
            or head.startswith(b"RIFF")
        )
        if is_image and (photo.size is None or photo.size < 5_000_000):
            ext = "jpg"
            if head.startswith(b"\x89PNG"):
                ext = "png"
            elif head.startswith(b"RIFF"):
                ext = "webp"
            fname = f"prod_{hashlib.md5(os.urandom(16)).hexdigest()}.{ext}"
            dest = os.path.join(MEDIA_DIR, fname)
            with open(dest, "wb") as f:
                f.write(await photo.read())
            photo_path = fname

    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            """INSERT INTO farm_products
               (farmer_phone, farmer_name, lga, title, description, price, contact_phone, category, photo_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (current_user["phone"], current_user["name"], current_user["lga"],
             title_c, desc_c, price_c, contact, cat, photo_path)
        )
        await conn.execute(
            "UPDATE farmers SET xp = xp + ? WHERE phone = ?",
            (PRODUCT_POST_XP, current_user["phone"])
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed?active_tab=market", status_code=303)


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
    return RedirectResponse(url=f"/portal/feed?active_tab=community&game_xp={xp}", status_code=303)


@app.post("/portal/flag-node")
async def handle_flag_node(target_phone: str = Form(...), current_user=Depends(get_current_farmer)):
    """Flag a peer node for administrative review."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized session")
    clean_t = clean_phone(target_phone)
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "UPDATE farmers SET status = ? WHERE phone = ?",
            (STATUS_REPORTED, clean_t)
        )
        await conn.commit()
    return RedirectResponse(url="/portal/feed", status_code=303)


@app.post("/portal/block-node")
async def handle_block_node(target_phone: str = Form(...), current_user=Depends(get_current_farmer)):
    """Block a peer so they can no longer message you."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    clean_t = clean_phone(target_phone)
    if clean_t == current_user["phone"]:
        return RedirectResponse(url="/portal/feed?active_tab=messages", status_code=303)
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO blocked_nodes (blocker_phone, blocked_phone) VALUES (?, ?)",
            (current_user["phone"], clean_t)
        )
        await conn.commit()
    return RedirectResponse(url=f"/portal/feed?active_tab=messages&search_phone={clean_t}", status_code=303)


@app.post("/portal/unblock-node")
async def handle_unblock_node(target_phone: str = Form(...), current_user=Depends(get_current_farmer)):
    """Remove a previously blocked peer."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    clean_t = clean_phone(target_phone)
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "DELETE FROM blocked_nodes WHERE blocker_phone = ? AND blocked_phone = ?",
            (current_user["phone"], clean_t)
        )
        await conn.commit()
    return RedirectResponse(url=f"/portal/feed?active_tab=messages&search_phone={clean_t}", status_code=303)


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
    redirect_url = f"/portal/feed?active_tab=messages&search_phone={clean_r}"

    if not msg_body:
        return RedirectResponse(url=redirect_url, status_code=303)

    if len(msg_body) > MAX_MESSAGE_LENGTH:
        return RedirectResponse(url=redirect_url + "&error=length", status_code=303)

    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row

        # Resolve peer (with Nigerian format fallback)
        async with conn.execute("SELECT phone, lga, status FROM farmers WHERE phone = ?", (clean_r,)) as cur:
            peer = await cur.fetchone()
        if not peer:
            if clean_r.startswith("0") and len(clean_r) == 11:
                alt = "234" + clean_r[1:]
            elif clean_r.startswith("234") and len(clean_r) == 13:
                alt = "0" + clean_r[3:]
            else:
                alt = None
            if alt:
                async with conn.execute("SELECT phone, lga, status FROM farmers WHERE phone = ?", (alt,)) as cur:
                    peer = await cur.fetchone()
                if peer:
                    clean_r = peer["phone"]
                    redirect_url = f"/portal/feed?active_tab=messages&search_phone={clean_r}"

        if not peer:
            return RedirectResponse(url=redirect_url + "&error=notfound", status_code=303)

        # Same-LGA restriction
        if peer["lga"] != current_user["lga"]:
            return RedirectResponse(url=redirect_url + "&error=lga", status_code=303)

        # Block check (either direction)
        async with conn.execute("""
            SELECT 1 FROM blocked_nodes
            WHERE (blocker_phone = ? AND blocked_phone = ?)
               OR (blocker_phone = ? AND blocked_phone = ?)
        """, (current_user["phone"], clean_r, clean_r, current_user["phone"])) as cur:
            if await cur.fetchone():
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

    return RedirectResponse(url=redirect_url, status_code=303)


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


@app.get("/portal/feed", response_class=HTMLResponse)
async def farmer_feed_portal(
    current_user=Depends(get_current_farmer),
    active_tab: Optional[str] = Query(None),
    search_phone: Optional[str] = Query(None),
    market_cat: Optional[str] = Query(None),
    market_status: Optional[str] = Query(None),
    market_q: Optional[str] = Query(None),
    market_sort: Optional[str] = Query(None),
    market_mine: Optional[str] = Query(None)
):
    if not current_user: return RedirectResponse(url="/portal/login?error=Session required.", status_code=303)
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
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM farmers WHERE lga = ? AND status = 'Pending'",
                                (current_user['lga'],)) as c1:
            pending_neighbors = await c1.fetchall()
        async with conn.execute("SELECT * FROM farmers WHERE lga = ? AND status = 'Approved' AND phone != ?",
                                (current_user['lga'], current_user['phone'])) as c2:
            approved_neighbors = await c2.fetchall()
        async with conn.execute("SELECT * FROM alerts_log WHERE lga = ? AND status = 'Active' ORDER BY id DESC",
                                (current_user['lga'],)) as c3:
            active_threats = await c3.fetchall()
        # Community engagement data
        async with conn.execute("""
            SELECT c.farmer_phone, f.name, c.timestamp FROM checkins c
            JOIN farmers f ON f.phone = c.farmer_phone
            WHERE c.lga = ? AND c.timestamp > datetime('now', '-1 day')
            ORDER BY c.id DESC LIMIT 20
        """, (current_user['lga'],)) as c4:
            recent_checkins = await c4.fetchall()
        async with conn.execute("""
            SELECT farmer_name, message, timestamp FROM shoutouts
            WHERE lga = ? ORDER BY id DESC LIMIT 25
        """, (current_user['lga'],)) as c5:
            recent_shoutouts = await c5.fetchall()
        async with conn.execute("""
            SELECT id FROM checkins
            WHERE farmer_phone = ? AND date(timestamp) = date('now', 'localtime') LIMIT 1
        """, (current_user['phone'],)) as c6:
            checked_in_today = await c6.fetchone() is not None
        async with conn.execute("""
            SELECT name, xp, phone FROM farmers
            WHERE lga = ? AND status = 'Approved'
            ORDER BY xp DESC LIMIT 10
        """, (current_user['lga'],)) as c7:
            leaderboard_rows = await c7.fetchall()
        async with conn.execute("""
            SELECT id, title, embed_path FROM spotify_links
            WHERE farmer_phone = ? ORDER BY id DESC LIMIT 20
        """, (current_user["phone"],)) as c_sp:
            my_spotify_links = await c_sp.fetchall()
        # Market filter: category + status + search + sort
        status_filter = market_status if market_status in ("Active", "Sold", "All") else "Active"
        cat_filter = market_cat if market_cat in PRODUCT_CATEGORIES else None
        search_q = (market_q or "").strip()[:80]
        sort_key = market_sort if market_sort in ("newest", "oldest", "title_az", "title_za") else "newest"
        if status_filter == "All":
            sql = "SELECT * FROM farm_products WHERE status IN ('Active','Sold')"
            params: list = []
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
        show_mine_only = (market_mine or "").lower() in ("1", "yes", "true")
        if show_mine_only:
            sql += " AND farmer_phone = ?"
            params.append(current_user["phone"])
        order_map = {
            "newest": "id DESC",
            "oldest": "id ASC",
            "title_az": "title COLLATE NOCASE ASC",
            "title_za": "title COLLATE NOCASE DESC",
        }
        sql += f" ORDER BY {order_map[sort_key]} LIMIT 50"
        async with conn.execute(sql, params) as c8:
            market_products = await c8.fetchall()
        market_result_count = len(market_products)

    tip_of_day = FARMING_TIPS[int(__import__('datetime').datetime.now().strftime('%j')) % len(FARMING_TIPS)]

    my_spotify_options = "".join([
        f'<option value="{html.escape(s["embed_path"])}">★ {html.escape(s["title"])}</option>'
        for s in my_spotify_links
    ])
    my_spotify_list_html = "".join([
        f'''<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.05);">
            <button type="button" onclick="setSpotifyEmbed('{html.escape(s["embed_path"])}')" style="background:none;border:none;color:#1db954;font-size:14px;font-weight:700;cursor:pointer;text-align:left;padding:0;">{html.escape(s["title"])}</button>
            <form action="/portal/spotify/delete" method="post" style="margin:0;">
                <input type="hidden" name="link_id" value="{s["id"]}">
                <button type="submit" style="background:none;border:none;color:#f87171;font-size:12px;cursor:pointer;">Remove</button>
            </form>
        </div>'''
        for s in my_spotify_links
    ]) or '<p style="color:var(--text-muted);font-size:13px;margin:0;">No saved links yet — paste yours below.</p>'

    leaderboard_html = ""
    for i, row in enumerate(leaderboard_rows):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
        is_me = row["phone"] == current_user["phone"]
        name_style = "color:#6ee7b7; font-weight:800;" if is_me else "color:#e2e8f0; font-weight:600;"
        leaderboard_html += f"""
        <div style="display:flex; align-items:center; gap:10px; padding:10px 0; border-bottom:1px solid rgba(255,255,255,0.05);">
            <span style="width:28px; text-align:center; font-size:16px;">{medal}</span>
            <span style="flex:1; font-size:15px; {name_style}">{html.escape(row['name'])}{" (you)" if is_me else ""}</span>
            <span style="font-size:14px; color:#fbbf24; font-weight:700;">⚡ {row['xp']} XP</span>
        </div>"""
    if not leaderboard_html:
        leaderboard_html = '<p style="color:var(--text-muted); font-size:13px;">No ranked farmers yet.</p>'

    products_html = ""
    for p in market_products:
        is_mine = p["farmer_phone"] == current_user["phone"]
        is_sold = p["status"] == "Sold"
        actions = ""
        if is_mine and not is_sold:
            actions = f"""
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
            <form action="/portal/market/remove" method="post" style="display:inline; margin:0;">
                <input type="hidden" name="product_id" value="{p['id']}">
                <button type="submit" style="background:none;border:none;color:#f87171;font-size:12px;cursor:pointer;padding:4px 8px;">Remove</button>
            </form>"""

        photo_html = ""
        if p["photo_path"]:
            photo_html = f'<img src="/media/{html.escape(p["photo_path"])}" alt="" style="width:100%; max-height:200px; object-fit:cover; border-radius:12px; margin-bottom:12px;">'

        sold_badge = '<span style="background:rgba(245,158,11,0.2); color:#fbbf24; font-size:12px; font-weight:800; padding:4px 10px; border-radius:6px; margin-left:6px;">SOLD</span>' if is_sold else ""
        price_color = "#94a3b8" if is_sold else "#6ee7b7"
        card_opacity = "opacity:0.75;" if is_sold else ""
        contact_raw = p["contact_phone"] or p["farmer_phone"] or ""
        call_btn = ""
        if contact_raw and not is_sold:
            call_btn = f'<a href="tel:{html.escape(str(contact_raw))}" style="display:inline-block;padding:10px 16px;background:rgba(59,130,246,0.2);border:1px solid rgba(59,130,246,0.4);color:#93c5fd;border-radius:10px;font-size:14px;font-weight:700;text-decoration:none;">📞 Call seller</a>'

        products_html += f"""
        <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:14px; padding:16px; margin-bottom:14px; {card_opacity}">
            {photo_html}
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px; flex-wrap:wrap;">
                <div style="flex:1; min-width:140px;">
                    <div style="font-size:13px; color:#94a3b8; font-weight:700;">{html.escape(p['category'] or 'General')} · {html.escape(p['lga'] or '')}{sold_badge}</div>
                    <div style="font-size:18px; font-weight:800; color:#f1f5f9; margin-top:6px; line-height:1.3;">{html.escape(p['title'])}</div>
                </div>
                <div style="font-size:18px; font-weight:800; color:{price_color}; white-space:nowrap;">{html.escape(p['price'] or 'Ask price')}</div>
            </div>
            <p style="font-size:15px; color:#cbd5e1; margin:12px 0; line-height:1.5;">{html.escape(p['description'] or '')}</p>
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; font-size:14px;">
                <span style="color:#94a3b8;">Seller: <b style="color:#e2e8f0;">{html.escape(p['farmer_name'] or '')}</b></span>
                <span style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">{call_btn}{actions}</span>
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

    category_options = "".join([f'<option value="{c}">{c}</option>' for c in PRODUCT_CATEGORIES])
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
    result_label = f'{market_result_count} product{"s" if market_result_count != 1 else ""} found'
    clear_filters_btn = f'<a href="/portal/feed?active_tab=market" style="font-size:14px;color:#f87171;font-weight:700;text-decoration:none;">Clear all filters</a>' if has_filters else ""

    checkins_html = "".join([f"""
        <div style="display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid rgba(255,255,255,0.05); font-size:14px;">
            <span style="color:#e2e8f0; font-weight:600;">{html.escape(c['name'])}</span>
            <span style="color:#94a3b8; font-size:12px;">OK · {c['timestamp']}</span>
        </div>""" for c in recent_checkins]) or '<p style="color:var(--text-muted); font-size:13px;">No check-ins yet today. Be the first!</p>'

    shoutouts_html = "".join([f"""
        <div style="background:rgba(255,255,255,0.04); border-radius:10px; padding:12px; margin-bottom:8px;">
            <div style="font-weight:700; color:#6ee7b7; font-size:13px;">{html.escape(s['farmer_name'])}</div>
            <div style="color:#f1f5f9; font-size:14px; margin-top:4px;">{s['message']}</div>
            <div style="color:#64748b; font-size:11px; margin-top:4px;">{s['timestamp']}</div>
        </div>""" for s in recent_shoutouts]) or '<p style="color:var(--text-muted); font-size:13px;">No shout-outs yet. Say hello to your neighbours!</p>'

    nb_pending = "".join([f"""
        <div style='background:#1e293b; padding:16px; margin:10px 0; border-radius:12px; display:flex; justify-content:space-between; align-items:center;'>
            <div><div style='font-weight:600; color:#fff;'>{n['name']}</div><div style='font-size:12px; color:var(--text-muted);'>{mask_phone_number(n['phone'])}</div></div>
            <form action='/portal/approve-node' method='post' style='margin:0;'><input type='hidden' name='target_phone' value='{n['phone']}'><button type='submit' class='btn btn-emerald' style='padding:8px 16px; font-size:12px; border-radius:8px;'>🔒 Verify Identity</button></form>
        </div>""" for n in pending_neighbors])
    nb_approved = "".join([f"""
        <div style='padding:12px 16px; background:rgba(16,185,129,0.03); border:1px solid rgba(16,185,129,0.15); border-radius:10px; margin-bottom:8px; display:flex; align-items:center; gap:10px;'>
            🟢 <div style='flex:1;'><span style='font-weight:600; color:#f1f5f9;'>{f['name']}</span></div>
            <form action='/portal/flag-node' method='post' style='margin:0;'><input type='hidden' name='target_phone' value='{f['phone']}'><button type='submit' class='btn btn-danger' style='padding:4px 10px; font-size:11px; border-radius:6px;'>Flag Node</button></form>
            <span style='font-size:11px; color:var(--accent-emerald); background:rgba(16,185,129,0.1); padding:2px 8px; border-radius:4px;'>Online</span>
        </div>""" for f in approved_neighbors])

    # --- Direct Messages / Peer Lookup logic ---
    peer_card_html = ""
    messages_log_html = ""
    send_form_html = ""
    safety_notice = ""
    clean_search = ""
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

    if clean_search:
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            peer = None
            async with conn.execute("SELECT * FROM farmers WHERE phone = ?", (clean_search,)) as cur:
                peer = await cur.fetchone()
            if not peer and clean_search.startswith("0") and len(clean_search) == 11:
                alt = "234" + clean_search[1:]
                async with conn.execute("SELECT * FROM farmers WHERE phone = ?", (alt,)) as cur:
                    peer = await cur.fetchone()
                if peer:
                    clean_search = peer["phone"]
            elif not peer and clean_search.startswith("234") and len(clean_search) == 13:
                alt = "0" + clean_search[3:]
                async with conn.execute("SELECT * FROM farmers WHERE phone = ?", (alt,)) as cur:
                    peer = await cur.fetchone()
                if peer:
                    clean_search = peer["phone"]

            if peer:
                my_phone = current_user["phone"]
                peer_phone = peer["phone"]
                same_lga = peer["lga"] == current_user["lga"]
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

                peer_card_html = f"""
                <div style="background:rgba(59,130,246,0.08); border:1px solid rgba(59,130,246,0.25); border-radius:14px; padding:18px; margin-bottom:16px;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap;">
                        <div>
                            <div style="font-weight:700; font-size:16px; color:#fff; margin-bottom:6px;">{html.escape(peer['name'])}</div>
                            <div style="font-size:13px; color:var(--text-muted);">LGA Sector: <b>{html.escape(peer['lga'])}</b></div>
                            <div style="font-size:13px; color:var(--text-muted); margin-top:4px;">
                                Status: <span class="badge {status_badge_class}">{html.escape(peer['status'])}</span>
                            </div>
                            <div style="font-size:12px; color:var(--text-muted); margin-top:6px; font-family:monospace;">
                                {mask_phone_number(peer_phone)}
                            </div>
                        </div>
                        <div style="display:flex; gap:8px; align-items:center;">{block_btn}</div>
                    </div>
                </div>"""

                if not same_lga:
                    peer_card_html += """
                    <div style="background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.25); border-radius:10px; padding:12px 16px; margin-bottom:14px; font-size:13px; color:#fbbf24;">
                        Messaging is limited to farmers in the same LGA for community safety.
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
                    async with conn.execute("""
                        SELECT * FROM direct_messages
                        WHERE (sender_phone = ? AND receiver_phone = ?)
                           OR (sender_phone = ? AND receiver_phone = ?)
                        ORDER BY id ASC
                    """, (my_phone, peer_phone, peer_phone, my_phone)) as mcur:
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
            else:
                peer_card_html = '<p style="color:var(--text-muted); font-size:14px; text-align:center; margin:20px 0;">No registered node found for that number. Please check and try again.</p>'

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
    is_market_tab = tab == "market"
    is_incidents_tab = tab not in ("messages", "community", "market")
    tab_incidents_active = "background:rgba(16,185,129,0.2); color:#10b981;" if is_incidents_tab else "background:transparent; color:var(--text-muted);"
    tab_messages_active = "background:rgba(16,185,129,0.2); color:#10b981;" if is_messages_tab else "background:transparent; color:var(--text-muted);"
    tab_community_active = "background:rgba(16,185,129,0.2); color:#10b981;" if is_community_tab else "background:transparent; color:var(--text-muted);"
    tab_market_active = "background:rgba(16,185,129,0.2); color:#10b981;" if is_market_tab else "background:transparent; color:var(--text-muted);"
    show_incidents = "display:block;" if is_incidents_tab else "display:none;"
    show_messages = "display:block;" if is_messages_tab else "display:none;"
    show_community = "display:block;" if is_community_tab else "display:none;"
    show_market = "display:block;" if is_market_tab else "display:none;"
    checked_in_btn = "background:#334155; color:#94a3b8; pointer-events:none;" if checked_in_today else ""
    checked_in_label = "Checked in today ✓" if checked_in_today else f"I'm OK (+{CHECKIN_XP} XP)"

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
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        {UPGRADED_CSS}
        .portal-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 24px; margin-top: 24px; }}
        .portal-card {{
            background: linear-gradient(155deg, rgba(22, 52, 38, 0.88) 0%, rgba(18, 40, 48, 0.82) 100%);
            border: 1px solid rgba(110, 231, 183, 0.14);
            border-radius: 20px;
            padding: 24px;
            box-shadow: 0 12px 36px -12px rgba(0,0,0,0.4), 0 0 28px -12px rgba(52, 211, 153, 0.15);
            display: flex;
            flex-direction: column;
        }}
        .card-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 18px; border-bottom: 1px solid rgba(110, 231, 183, 0.1); padding-bottom: 12px; }}
        .card-title {{ font-size: 16px; font-weight: 700; color: #ecfdf5; margin: 0; }}
        .weather-value {{ font-size: 32px; font-weight: 800; color: #6ee7b7; margin: 10px 0 5px 0; font-family: monospace; text-shadow: 0 0 20px rgba(52, 211, 153, 0.35); }}
        .tab-bar {{
            display:flex; gap:8px; margin-bottom:20px;
            background: linear-gradient(90deg, rgba(52, 211, 153, 0.06), rgba(167, 139, 250, 0.06));
            padding:6px; border-radius:14px; border:1px solid rgba(110, 231, 183, 0.12);
        }}
        .tab-btn {{ flex:1; text-align:center; padding:12px 16px; border-radius:10px; font-weight:700; font-size:14px; cursor:pointer; text-decoration:none; transition:all 0.25s; }}
    </style></head>
    <body>
        <div class="container" style="max-width:1200px; padding:20px 0;">
            <div style="background:var(--panel-glass); border:1px solid var(--border-glass); border-radius:24px; padding:24px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:15px; margin-bottom:24px;">
                <div style="display:flex; align-items:center; gap:16px;">
                    <div style="font-size:40px;">👨‍🌾</div>
                    <div><h1 style="margin:0; font-size:22px; font-weight:800; color:#fff;">Terminal: {current_user['name']}</h1><span class="badge badge-emerald" style="margin-top:6px;">📍 {current_user['lga']} Sector Grid</span></div>
                </div>
                <div style="display:flex; gap:12px; align-items:center;"><span id="grid_score_display" class="badge badge-amber" style="font-weight:800; padding:8px 16px; font-size:13px;">⚡ {current_user['xp']} Grid XP</span><a href="/portal/logout" class="btn btn-danger" style="padding:10px 20px; font-size:13px; border-radius:10px;">🔌 Disconnect</a></div>
            </div>

            <div class="tab-bar">
                <a href="/portal/feed?active_tab=incidents" class="tab-btn" style="{tab_incidents_active}">🛡️ Alerts</a>
                <a href="/portal/feed?active_tab=community" class="tab-btn" style="{tab_community_active}">🎉 Community</a>
                <a href="/portal/feed?active_tab=market" class="tab-btn" style="{tab_market_active}">🛒 Market</a>
                <a href="/portal/feed?active_tab=messages" class="tab-btn" style="{tab_messages_active}">💬 Messages</a>
            </div>

            <div id="tab_incidents" style="{show_incidents}">
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
                    <div class="portal-card"><div class="card-header">🤝 <h3 class="card-title">P2P Trust Gate</h3></div><div style="flex:1; max-height:220px; overflow-y:auto;">{nb_pending or '<p style="color:var(--text-muted); font-size:13px; margin:0;">Grid clear.</p>'}</div></div>
                </div>

                <!-- Farm Radio Receiver -->
                <div class="portal-card" style="margin-top:24px; border-color: rgba(168,85,247,0.25);">
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
                    <audio id="radio_audio" crossorigin="anonymous" preload="none" style="display:none;"></audio>
                </div>

                <!-- Spotify -->
                <div class="portal-card" style="margin-top:24px; border-color: rgba(29,185,84,0.3);">
                    <div class="card-header" style="border-color: rgba(29,185,84,0.2);">
                        🎧 <h3 class="card-title" style="color:#1db954;">Spotify — Your links</h3>
                    </div>
                    <p style="font-size:14px; color:#cbd5e1; margin:0 0 14px 0; line-height:1.45;">
                        Save your favourite playlists here. Paste a Spotify link, give it a name, and play anytime.
                    </p>

                    <div style="background:rgba(29,185,84,0.06); border:1px solid rgba(29,185,84,0.2); border-radius:12px; padding:14px; margin-bottom:16px;">
                        <div style="font-size:13px; font-weight:700; color:#1db954; margin-bottom:8px;">My saved playlists</div>
                        {my_spotify_list_html}
                    </div>

                    <form action="/portal/spotify/save" method="post" style="background:rgba(0,0,0,0.2); padding:14px; border-radius:12px; margin-bottom:14px;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Name</label>
                        <input type="text" name="title" required maxlength="60" placeholder="e.g. My farm work mix"
                               style="width:100%; padding:12px; font-size:16px; background:rgba(10,31,20,0.9); border:2px solid rgba(29,185,84,0.35); color:#f0fdf4; border-radius:10px; box-sizing:border-box; margin-bottom:10px;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Spotify link</label>
                        <input type="text" name="url" required placeholder="Paste playlist / album / song link from Spotify"
                               style="width:100%; padding:12px; font-size:15px; background:rgba(10,31,20,0.9); border:2px solid rgba(29,185,84,0.35); color:#f0fdf4; border-radius:10px; box-sizing:border-box; margin-bottom:12px;">
                        <button type="submit" class="btn btn-emerald" style="width:100%; padding:14px; font-size:16px; background:linear-gradient(135deg,#1db954,#1ed760); color:#042f1a;">Save my link</button>
                    </form>

                    <div style="display:flex; flex-wrap:wrap; gap:10px; margin-bottom:12px; align-items:center;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0; margin:0;">Quick play</label>
                        <select id="spotify_preset" onchange="loadSpotifyPreset()" style="flex:1; min-width:180px; padding:12px; font-size:16px; background:rgba(10,31,20,0.9); border:2px solid rgba(29,185,84,0.35); color:#f0fdf4; border-radius:10px;">
                            <option value="">— Choose —</option>
                            <optgroup label="My links">{my_spotify_options or '<option disabled>None saved yet</option>'}</optgroup>
                            <optgroup label="Suggested">
                                <option value="playlist/37i9dQZF1DWYkaDi7aYkT9">Afrobeats Hits</option>
                                <option value="playlist/37i9dQZF1DX4sWSpwq3LiO">Peaceful Piano</option>
                                <option value="playlist/37i9dQZF1DX3Ogo9pFvBkY">Ambient Relaxation</option>
                                <option value="playlist/37i9dQZF1DX0XUsuxWHRQd">RapCaviar</option>
                            </optgroup>
                        </select>
                    </div>
                    <div style="display:flex; flex-wrap:wrap; gap:10px; margin-bottom:14px; align-items:center;">
                        <input type="text" id="spotify_url" placeholder="Or paste link just to play (without saving)"
                               style="flex:1; min-width:200px; padding:12px; font-size:15px; background:rgba(10,31,20,0.9); border:2px solid rgba(29,185,84,0.35); color:#f0fdf4; border-radius:10px;">
                        <button type="button" onclick="loadSpotifyUrl()" class="btn btn-emerald" style="padding:12px 18px; font-size:15px; background:linear-gradient(135deg,#1db954,#1ed760); color:#042f1a;">Play</button>
                    </div>
                    <div id="spotify_wrap" style="border-radius:12px; overflow:hidden; background:rgba(0,0,0,0.25); min-height:80px;">
                        <div id="spotify_placeholder" style="padding:28px; text-align:center; color:#94a3b8; font-size:14px;">
                            Save your links above, then tap one to play
                        </div>
                        <iframe id="spotify_iframe" style="display:none; width:100%; height:152px; border:0;" allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture" loading="lazy"></iframe>
                    </div>
                    <p style="font-size:12px; color:#64748b; margin:10px 0 0 0;">
                        How to copy a link: open Spotify → share → Copy link. Free accounts play with ads.
                    </p>
                </div>

                <!-- Farm TV — Nigerian channels -->
                <div class="portal-card" style="margin-top:24px; border-color: rgba(239,68,68,0.25);">
                    <div class="card-header" style="border-color: rgba(239,68,68,0.2);">
                        📺 <h3 class="card-title" style="color:#fca5a5;">Farm TV — Nigerian Channels</h3>
                    </div>
                    <p style="font-size:14px; color:#cbd5e1; margin:0 0 14px 0; line-height:1.45;">
                        News, football &amp; entertainment. Choose a channel. Needs internet.
                    </p>
                    <div style="display:flex; flex-wrap:wrap; gap:10px; margin-bottom:14px; align-items:center;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0; margin:0;">Channel</label>
                        <select id="tv_channel" onchange="loadTvChannel()" style="flex:1; min-width:200px; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px;">
                            <option value="">— Select a TV channel —</option>
                            <optgroup label="📰 News">
                                <option value="ch:UCEXGDNclvmg6RW0vipJYsTQ">Channels Television</option>
                                <option value="ch:UCgp4A6I8LCWrhUzn-5SbKvA">TVC News Nigeria</option>
                                <option value="ch:UCQzc5L69qj73yq_OIBM7wNg">News Central TV</option>
                                <option value="yt:@AriseNewsChannel">Arise News</option>
                                <option value="yt:@NTALive">NTA Live</option>
                            </optgroup>
                            <optgroup label="⚽ Football &amp; Sports">
                                <option value="yt:@BrilaMedia">Brila Media TV (Football &amp; Sports)</option>
                                <option value="yt:@SuperSport">SuperSport (highlights / live when available)</option>
                            </optgroup>
                            <optgroup label="🎵 Entertainment &amp; Music">
                                <option value="yt:@SoundcityTVAfrica">Soundcity TV</option>
                                <option value="yt:@africamagicofficial">Africa Magic</option>
                                <option value="yt:@SpiceTVAfrica">Spice TV</option>
                            </optgroup>
                        </select>
                    </div>
                    <div id="tv_player_wrap" style="position:relative; width:100%; padding-bottom:56.25%; background:#0f172a; border-radius:12px; overflow:hidden; border:1px solid rgba(255,255,255,0.08);">
                        <div id="tv_placeholder" style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:#94a3b8; font-size:15px; text-align:center; padding:20px;">
                            Select a channel to start watching
                        </div>
                        <iframe id="tv_iframe" style="display:none; position:absolute; top:0; left:0; width:100%; height:100%; border:0;" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>
                    </div>
                    <p style="font-size:12px; color:#64748b; margin:10px 0 0 0;">Powered by official YouTube live streams. If a channel is offline, try another.</p>
                </div>

                <div class="portal-grid" style="grid-template-columns: 1fr; margin-top:24px;">
                    <div class="portal-card" style="border-color: rgba(239,68,68,0.2);"><div class="card-header" style="border-color: rgba(239,68,68,0.15);">🛡️ <h3 class="card-title" style="color:#ef4444;">Active Sector Threat Vectors</h3></div>{echo_feed_html or '<div style="text-align:center; padding:20px; color:var(--text-muted); font-style:italic; font-size:14px;">🟢 Secure baseline. Local sector is quiet.</div>'}</div>
                    <div class="portal-card" style="border-color: rgba(245,158,11,0.2);">
                        <div class="card-header" style="border-color: rgba(245,158,11,0.15);">🚨 <h3 class="card-title" style="color:var(--accent-amber);">Broadcast Emergency Panic Vector</h3></div>
                        <form id="emergency_form" action="/portal/alert/raise" method="post" enctype="multipart/form-data" onsubmit="executeTransmissionSequence(event)">
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:15px; margin-bottom:15px;">
                                <div><label style="display:block; margin-bottom:8px; font-size:12px; color:var(--text-muted); font-weight:700;">Classification</label><select id="alert_type" name="alert_type"><option value="Intruder Spotted">⚠️ Intruder Spotted</option><option value="Critical Disaster">🔥 Critical Disaster</option><option value="Armed Attack">⚔️ Armed Attack</option></select></div>
                                <div><label style="display:block; margin-bottom:8px; font-size:12px; color:var(--text-muted); font-weight:700;">Tactical Coordinates</label><input type="text" id="alert_message" name="message" placeholder="State coordinates..." required></div>
                            </div>
                            <div style="margin-bottom:20px;"><label style="display:block; margin-bottom:8px; font-size:12px; color:var(--text-muted); font-weight:700;">📷 Attach Video Clip Evidence (Optional)</label><input type="file" name="video_evidence" accept="video/*" style="background:#090d16; color:white; padding:10px; border-radius:12px; border:1px solid var(--border-glass); width:100%;"></div>
                            <button type="submit" id="panic_btn" class="btn" style="width:100%; padding:16px; background:#ef4444; color:white; font-size:15px; font-weight:bold; box-shadow: 0 4px 20px rgba(239,68,68,0.25);">📡 Execute Strategic Grid Alarm</button>
                        </form>
                    </div>
                </div>
            </div>

            <div id="tab_community" style="{show_community}">
                <div class="portal-grid">
                    <div class="portal-card">
                        <div class="card-header">✅ <h3 class="card-title">Daily Check-in</h3></div>
                        <p style="font-size:14px; color:#cbd5e1; margin:0 0 14px 0;">Let neighbours know you are safe today.</p>
                        <form action="/portal/checkin" method="post">
                            <button type="submit" class="btn btn-emerald" style="width:100%; padding:16px; font-size:17px; {checked_in_btn}">{checked_in_label}</button>
                        </form>
                        <div style="margin-top:18px; max-height:200px; overflow-y:auto;">
                            <div style="font-size:12px; color:var(--text-muted); text-transform:uppercase; font-weight:700; margin-bottom:8px;">Who checked in (24h)</div>
                            {checkins_html}
                        </div>
                    </div>

                    <div class="portal-card">
                        <div class="card-header">💡 <h3 class="card-title">Tip of the Day</h3></div>
                        <p style="font-size:16px; color:#f1f5f9; line-height:1.55; margin:0;">{tip_of_day}</p>
                        <div style="margin-top:16px; padding:12px; background:rgba(16,185,129,0.08); border-radius:10px; font-size:13px; color:#a7f3d0;">
                            Weekly challenge: Log a soil reading or verify a neighbour — earn XP!
                        </div>
                    </div>

                    <div class="portal-card">
                        <div class="card-header">🏆 <h3 class="card-title">LGA Leaderboard</h3></div>
                        <p style="font-size:13px; color:#94a3b8; margin:0 0 12px 0;">Top farmers in your sector by Grid XP</p>
                        <div style="max-height:320px; overflow-y:auto;">{leaderboard_html}</div>
                    </div>

                    <div class="portal-card" style="grid-column:1 / -1;">
                        <div class="card-header">📣 <h3 class="card-title">Neighbour Shout-outs</h3></div>
                        <form action="/portal/shoutout" method="post" style="display:flex; gap:10px; margin-bottom:16px;">
                            <input type="text" name="message" maxlength="{MAX_SHOUTOUT_LEN}" required placeholder="Say hello to your LGA…"
                                   style="flex:1; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px;">
                            <button type="submit" class="btn btn-emerald" style="padding:12px 18px;">Post (+{SHOUTOUT_XP} XP)</button>
                        </form>
                        <div style="max-height:280px; overflow-y:auto;">{shoutouts_html}</div>
                    </div>

                    <div class="portal-card">
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

                    <div class="portal-card">
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

            <div id="tab_market" style="{show_market}">
                <div class="portal-card" style="max-width:720px; margin:0 auto 20px;">
                    <div class="card-header">🛒 <h3 class="card-title">Farm Market</h3></div>
                    <p style="font-size:14px; color:#cbd5e1; margin:0 0 16px 0; line-height:1.45;">
                        Promote your crops, livestock, tools or produce. Neighbours can contact you directly.
                        Posting earns <b style="color:#6ee7b7;">+{PRODUCT_POST_XP} XP</b>.
                    </p>
                    <form action="/portal/market/post" method="post" enctype="multipart/form-data" style="background:rgba(0,0,0,0.2); padding:16px; border-radius:14px; margin-bottom:8px;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">What are you selling?</label>
                        <input type="text" name="title" required maxlength="{MAX_PRODUCT_TITLE}" placeholder="e.g. Fresh cassava, 50kg bags"
                               style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; box-sizing:border-box; margin-bottom:12px;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Category</label>
                        <select name="category" style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; margin-bottom:12px;">
                            {category_options}
                        </select>
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Price</label>
                        <input type="text" name="price" placeholder="e.g. ₦15,000 per bag" maxlength="40"
                               style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; box-sizing:border-box; margin-bottom:12px;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Details</label>
                        <input type="text" name="description" maxlength="{MAX_PRODUCT_DESC}" placeholder="Quality, quantity, location notes…"
                               style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; box-sizing:border-box; margin-bottom:12px;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Photo (optional)</label>
                        <input type="file" name="photo" accept="image/jpeg,image/png,image/webp"
                               style="width:100%; padding:12px; font-size:14px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; box-sizing:border-box; margin-bottom:12px;">
                        <label style="font-size:14px; font-weight:700; color:#e2e8f0;">Contact phone (optional)</label>
                        <input type="text" name="contact_phone" placeholder="Leave blank to use your registered number" inputmode="numeric"
                               style="width:100%; padding:12px; font-size:16px; background:#1e293b; border:2px solid #475569; color:#f8fafc; border-radius:10px; box-sizing:border-box; margin-bottom:14px;">
                        <button type="submit" class="btn btn-emerald" style="width:100%; padding:16px; font-size:17px;">Post to Market</button>
                    </form>
                </div>
                <div class="portal-card" style="max-width:720px; margin:0 auto;">
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
                    {products_html}
                </div>
            </div>

            <div id="tab_messages" style="{show_messages}">
                <div class="portal-card" style="max-width:720px; margin:0 auto;">
                    <div class="card-header">💬 <h3 class="card-title">Node P2P Comms</h3></div>
                    {safety_notice}
                    <form action="/portal/feed" method="get" style="margin-bottom:18px; display:flex; gap:10px;">
                        <input type="hidden" name="active_tab" value="messages">
                        <input type="text" name="search_phone" placeholder="Enter registered mobile number (same LGA)..." value="{clean_search}" required
                               style="flex:1; padding:12px; background:#090d16; border:1px solid var(--border-glass); color:white; border-radius:10px;">
                        <button type="submit" class="btn btn-emerald" style="padding:12px 20px;">Lookup Peer</button>
                    </form>
                    {peer_card_html}
                    <div style="max-height:340px; overflow-y:auto; margin-bottom:12px; padding:12px; background:rgba(0,0,0,0.25); border-radius:12px; min-height:120px;">
                        {messages_log_html or '<p style="color:var(--text-muted); font-size:13px; text-align:center; margin:30px 0;">No messages yet. Lookup a peer in your LGA to start a conversation.</p>'}
                    </div>
                    {send_form_html}
                </div>
            </div>
        </div>
        <div id="radar_screen" class="glass-panel" style="max-width: 550px; margin: 60px auto; text-align: center; display: none;"><div class="radar-spinner"></div><span class="badge badge-amber pulse" style="margin-bottom: 16px;">Transmission Channel Engaged</span><h2>Transmitting...</h2></div>
        <script>
            async function triggerEchoAnimation(e, aId) {{ e.preventDefault(); const btn = document.getElementById('echo_btn_' + aId); btn.disabled = true; btn.innerText = "📡 Relaying..."; try {{ const res = await fetch('/portal/alert/relay', {{ method: 'POST', body: new FormData(e.target) }}); if (res.status === 200) {{ const newXp = await res.text(); document.getElementById('grid_score_display').innerText = "⚡ " + newXp + " Grid XP"; btn.className = "btn"; btn.style.background = "#10b981"; btn.innerText = "✅ Dispatched"; }} }} catch(err) {{ console.error(err); }} }}
            function executeTransmissionSequence(e) {{ e.preventDefault(); const termCard = document.getElementById('container'), radarScreen = document.getElementById('radar_screen'); if(termCard) termCard.style.display = 'none'; radarScreen.style.display = 'block'; const form = document.getElementById('emergency_form'), formData = new FormData(form); fetch(form.action, {{ method: form.method, body: formData }}).then(() => {{ window.location.href = '/portal/feed'; }}).catch(() => {{ window.location.href = '/portal/feed'; }}); }}

            // ----- Farm Radio with Bass / Mid / High EQ -----
            let radioCtx = null, radioSource = null, bassFilter = null, midFilter = null, highFilter = null, radioGain = null;
            let radioPlaying = false;

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
                        btn.innerText = 'Stop';
                        const name = document.getElementById('radio_station').selectedOptions[0].text;
                        status.innerText = 'Playing: ' + name;
                        status.style.color = '#6ee7b7';
                    }}
                }} catch (err) {{
                    status.innerText = 'Could not play this station. Try another one.';
                    status.style.color = '#f87171';
                    radioPlaying = false;
                    btn.innerText = 'Play';
                    console.error(err);
                }}
            }}

            document.getElementById('radio_station').addEventListener('change', function() {{
                const audio = document.getElementById('radio_audio');
                if (radioPlaying) {{
                    audio.pause();
                    radioPlaying = false;
                    document.getElementById('radio_play_btn').innerText = 'Play';
                    document.getElementById('radio_status').innerText = 'Station changed — press Play';
                    document.getElementById('radio_status').style.color = '#94a3b8';
                }}
            }});

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

            // ----- Rolling Dart -----
            function playDart() {{
                const score = Math.floor(Math.random() * 100) + 1;
                document.getElementById('dart_score_display').innerText = score;
                document.getElementById('dart_score_input').value = score;
                sfxDart(score);
                const msg = document.getElementById('dart_msg');
                if (score >= 50) {{
                    msg.innerText = 'Great throw! Submitting for XP…';
                    msg.style.color = '#6ee7b7';
                    setTimeout(() => document.getElementById('dart_score_form').submit(), 700);
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
                                    document.getElementById('hunt_msg').innerText = 'You found all seeds! Claiming XP…';
                                    document.getElementById('hunt_score_input').value = 3;
                                    setTimeout(() => document.getElementById('hunt_score_form').submit(), 800);
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

            // ----- Spotify embeds -----
            function setSpotifyEmbed(path) {{
                const iframe = document.getElementById('spotify_iframe');
                const placeholder = document.getElementById('spotify_placeholder');
                if (!path) {{
                    iframe.style.display = 'none';
                    iframe.src = '';
                    placeholder.style.display = 'block';
                    return;
                }}
                iframe.src = 'https://open.spotify.com/embed/' + path + '?utm_source=generator&theme=0';
                placeholder.style.display = 'none';
                iframe.style.display = 'block';
            }}
            function loadSpotifyPreset() {{
                const val = document.getElementById('spotify_preset').value;
                if (val) {{
                    document.getElementById('spotify_url').value = '';
                    setSpotifyEmbed(val);
                }}
            }}
            function loadSpotifyUrl() {{
                const raw = (document.getElementById('spotify_url').value || '').trim();
                if (!raw) return;
                // Accept open.spotify.com links for playlist, album, track, episode
                let m = raw.match(/open[.]spotify[.]com[/](playlist|album|track|episode|show)[/]([a-zA-Z0-9]+)/);
                if (!m) {{
                    // Also accept spotify:playlist:ID URI form
                    m = raw.match(/spotify:(playlist|album|track|episode|show):([a-zA-Z0-9]+)/);
                }}
                if (m) {{
                    document.getElementById('spotify_preset').value = '';
                    setSpotifyEmbed(m[1] + '/' + m[2]);
                }} else {{
                    document.getElementById('spotify_placeholder').style.display = 'block';
                    document.getElementById('spotify_placeholder').innerText = 'Link not recognized. Paste a Spotify playlist, album, or song link.';
                    document.getElementById('spotify_iframe').style.display = 'none';
                }}
            }}

            // ----- Farm TV (YouTube live embeds) -----
            function loadTvChannel() {{
                const sel = document.getElementById('tv_channel');
                const val = sel.value;
                const iframe = document.getElementById('tv_iframe');
                const placeholder = document.getElementById('tv_placeholder');
                if (!val) {{
                    iframe.style.display = 'none';
                    iframe.src = '';
                    placeholder.style.display = 'flex';
                    placeholder.innerText = 'Select a channel to start watching';
                    return;
                }}
                if (val.startsWith('ch:')) {{
                    // Direct channel ID — embed live stream in page
                    const channelId = val.slice(3);
                    iframe.src = 'https://www.youtube.com/embed/live_stream?channel=' + encodeURIComponent(channelId) + '&autoplay=1&rel=0';
                    placeholder.style.display = 'none';
                    iframe.style.display = 'block';
                }} else if (val.startsWith('yt:')) {{
                    // Open official YouTube channel live page (works when they are on air)
                    const handle = val.slice(3);
                    iframe.style.display = 'none';
                    iframe.src = '';
                    placeholder.style.display = 'flex';
                    placeholder.innerHTML = 'Opening <b>' + sel.selectedOptions[0].text + '</b>…<br><br>' +
                        '<a href="https://www.youtube.com/' + handle + '/live" target="_blank" rel="noopener" ' +
                        'style="display:inline-block;padding:12px 20px;background:#ef4444;color:#fff;border-radius:10px;font-weight:700;text-decoration:none;font-size:16px;">Watch live on YouTube</a>';
                    window.open('https://www.youtube.com/' + handle + '/live', '_blank', 'noopener');
                }}
            }}
        </script>
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
                             video_evidence: Optional[UploadFile] = File(None),
                             current_user=Depends(get_current_farmer)):
    if not current_user: raise HTTPException(status_code=401, detail="Unauthorized")
    v_name = None

    if video_evidence and video_evidence.filename:
        # Inspect binary magic signature headers to prevent structural file mismatches
        file_head = await video_evidence.read(8)
        await video_evidence.seek(0)
        valid_signatures = [b'ftypmp42', b'ftypisom', b'ftypMSNV', b'1A45DFA3', b'RIFF', b'ftypqt  ']

        if not any(sig in file_head for sig in valid_signatures):
            raise HTTPException(status_code=400, detail="Invalid video format header uploaded.")

        v_name = f"{hashlib.md5(os.urandom(16)).hexdigest()}_{sanitize(video_evidence.filename)}"
        with open(os.path.join(MEDIA_DIR, v_name), "wb") as f:
            f.write(await video_evidence.read())

    a_type, msg = sanitize(alert_type), sanitize(message)
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "INSERT INTO alerts_log (type, sender, lga, message, status, video_path) VALUES (?, ?, ?, ?, 'Active', ?)",
            (a_type, current_user['name'], current_user['lga'], msg, v_name))
        await conn.commit()

    override = a_type in ["Critical Disaster", "Armed Attack"]
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        q = "SELECT phone FROM farmers WHERE status = 'Approved' AND phone != ?" if override else "SELECT phone FROM farmers WHERE status = 'Approved' AND lga = ? AND phone != ?"
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
                if res_row: new_xp = res_row
            await conn.commit()
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT phone FROM farmers WHERE status = 'Approved' AND lga = ? AND phone != ?",
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
        async with conn.execute("SELECT * FROM farmers WHERE phone = ? AND status = 'Approved'",
                                (sender_number,)) as cursor: farmer = await cursor.fetchone()
    if not farmer: return Response(content="<Response></Response>", media_type="application/xml")
    alert_type, msg_lower = "General Anomaly", Body.lower()
    if "fire" in msg_lower or "flood" in msg_lower:
        alert_type = "Critical Disaster"
    elif "thief" in msg_lower or "intruder" in msg_lower:
        alert_type = "Intruder Spotted"
    elif "attack" in msg_lower or "armed" in msg_lower:
        alert_type = "Armed Attack"
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute(
            "INSERT INTO alerts_log (type, sender, lga, message, status, video_path) VALUES (?, ?, ?, ?, 'Active', NULL)",
            (alert_type, farmer['name'], farmer['lga'], sanitize(Body)))
        await conn.commit()
    return Response(content="<Response></Response>", media_type="application/xml")


@app.get("/", response_class=HTMLResponse)
def community_homepage():
    clean_logo_svg = """
    <svg width="90" height="90" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 16px rgba(16,185,129,0.35)); margin-bottom: 10px;">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        <path d="M12 8a3 3 0 0 0-3 3c0 3 3 7 3 7s3-4 3-7a3 3 0 0 0-3-3z"/>
        <circle cx="12" cy="11" r="1" fill="#10b981"/>
    </svg>
    """
    return f"""<html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            {UPGRADED_CSS}
            .welcome-title {{ margin: 5px 0 8px 0; font-size: 32px; font-weight: 900; letter-spacing: -0.02em; color: #fff; }}
            .subtitle {{ color: #cbd5e1; line-height: 1.65; font-size: 17px; margin: 0 auto 32px auto; max-width: 420px; }}
            .action-link {{ padding: 20px; font-size: 18px; font-weight: 800; color: #ffffff; border-radius: 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }}
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
            </div>
        </div>
    </body>
    </html>"""
