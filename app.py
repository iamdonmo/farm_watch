import os
import hmac
import hashlib
import html
import httpx
import asyncio
import aiosqlite
from typing import Optional, Dict, List
from fastapi import FastAPI, Form, Response, Depends, HTTPException, status, Cookie, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI(title="Farm Watch Enterprise Node", version="5.2.1")
security = HTTPBasic()

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
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

CITY_AUTOFILL_MAP = {
    "osogbo": {"country": "Nigeria", "state": "Osun", "lga": "Osogbo", "area": "Ataoja Sector"},
    "ile-ife": {"country": "Nigeria", "state": "Osun", "lga": "Ile-Ife", "area": "Ife Central Town"},
    "ibadan": {"country": "Nigeria", "state": "Oyo", "lga": "Ibadan", "area": "Ido Farming Grid"},
    "ogbomoso": {"country": "Nigeria", "state": "Oyo", "lga": "Ogbomoso", "area": "Ogbomoso South Central"}
}

#  MODERN LIFESPAN APPROACH
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. This runs BEFORE the application starts receiving requests (Startup)
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
        try:
            await conn.execute("ALTER TABLE alerts_log ADD COLUMN video_path TEXT;")
        except Exception:
            pass
        await conn.commit()

    yield  # 2. The app stays active and handles requests here

    # 3. Any cleanup code here runs when the app is shutting down (Shutdown)


# Pass the lifespan context manager into your FastAPI initialization
app = FastAPI(title="Farm Watch Enterprise Node", version="5.2.1", lifespan=lifespan)


def clean_phone(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())

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
    url = f"https://twilio.com{TWILIO_ACCOUNT_SID}/Messages.json"
    clean_target = f"whatsapp:+{clean_phone(to_number)}" if not to_number.startswith("+") else f"whatsapp:{to_number}"
    payload = {"To": clean_target, "From": TWILIO_PHONE_NUMBER, "Body": message_text}
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            res = await client.post(url, data=payload, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            print(f"📡 Background Dispatch Status: {res.status_code}")
        except Exception as e:
            print(f"❌ Non-blocking network alert exception: {e}")

async def get_realtime_weather(lga: str) -> dict:
    geo_coordinates = {
        "osogbo": {"lat": 7.7827, "lon": 4.5418}, "ile-ife": {"lat": 7.4667, "lon": 4.5667},
        "ibadan": {"lat": 7.3775, "lon": 3.9470}, "ogbomoso": {"lat": 8.1333, "lon": 4.2667}
    }
    coords = geo_coordinates.get(lga.lower().strip(), {"lat": 7.3775, "lon": 3.9470})
    url = f"https://open-meteo.com{coords['lat']}&longitude={coords['lon']}&current_weather=true"
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            res = await client.get(url)
            if res.status_code == 200:
                temp = res.json().get("current_weather", {}).get("temperature", 28.5)
                return {"temp": f"{temp}°C", "desc": "Optimal Growth" if 22 <= temp <= 32 else "Monitor Hydration"}
        except Exception: pass
    return {"temp": "28.5°C", "desc": "Optimal Conditions"}

def authenticate_admin(credentials: HTTPBasicCredentials = Depends(security)):
    input_hash = hashlib.sha256(credentials.password.encode()).hexdigest()
    if not (hmac.compare_digest(credentials.username, ADMIN_USERNAME) and hmac.compare_digest(input_hash, ADMIN_SECRET_HASH)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Node Credentials", headers={"WWW-Authenticate": "Basic"})
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
    target = clean_phone(phone)
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM farmers WHERE phone = ?", (target,)) as cursor:
            farmer = await cursor.fetchone()
    if farmer:
        if farmer["status"] == "Pending":
            return RedirectResponse(url="/portal/login?error=Access Restricted. Awaiting verification clearance.", status_code=303)
        res = RedirectResponse(url="/portal/feed", status_code=303)
        signed_token = sign_cookie_value(target)
        res.set_cookie(key="farmer_session", value=signed_token, max_age=31536000, httponly=True, secure=False)
        return res
    return RedirectResponse(url="/portal/login?error=Phone number not recognized on network scale.", status_code=303)

@app.post("/submit-registration")
async def handle_registration(name: str = Form(...), phone: str = Form(...), city_manual: str = Form(...)):
    clean_p = clean_phone(phone)
    lookup = city_manual.strip().lower()
    geo = CITY_AUTOFILL_MAP.get(lookup, {"country": "Nigeria", "state": "Region", "lga": city_manual, "area": "General Hub"})
    unique_token = hashlib.sha256(os.urandom(24)).hexdigest()[:16]
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("""
            INSERT OR REPLACE INTO farmers (phone, name, country, state, city, lga, area, token, status, xp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', 100)
        """, (clean_p, sanitize(name), geo["country"], geo["state"], sanitize(city_manual), geo["lga"], geo["area"], unique_token))
        await conn.commit()
    return HTMLResponse(content=f"""
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{UPGRADED_CSS}</style></head>
    <body><div class="glass-panel" style="max-width: 550px; margin: 60px auto; text-align: center;">
        <div style="font-size: 56px; margin-bottom: 20px;">⏳</div><span class="badge badge-amber pulse" style="margin-bottom: 16px;">Node Profile Cryptographed</span>
        <h2 style="margin: 0 0 12px 0; font-size: 28px; font-weight: 800;">Awaiting Infrastructure Clearance</h2>
        <p style="color: var(--text-muted); line-height: 1.6; font-size: 15px; margin-bottom: 30px;">
            Thank you, <b>{sanitize(name)}</b>. Your tactical node has been securely mapped under the <span style="color: #fff; font-weight: 600;">{geo['lga']} Grid Sector</span>.
        </p>
        <a href="/" class="btn" style="background: rgba(255,255,255,0.05); color: #cbd5e1; border: 1px solid var(--border-glass); width: 100%; box-sizing: border-box;">Return to Main Terminal Gateway</a>
    </div></body></html>""")

UPGRADED_CSS = """
    :root {
        --bg-slate: #020617; --panel-glass: rgba(15, 23, 42, 0.75); --border-glass: rgba(255, 255, 255, 0.08);
        --accent-emerald: #10b981; --accent-blue: #3b82f6; --accent-amber: #f59e0b;
        --text-main: #f8fafc; --text-muted: #94a3b8;
    }
    body { font-family: sans-serif; background: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #020617 70%); color: var(--text-main); margin: 0; padding: 40px 20px; min-height: 100vh; box-sizing: border-box; }
    .container { max-width: 1100px; margin: 0 auto; width: 100%; }
    .glass-panel { background: var(--panel-glass); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); border: 1px solid var(--border-glass); border-radius: 24px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); padding: 40px; box-sizing: border-box; }
    .badge { display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: 9999px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
    .badge-amber { background: rgba(245, 158, 11, 0.1); color: var(--accent-amber); border: 1px solid rgba(245, 158, 11, 0.2); }
    .badge-emerald { background: rgba(16, 185, 129, 0.1); color: var(--accent-emerald); border: 1px solid rgba(16, 185, 129, 0.2); }
    .badge-blue { background: rgba(59, 130, 246, 0.1); color: var(--accent-blue); border: 1px solid rgba(59, 130, 246, 0.2); }
    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 12px 24px; border-radius: 12px; font-weight: 700; text-decoration: none; cursor: pointer; border: none; transition: all 0.2s ease; font-size: 14px; }
    .btn-emerald { background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; box-shadow: 0 4px 14px rgba(16,185,129,0.3); }
    .btn-danger { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
    .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; margin: 30px 0; }
    .stat-card { background: rgba(255,255,255,0.02); border: 1px solid var(--border-glass); border-radius: 16px; padding: 24px; }
    .data-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
    .data-table th { padding: 14px; color: var(--text-muted); font-size: 12px; text-transform: uppercase; border-bottom: 1px solid var(--border-glass); text-align: left; }
    .data-table td { padding: 16px 14px; font-size: 14px; border-bottom: 1px solid rgba(255,255,255,0.02); text-align: left; }
    input[type="text"], select { width: 100%; padding: 14px; background: #090d16; border: 1px solid var(--border-glass); color: white; border-radius: 12px; box-sizing: border-box; }
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
        v_tag = f'<div style="margin-top:8px;"><a href="/media/{a["video_path"]}" target="_blank" style="color:var(--accent-blue); font-size:12px; font-weight:700;">📂 View Attached Clip Evidence</a></div>' if a['video_path'] else ''
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
    total_nodes = len(all_farmers)
    pending_clearance = sum(1 for f in all_farmers if f['status'] == 'Pending')
    active_threats = len(active_alerts)
    pulse_class = "pulse" if pending_clearance > 0 else ""
    map_nodes_js = ",".join([f"{{name:'{f['name']}', lga:'{f['lga']}', status:'{f['status']}'}}" for f in all_farmers if f['status'] == 'Approved'])
    map_threats_js = ",".join([f"{{type:'{a['type']}', lga:'{a['lga']}'}}" for a in active_alerts])
    pending_html = ""
    for f in all_farmers:
        if f['status'] == 'Pending':
            pending_html += f"""
            <tr>
                <td style="font-weight: 600; color: #fff;">{f['name']}</td>
                <td style="font-family: monospace; color: var(--text-muted);">{f['phone']}</td>
                <td><span class="badge badge-blue">{f['lga']}</span></td>
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
    pending_table = f'<div style="overflow-x: auto;"><table class="data-table"><thead><tr><th>Node Name</th><th>Phone</th><th>Sector</th><th>Actions</th></tr></thead><tbody>{pending_html}</tbody></table></div>' if pending_clearance > 0 else '<p style="color: var(--text-muted); font-style: italic; margin: 0; font-size: 14px;">No new registrations awaiting clearance.</p>'
    active_table = f'<div style="overflow-x: auto;"><table class="data-table"><thead><tr><th>Node Name</th><th>Phone Address</th><th>Geographic Network Path</th><th>Status</th><th>Management</th></tr></thead><tbody>{active_nodes_html}</tbody></table></div>' if active_nodes_html else '<p style="color: var(--text-muted); font-style: italic; text-align: center;">No active nodes operating on current security grid.</p>'
    return f"""
    <html>
    <head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{UPGRADED_CSS} .map-container {{ background: #040814; border: 1px solid var(--border-glass); border-radius: 20px; padding: 20px; margin-bottom: 30px; position: relative; overflow: hidden; }} .grid-bg {{ stroke: rgba(59, 130, 246, 0.05); stroke-width: 1; fill: none; }} .map-dot {{ transition: all 0.5s ease; cursor: pointer; }} .map-pulse {{ animation: map-pulse-ring 1.5s infinite ease-out; transform-origin: center; }} @keyframes map-pulse-ring {{ 0% {{ r: 6; opacity: 1; }} 100% {{ r: 25; opacity: 0; }} }}</style></head>
    <body>
        <div class="container">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-glass); padding-bottom: 24px; flex-wrap: wrap; gap: 15px;">
                <div><h1>📡 Global Command Control</h1><p style="margin: 4px 0 0 0; color: var(--text-muted); font-size: 14px;">Farm Watch Security Operations Matrix</p></div>
                <div style="display: flex; gap: 10px; align-items: center;">
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
            <div class="glass-panel" style="padding: 30px;"><h3>🗂️ Active Grid Infrastructure Map</h3>{active_table}</div>
        </div>
        <script>
            const container = document.getElementById('live_threat_feed_target');
            const geographicSectorCoordinates = {{"OSOGBO": {{x: 150, y: 220}}, "ILE-IFE": {{x: 280, y: 240}}, "IBADAN": {{x: 110, y: 140}}, "OGBOMOSO": {{x: 180, y: 80}}, "KANO MUNICIPAL": {{x: 620, y: 70}}, "FAGGE": {{x: 740, y: 90}}, "IKEJA": {{x: 450, y: 260}}, "LEKKI": {{x: 520, y: 280}}}};
            function renderTacticalVectorMap() {{ const layer = document.getElementById('map_hardware_layer'); if(!layer) return; layer.innerHTML = ""; const deploymentNodes = [{map_nodes_js}], operationalThreats = [{map_threats_js}]; operationalThreats.forEach(t => {{ const p = geographicSectorCoordinates[t.lga.toUpperCase()] || {{x: 350, y: 160}}; layer.innerHTML += `<circle cx="${{p.x}}" cy="${{p.y}}" r="8" fill="rgba(239, 68, 68, 0.4)" class="map-pulse"/><circle cx="${{p.x}}" cy="${{p.y}}" r="5" fill="#ef4444" class="map-dot"/>`; }}); deploymentNodes.forEach(n => {{ const k = n.lga.toUpperCase(), p = geographicSectorCoordinates[k] || {{x: 350, y: 160}}; if (!operationalThreats.some(t => t.lga.toUpperCase() === k)) {{ layer.innerHTML += `<circle cx="${{p.x}}" cy="${{p.y}}" r="6" fill="#10b981" class="map-dot"/><text x="${{p.x + 10}}" y="${{p.y + 4}}" fill="#94a3b8" font-size="10" font-family="monospace">${{n.lga}}</text>`; }} }}); }}
            async function pullLiveThreatStream() {{ try {{ const e = await fetch('/admin/threats/stream'); if (200 === e.status && container) {{ const t = await e.text(); if (container.innerHTML !== t) {{ container.innerHTML = t; renderTacticalVectorMap(); }} }} }} catch (err) {{ console.error(err); }} }}
            setInterval(pullLiveThreatStream, 2000); window.onload = () => {{ pullLiveThreatStream(); renderTacticalVectorMap(); }};
        </script>
    </body></html>"""
@app.get("/register", response_class=HTMLResponse)
def registration_form():
    return f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>{UPGRADED_CSS}</style></head><body><div class='glass-panel' style='max-width: 480px; margin: 40px auto;'><h2>Register Security Node</h2><form action='/submit-registration' method='post'><label>Farmer Full Name</label><input type='text' name='name' required><label>Mobile Phone Number</label><input type='text' name='phone' placeholder='e.g. 23480...' required><label>Target Town / City</label><input type='text' name='city_manual' placeholder='e.g. Osogbo' required><br><br><button type='submit' class='btn btn-emerald' style='width:100%;'>Complete Grid Entry</button></form></div></body></html>"

@app.get("/admin/export-ledger")
async def admin_export_ledger(username: str = Depends(authenticate_admin)):
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM alerts_log") as cursor:
            logs = await cursor.fetchall()
    csv_data = "Timestamp,Type,Sender,District,Message,Status\n"
    for log in logs: csv_data += f"\"{log['timestamp']}\",\"{log['type']}\",\"{log['sender']}\",\"{log['lga']}\",\"{log['message']}\",\"{log['status']}\"\n"
    return StreamingResponse(iter([csv_data]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=ledger.csv"})

@app.get("/portal/login", response_class=HTMLResponse)
def farmer_login_page(error: str = None):
    err_msg = f"<p style='color:#ef4444;'>{error}</p>" if error else ""
    return f"<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>{UPGRADED_CSS}</style></head><body><div class='glass-panel' style='max-width:400px; margin:80px auto;'><h2>Member Authentication</h2>{err_msg}<form action='/portal/auth' method='post'><label>Registered Phone Number</label><input type='text' name='phone' required><br><br><button type='submit' class='btn btn-blue' style='width:100%;'>Frictionless Sign In</button></form></div></body></html>"

@app.get("/portal/logout")
def handle_member_logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="farmer_session")
    return response

@app.post("/portal/approve-node")
async def handle_node_approval(target_phone: str = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user: raise HTTPException(status_code=401, detail="Unauthorized session Access")
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("UPDATE farmers SET status = 'Approved' WHERE phone = ? AND lga = ?", (clean_phone(target_phone), current_user['lga']))
        await conn.commit()
    return RedirectResponse(url="/portal/feed", status_code=303)


@app.get("/portal/feed", response_class=HTMLResponse)
async def farmer_feed_portal(current_user=Depends(get_current_farmer)):
    if not current_user: return RedirectResponse(url="/portal/login?error=Session required.", status_code=303)
    weather = await get_realtime_weather(current_user['lga'])
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

    nb_pending = "".join([f"""
        <div style='background:#1e293b; padding:16px; margin:10px 0; border-radius:12px; display:flex; justify-content:space-between; align-items:center;'>
            <div><div style='font-weight:600; color:#fff;'>{n['name']}</div><div style='font-size:12px; color:var(--text-muted);'>{mask_phone_number(n['phone'])}</div></div>
            <form action='/portal/approve-node' method='post' style='margin:0;'><input type='hidden' name='target_phone' value='{n['phone']}'><button type='submit' class='btn btn-emerald' style='padding:8px 16px; font-size:12px; border-radius:8px;'>🔒 Verify Identity</button></form>
        </div>""" for n in pending_neighbors])
    nb_approved = "".join([f"""
        <div style='padding:12px 16px; background:rgba(16,185,129,0.03); border:1px solid rgba(16,185,129,0.15); border-radius:10px; margin-bottom:8px; display:flex; align-items:center; gap:10px;'>
            🟢 <div style='flex:1;'><span style='font-weight:600; color:#f1f5f9;'>{f['name']}</span></div><span style='font-size:11px; color:var(--accent-emerald); background:rgba(16,185,129,0.1); padding:2px 8px; border-radius:4px;'>Online</span>
        </div>""" for f in approved_neighbors])

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
        .portal-card {{ background: var(--panel-glass); border: 1px solid var(--border-glass); border-radius: 20px; padding: 24px; box-shadow: 0 10px 30px -10px rgba(0,0,0,0.3); display: flex; flex-direction: column; }}
        .card-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 18px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 12px; }}
        .card-title {{ font-size: 16px; font-weight: 700; color: #fff; margin: 0; }}
        .weather-value {{ font-size: 32px; font-weight: 800; color: #fff; margin: 10px 0 5px 0; font-family: monospace; }}
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
            <div class="portal-grid">
                <div class="portal-card"><div class="card-header">🌤️ <h3 class="card-title">Local Environment Matrix</h3></div><div class="weather-value">{weather['temp']}</div><div style="color:var(--accent-blue); font-weight:600; font-size:14px;">📈 Status: {weather['desc']}</div></div>
                <div class="portal-card"><div class="card-header">👥 <h3 class="card-title">Active Neighbors ({len(approved_neighbors)})</h3></div><div style="flex:1; max-height:220px; overflow-y:auto;">{nb_approved or '<p style="color:var(--text-muted); font-size:13px; margin:0;">No active nodes nearby.</p>'}</div></div>
                <div class="portal-card"><div class="card-header">🤝 <h3 class="card-title">P2P Trust Gate</h3></div><div style="flex:1; max-height:220px; overflow-y:auto;">{nb_pending or '<p style="color:var(--text-muted); font-size:13px; margin:0;">Grid clear.</p>'}</div></div>
            </div>
            <div class="portal-grid" style="grid-template-columns: 1fr;">
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
        <div id="radar_screen" class="glass-panel" style="max-width: 550px; margin: 60px auto; text-align: center; display: none;"><div class="radar-spinner"></div><span class="badge badge-amber pulse" style="margin-bottom: 16px;">Transmission Channel Engaged</span><h2>Transmitting...</h2></div>
        <script>
            async function triggerEchoAnimation(e, aId) {{ e.preventDefault(); const btn = document.getElementById('echo_btn_' + aId); btn.disabled = true; btn.innerText = "📡 Relaying..."; try {{ const res = await fetch('/portal/alert/relay', {{ method: 'POST', body: new FormData(e.target) }}); if (res.status === 200) {{ const newXp = await res.text(); document.getElementById('grid_score_display').innerText = "⚡ " + newXp + " Grid XP"; btn.className = "btn"; btn.style.background = "#10b981"; btn.innerText = "✅ Dispatched"; }} }} catch(err) {{ console.error(err); }} }}
            function executeTransmissionSequence(e) {{ e.preventDefault(); const termCard = document.getElementById('container'), radarScreen = document.getElementById('radar_screen'); if(termCard) termCard.style.display = 'none'; radarScreen.style.display = 'block'; const form = document.getElementById('emergency_form'), formData = new FormData(form); fetch(form.action, {{ method: form.method, body: formData }}).then(() => {{ window.location.href = '/portal/feed'; }}).catch(() => {{ window.location.href = '/portal/feed'; }}); }}
        </script>
    </body></html>"""

@app.post("/portal/alert/comment")
async def farmer_post_comment(alert_id: int = Form(...), comment_text: str = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user: raise HTTPException(status_code=401, detail="Unauthorized")
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("INSERT INTO alert_comments (alert_id, author, text) VALUES (?, ?, ?)", (alert_id, current_user['name'], sanitize(comment_text)))
        await conn.commit()
    return RedirectResponse(url="/portal/feed", status_code=303)

@app.post("/portal/alert/raise")
async def farmer_raise_alert(alert_type: str = Form(...), message: str = Form(...), video_evidence: Optional[UploadFile] = File(None), current_user=Depends(get_current_farmer)):
    if not current_user: raise HTTPException(status_code=401, detail="Unauthorized")
    v_name = None
    if video_evidence and video_evidence.filename:
        v_name = f"{hashlib.md5(os.urandom(16)).hexdigest()}_{video_evidence.filename}"
        with open(os.path.join(MEDIA_DIR, v_name), "wb") as f: f.write(await video_evidence.read())
    a_type, msg = sanitize(alert_type), sanitize(message)
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("INSERT INTO alerts_log (type, sender, lga, message, status, video_path) VALUES (?, ?, ?, ?, 'Active', ?)", (a_type, current_user['name'], current_user['lga'], msg, v_name))
        await conn.commit()
    override = a_type in ["Critical Disaster", "Armed Attack"]
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        q = "SELECT phone FROM farmers WHERE status = 'Approved' AND phone != ?" if override else "SELECT phone FROM farmers WHERE status = 'Approved' AND lga = ? AND phone != ?"
        p = (current_user['phone'],) if override else (current_user['lga'], current_user['phone'])
        async with conn.execute(q, p) as cursor: targets = [r["phone"] for r in await cursor.fetchall()]
    alert_text = f"🚨 ALERT [{a_type.upper()}] from Sector [{current_user['lga']}]: {msg}"
    for phone in targets: asyncio.create_task(async_dispatch_whatsapp(phone, alert_text))
    return Response(status_code=200)

@app.post("/portal/alert/relay")
async def farmer_relay_alert(alert_id: int = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user: raise HTTPException(status_code=401, detail="Session validation failed")
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT type, sender, message, lga FROM alerts_log WHERE id = ?", (alert_id,)) as cursor: alert = await cursor.fetchone()
    new_xp = current_user['xp']
    if alert:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute("UPDATE farmers SET xp = xp + 15 WHERE phone = ?", (current_user['phone'],))
            async with conn.execute("SELECT xp FROM farmers WHERE phone = ?", (current_user['phone'],)) as res_cursor:
                res_row = await res_cursor.fetchone()
                if res_row: new_xp = res_row[0]  # <--- Extract the actual value from the row tuple
            await conn.commit()
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT phone FROM farmers WHERE status = 'Approved' AND lga = ? AND phone != ?", (alert['lga'], current_user['phone'])) as cursor: targets = [r["phone"] for r in await cursor.fetchall()]
        relay_text = f"📡 [GRID RELAY] Forwarded by {current_user['name']} | ORIGINAL ALERT [{alert['type'].upper()}] from {alert['sender']}: {alert['message']}"
        for phone in targets: asyncio.create_task(async_dispatch_whatsapp(phone, relay_text))
    return Response(content=str(new_xp), status_code=200)

@app.post("/incoming-alert")
async def handle_incoming_alert(From: str = Form(...), Body: str = Form(...)):
    sender_number = clean_phone(From.replace("whatsapp:", ""))
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM farmers WHERE phone = ? AND status = 'Approved'", (sender_number,)) as cursor: farmer = await cursor.fetchone()
    if not farmer: return Response(content="<Response></Response>", media_type="application/xml")
    alert_type, msg_lower = "General Anomaly", Body.lower()
    if "fire" in msg_lower or "flood" in msg_lower: alert_type = "Critical Disaster"
    elif "thief" in msg_lower or "intruder" in msg_lower: alert_type = "Intruder Spotted"
    elif "attack" in msg_lower or "armed" in msg_lower: alert_type = "Armed Attack"
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute("INSERT INTO alerts_log (type, sender, lga, message, status, video_path) VALUES (?, ?, ?, ?, 'Active', NULL)", (alert_type, farmer['name'], farmer['lga'], sanitize(Body)))
        await conn.commit()
    return Response(content="<Response></Response>", media_type="application/xml")


@app.get("/", response_class=HTMLResponse)
def community_homepage():
    # Public domain SVG path representing a friendly, high-visibility security badge with a plant leaf core
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
            .welcome-title {{
                margin: 5px 0 8px 0; 
                font-size: 32px; 
                font-weight: 900; 
                letter-spacing: -0.02em; 
                color: #fff;
            }}
            .subtitle {{
                color: var(--text-muted); 
                line-height: 1.6; 
                font-size: 15px; 
                margin: 0 auto 35px auto; 
                max-width: 420px;
            }}
            .action-link {{
                padding: 18px; 
                font-size: 16px; 
                font-weight: 800; 
                color: #ffffff; 
                letter-spacing: 0.01em; 
                border-radius: 14px;
                text-transform: uppercase;
                box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            }}
        </style>
    </head>
    <body>
        <div class="glass-panel" style="max-width: 520px; margin: 50px auto; text-align: center;">

            <!-- Branding Header Area -->
            <div ondblclick="window.location.href='/dashboard'" style="cursor: default; user-select: none;">
                {clean_logo_svg}
                <h1 class="welcome-title">olode.com.ng</h1>
                <span class="badge badge-emerald" style="font-size: 11px; font-weight: 800; letter-spacing: 0.05em; padding: 5px 12px;">🌾 Farm Watch Network</span>
            </div>

            <hr style="border: 0; border-top: 1px solid var(--border-glass); margin: 25px 0;">

            <!-- Simplified, Clear Language Descriptions -->
            <p class="subtitle">
                Connecting local farmers to watch over our community together, share live warnings, and protect our lands from danger.
            </p>

            <!-- Clean, Human-Friendly Buttons -->
            <div style="display: grid; gap: 16px;">
                <a href="/register" class="btn btn-emerald action-link">
                    👋 Register Your Farm Node
                </a>
                <a href="/portal/login" class="btn btn-blue action-link" style="background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.3); color: #93c5fd;">
                    👨‍🌾 Enter Member Portal
                </a>
            </div>

        </div>
    </body>
    </html>"""
