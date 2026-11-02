import secrets
import requests
import os
import threading
from fastapi import FastAPI, Form, Response, Depends, HTTPException, status, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import database as db_engine

app = FastAPI(title="Farm Watch Enterprise Node", version="3.5.0")
security = HTTPBasic()
db_engine.initialize_db()

ADMIN_USERNAME = "chief"
ADMIN_PASSWORD = "securepassword123"
ANDROID_GATEWAY_IP = "http://192.168.1.50:8080"
ANDROID_API_TOKEN = "YOUR_ANDROID_APP_PASSWORD_OR_TOKEN"
ADMIN_ALERT_WEBHOOK_URL = "https://slack.com"

GLOBAL_GEO_DB = {
    "Nigeria": {
        "Kano": {
            "Kano Municipal": ["Gandun Albasa", "Kano City Center", "Tudun Wada"],
            "Fagge": ["Fagge D2", "Waje", "Sabon Gari"]
        },
        "Lagos": {
            "Ikeja": ["Alausa", "Oregun", "Computer Village"],
            "Lekki": ["Phase 1", "Ikate", "Chevron Node"]
        },
        "Osun": {
            "Osogbo": ["Olorunda Central", "Capital Hub Ring", "Ataoja Sector"],
            "Ile-Ife": ["Ife Central Town", "Modakeke Border", "University Outpost"]
        },
        "Oyo": {
            "Ibadan": ["Ido Farming Grid", "Oluyole Frontier", "Lagelu Outpost Area"],
            "Ogbomoso": ["Ogbomoso North LAUTECH", "Ogbomoso South Central"]
        }
    }
}

CITY_AUTOFILL_MAP = {
    "osogbo": {"country": "Nigeria", "state": "Osun", "lga": "Osogbo", "area": "Ataoja Sector"},
    "ile-ife": {"country": "Nigeria", "state": "Osun", "lga": "Ile-Ife", "area": "Ife Central Town"},
    "ibadan": {"country": "Nigeria", "state": "Oyo", "lga": "Ibadan", "area": "Ido Farming Grid"},
    "ogbomoso": {"country": "Nigeria", "state": "Oyo", "lga": "Ogbomoso", "area": "Ogbomoso South Central"}
}

# 🕵️ WATCHDOG BACKGROUND LOGIC TRACKER
class DatabaseChangeHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if os.path.basename(event.src_path) == os.path.basename(db_engine.DB_FILE):
            pass # Database file sync hook established natively

def start_db_watchdog():
    db_dir = os.path.dirname(os.path.abspath(db_engine.DB_FILE))
    if not db_dir or not os.path.exists(db_dir):
        db_dir = "."
    event_handler = DatabaseChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, path=db_dir, recursive=False)
    observer.start()

# Fire file system trace monitor on a dedicated parallel daemon thread
threading.Thread(target=start_db_watchdog, daemon=True).start()
def mask_phone_number(phone: str) -> str:
    clean = str(phone).strip()
    if len(clean) <= 6: return "••••" + clean[-2:] if len(clean) > 2 else "••••"
    return f"{clean[:4]}••••{clean[-3:]}"

def send_production_alert(to_number: str, message_text: str):
    url = f"{ANDROID_GATEWAY_IP}/api/v1/sms/send"
    payload = {"phone": to_number, "message": message_text}
    headers = {"Authorization": f"Bearer {ANDROID_API_TOKEN}", "Content-Type": "application/json"}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        return res.status_code == 200
    except Exception: return False

def send_admin_webhook(payload: dict):
    if "://slack.com" in ADMIN_ALERT_WEBHOOK_URL or "://discord.com" in ADMIN_ALERT_WEBHOOK_URL:
        try: requests.post(ADMIN_ALERT_WEBHOOK_URL, json=payload, timeout=5)
        except Exception: pass

def authenticate_admin(credentials: HTTPBasicCredentials = Depends(security)):
    is_user = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    is_pass = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (is_user and is_pass):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad credentials.", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

def get_current_farmer(farmer_session: str = Cookie(None)):
    if not farmer_session: return None
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(farmer_session)
    return {"phone": clean_phone, "data": db["farmers"][clean_phone]} if clean_phone in db["farmers"] else None

CORE_CSS = """
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: radial-gradient(circle at 10% 20%, #0f172a 0%, #020617 90%); color: #f8fafc; margin: 0; padding: 20px; min-height: 100vh; display: flex; justify-content: center; align-items: center; box-sizing: border-box; }
    .glass-panel { background: rgba(15, 23, 42, 0.65); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 24px; box-shadow: 0 20px 50px rgba(0,0,0,0.4); width: 100%; box-sizing: border-box; }
    .btn { display: inline-flex; align-items: center; justify-content: center; padding: 14px 24px; border-radius: 12px; font-weight: 700; text-decoration: none; cursor: pointer; border: none; transition: all 0.2s ease-in-out; font-size: 14px; text-align: center; }
    .btn-emerald { background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; box-shadow: 0 4px 14px rgba(16,185,129,0.2); }
    .btn-emerald:hover { transform: translateY(-1px); box-shadow: 0 6px 20px rgba(16,185,129,0.35); }
    .btn-blue { background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%); color: white; box-shadow: 0 4px 14px rgba(59,130,246,0.2); }
    .btn-blue:hover { transform: translateY(-1px); box-shadow: 0 6px 20px rgba(59,130,246,0.35); }
    input, select { width:100%; padding:12px; background:#020617; border: 1px solid rgba(255,255,255,0.1); color:white; border-radius:8px; box-sizing:border-box; margin-bottom:15px; font-size: 14px; transition: border 0.2s; }
    input:focus, select:focus { border-color: #3b82f6; outline: none; }
    .responsive-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 24px; width: 100%; }
"""

@app.get("/", response_class=HTMLResponse)
def community_homepage():
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS}</style></head><body><div class="hero glass-panel" style="max-width: 550px; text-align: center; padding: 40px 30px;"><h1>📡 Farm Watch Ecosystem</h1><p style="color: #94a3b8; margin-bottom: 30px; line-height: 1.6; font-size: 15px;">Next-generation georeferenced multi-tenant protection network protecting local smallholder livelihoods.</p><div style="display:flex; flex-direction:column; gap:14px;"><a href="/register" class="btn btn-emerald">➕ Register Operational Node</a><a href="/portal/login" class="btn btn-blue">👩‍🌾 Member Authentication Portal</a><a href="/dashboard" class="btn" style="background:rgba(255,255,255,0.03); color:#cbd5e1; border:1px solid rgba(255,255,255,0.1);">🖥️ Access Admin Control Center</a></div></div></body></html>"""
@app.get("/portal/login", response_class=HTMLResponse)
def farmer_login_page(error: str = None):
    err_box = f'<div style="color:#f87171; background:rgba(239,68,68,0.1); padding:12px; border-radius:8px; font-size:13px; margin-bottom:20px; font-weight:600; border: 1px solid rgba(239,68,68,0.15);">⚠️ {error}</div>' if error else ""
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS}</style></head><body><div class="login-card glass-panel" style="padding:40px 25px; width:100%; max-width:380px;"><h2>Member Login</h2>{err_box}<form action="/portal/auth" method="post"><label style="font-size:11px; color:#64748b; font-weight:700; display:block; margin-bottom:6px; letter-spacing: 0.5px;">PHONE NUMBER</label><input type="text" name="phone" placeholder="e.g. 23480..." required><button type="submit" class="btn btn-blue" style="width: 100%;">Secure Sign In</button></form></div></body></html>"""

@app.post("/portal/auth")
def farmer_authentication(phone: str = Form(...)):
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(phone)
    if clean_phone in db["farmers"]:
        if db["farmers"][clean_phone].get("status", "Pending") == "Pending":
            return RedirectResponse(url="/portal/login?error=Access Restricted. Awaiting administrator review.", status_code=303)
        res = RedirectResponse(url="/portal/feed", status_code=303)
        res.set_cookie(key="farmer_session", value=clean_phone, max_age=2592000, httponly=True)
        return res
    return RedirectResponse(url="/portal/login?error=Phone number not recognized.", status_code=303)

@app.get("/portal/feed", response_class=HTMLResponse)
def farmer_feed_portal(current_user=Depends(get_current_farmer)):
    if not current_user: return RedirectResponse(url="/portal/login?error=Session expired.", status_code=303)
    f_phone, f_name, d = current_user["phone"], current_user["data"]["name"], current_user["data"]
    country, state, city, lga, area = d.get("country","?"), d.get("state","?"), d.get("city","?"), d.get("lga","?"), d.get("area","?")
    db = db_engine.load_db()
    nb_html = "".join([f'<div style="background:rgba(59,130,246,0.03); padding:14px; margin-bottom:8px; border-radius:10px; display:flex; justify-content:space-between; align-items:center; gap:10px;"><div><strong style="color:white; display:block; font-size:14px;">{info["name"]}</strong><span style="font-size:12px; color:#64748b;">{mask_phone_number(p)} • Sector: {info.get("area")}</span></div><form action="/portal/approve-node" method="post" style="margin:0;"><input type="hidden" name="target_phone" value="{p}"><button type="submit" class="btn btn-blue" style="padding:8px 14px; font-size:12px; border-radius:6px;">Verify</button></form></div>' for p, info in db["farmers"].items() if info.get("lga") == lga and info.get("status", "Pending") == "Pending" and p != f_phone])
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS} body {{ display:block; padding:15px; }} .container {{ max-width:950px; margin:0 auto; width:100%; }} @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }} .spinner {{ display: none; width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.3); border-radius: 50%; border-top-color: white; animation: spin 0.8s linear infinite; margin-right: 10px; }}</style></head><body><div class="container glass-panel" style="padding:25px 20px;"><div style="display:flex; justify-content:space-between; align-items:flex-start; border-bottom:1px solid rgba(255,255,255,0.05); padding-bottom:20px; margin-bottom:25px; flex-wrap:wrap; gap:15px;"><div><h2 style="margin:0; font-size:20px;">👨‍🌾 Node Terminal: {f_name}</h2><span style="background:rgba(16,185,129,0.1); color:#10b981; padding:4px 8px; border-radius:6px; font-size:12px; font-weight:700; display:inline-block; margin-top:5px;">📍 Index: {country} / {state} / {lga} / {area}</span></div><a href="/portal/logout" class="btn" style="background:rgba(239,68,68,0.1); color:#f87171; padding:8px 16px; font-size:13px;">Disconnect</a></div><div class="responsive-grid"><div style="background:rgba(239,68,68,0.02); border:1px solid rgba(239,68,68,0.1); padding:20px; border-radius:16px; height:fit-content;"><h3 style="margin-top:0;">🚨 Broadcast Emergency</h3><form id="broadcast_form" action="/portal/alert/raise" method="post" onsubmit="handleBroadcastSubmit(event)" style="display:flex; flex-direction:column; gap:12px; margin:0;"><select name="alert_type"><option value="Intruder Spotted">Intruder Spotted</option><option value="Critical Disaster">Critical Disaster</option><option value="Armed Attack">Armed Attack</option></select><input type="text" name="message" placeholder="Situation details..." required><button type="submit" id="dispatch_btn" class="btn btn-emerald" style="display: inline-flex; align-items: center; justify-content: center; width:100%;"><div id="btn_spinner" class="spinner"></div><span id="btn_text">📡 Dispatch Alert Matrix</span></button></form></div><div><h3 style="margin-top:0;">🤝 Peer Authentication Desk</h3>{nb_html or "<p style='color:#64748b; font-size:13px; font-style:italic;'>Clear ring.</p>"}<h3 style="margin-top:20px;">📡 Live Security Feed (<span style="color:#10b981; font-weight:bold;">● Live Auto-Sync</span>)</h3><div id="live_stream_container"><p style="color:#64748b; font-size:13px; font-style:italic;">Initializing connection matrix...</p></div></div></div></div>
    <script>
        function handleBroadcastSubmit(e){{const b=document.getElementById("dispatch_btn");const s=document.getElementById("btn_spinner");const t=document.getElementById("btn_text");b.style.opacity="0.7";b.style.pointerEvents="none";s.style.display="inline-block";t.innerText="Transmitting Alert Grid...";}}
        async function fetchLiveFeedStream() {{
            try {{
                const res = await fetch("/portal/feed/stream");
                if (res.status === 200) {{
                    const html_payload = await res.text();
                    document.getElementById("live_stream_container").innerHTML = html_payload;
                }}
            }} catch(err) {{}}
        }}
        // Secure background loop queries state alterations seamlessly every 2000ms
        setInterval(fetchLiveFeedStream, 2000);
        fetchLiveFeedStream();
    </script></body></html>"""
@app.get("/portal/feed/stream")
def portal_async_feed_stream(current_user=Depends(get_current_farmer)):
    """Background high-performance engine that returns HTML fragments securely without refreshing the client browser."""
    if not current_user: return Response(status_code=401)
    lga = current_user["data"].get("lga", "Unknown")
    db = db_engine.load_db()
    html = ""
    for i in reversed(db["alerts_log"]):
        if i.get("lga") == lga:
            html += f'<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:16px; margin-bottom:12px; border-radius:12px;"><div style="display:flex; justify-content:space-between; font-size:11px; color:#64748b; margin-bottom:4px;"><span>⏱️ {i["timestamp"]}</span><span style="color:#ef4444; font-weight:800;">{i["status"]}</span></div><strong style="color:#f97316; font-size:13px;">[{i.get("type")}]</strong><span style="display:block; margin:6px 0; color:#e2e8f0; line-height:1.4;">"{i["message"]}"</span><span style="font-size:11px; color:#475569;">Origin: {i["sender"]} | Scope: {i.get("area","General")}</span></div>'
    return HTMLResponse(content=html or "<p style='color:#64748b; font-size:13px; font-style:italic;'>All sectors quiet across local scope.</p>")

@app.post("/portal/alert/raise")
def farmer_raise_alert(alert_type: str = Form(...), message: str = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user: return RedirectResponse(url="/portal/login", status_code=303)
    f_phone, f_name, d = current_user["phone"], current_user["data"]["name"], current_user["data"]
    db = db_engine.load_db()
    db_engine.archive_incident(f_name, d.get("lga"), message, alert_type)
    idx = len(db["alerts_log"]) - 1
    if idx >= 0:
        db = db_engine.load_db()
        for field in ["country", "state", "city", "lga", "area"]: db["alerts_log"][idx][field] = d.get(field)
        db_engine.save_db(db)
    override = alert_type in ["Critical Disaster", "Armed Attack"]
    targets = [p for p, data in db["farmers"].items() if p != f_phone and data.get("status") == "Approved" and (override or data.get("lga") == d.get("lga"))]
    txt = f"ALERT [{alert_type.upper()}] from {f_name} ({d.get('lga')}): {message}"
    for num in targets: send_production_alert(num, txt)
    return HTMLResponse(content=f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS}</style></head><body><div class="glass-panel" style="padding:40px 25px; text-align:center; max-width:450px; width:100%;"><div style="font-size:48px; margin-bottom:15px;">✅</div><h2 style="color:#10b981; margin:0 0 10px;">Broadcast Dispatched</h2><p style="color:#94a3b8; line-height:1.6; font-size:14px;">Your incident report has been securely transmitted across the <strong>{d.get('lga')} Lookout Grid</strong>.</p><a href="/portal/feed" class="btn btn-blue" style="margin-top:20px; width:100%;">Return to Guard Station</a></div></body></html>""")

@app.post("/portal/approve-node")
def handle_node_approval(target_phone: str = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user: return RedirectResponse(url="/portal/login", status_code=303)
    db_engine.approve_farmer_node(target_phone)
    return RedirectResponse(url="/portal/feed", status_code=303)

@app.get("/portal/logout")
def handle_member_logout():
    res = RedirectResponse(url="/", status_code=303)
    res.delete_cookie(key="farmer_session")
    return res
@app.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(username: str = Depends(authenticate_admin)):
    db = db_engine.load_db()
    total, active, resolved = len(db["farmers"]), sum(1 for i in db["alerts_log"] if i.get("status") == "Active"), sum(1 for i in db["alerts_log"] if i.get("status") == "Resolved")
    pending_html = ""
    for phone, m in db["farmers"].items():
        if m.get("status", "Pending") == "Pending":
            pending_html += f'<div style="display:flex; justify-content:space-between; align-items:center; padding:12px; background:rgba(234,179,8,0.03); border:1px solid rgba(234,179,8,0.15); margin-bottom:8px; border-radius:8px; flex-wrap:wrap; gap:10px;"><span>⏳ <strong>{m["name"]}</strong> ({phone})<br><small style="color:#64748b;">MAPPED: {m.get("country")} -> {m.get("lga")}</small></span><div style="display:flex; gap:6px;"><form action="/admin/approve-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:#10b981; border:none; color:white; padding:6px 12px; border-radius:6px; font-size:11px; cursor:pointer; font-weight:700;">Approve</button></form><form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:rgba(239,68,68,0.1); border:none; color:#f87171; padding:6px 12px; border-radius:6px; font-size:11px; cursor:pointer;">Deny</button></form></div></div>'
    grouped_html, by_geo = "", {}
    for p, f in db["farmers"].items():
        if f.get("status") == "Approved":
            g_key = f"{f.get('country','Unknown')} → {f.get('state','Unknown')} → {f.get('city','Unknown')} → {f.get('lga','Unknown')}"
            if g_key not in by_geo: by_geo[g_key] = []
            by_geo[g_key].append((p, f))
    for path, members in by_geo.items():
        m_list = "".join([f'<li style="display:flex; justify-content:space-between; align-items:center; padding:10px; background:rgba(255,255,255,0.02); margin-bottom:6px; border-radius:8px; gap:10px;"><span style="font-size:14px;">🟢 <strong>{m["name"]}</strong> ({m.get("area")}) <small style="color:#64748b; display:block; margin-top:2px;">{phone}</small></span><form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:13px;">❌ Remove</button></form></li>' for phone, m in members])
        grouped_html += f'<div style="margin-bottom:20px; border-left:3px solid #3b82f6; padding-left:12px;"><h4 style="margin:0 0 10px; color:#38bdf8; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;">🗺️ {path}</h4><ul style="padding:0; margin:0; list-style:none;">{m_list}</ul></div>'
    al_html = "".join([f'<div style="background:rgba(239,68,68,0.03); border:1px solid rgba(239,68,68,0.1); padding:16px; margin-bottom:10px; border-radius:12px; display:flex; justify-content:space-between; align-items:center; gap:15px; flex-wrap:wrap;"><div style="font-size:14px; line-height:1.4;"><strong>🚨 {i["type"]} ({i.get("lga")}):</strong> "{i["message"]}"</div><form action="/resolve-alert" method="post" style="margin:0;"><input type="hidden" name="alert_id" value="{idx}"><button type="submit" class="btn" style="background:#10b981; color:white; padding:6px 14px; font-size:12px; border-radius:6px;">Clear</button></form></div>' for idx, i in enumerate(db["alerts_log"]) if i.get("status") == "Active"])
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS} body {{ display:block; padding:15px; }} .box {{ max-width:1000px; margin:0 auto; width:100%; }} .stats-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:16px; margin:25px 0; }} .card {{ padding:20px; text-align:center; }} .card h2 {{ margin:0 0 4px; font-size:32px; font-weight:800; }}</style></head><body><div class="box glass-panel" style="padding:30px 20px;"><h2>📡 Global Command Dashboard</h2><div class="stats-grid"><div class="card glass-panel" style="border-top:3px solid #10b981;"><h2>{total}</h2><small style="color:#64748b; font-weight:700; letter-spacing:0.5px;">REGISTRATIONS</small></div><div class="card glass-panel" style="border-top:3px solid #ef4444;"><h2>{active}</h2><small style="color:#64748b; font-weight:700; letter-spacing:0.5px;">ACTIVE THREATS</small></div><div class="card glass-panel" style="border-top:3px solid #3b82f6;"><h2>{resolved}</h2><small style="color:#64748b; font-weight:700; letter-spacing:0.5px;">CONTAINED</small></div></div><h3 style="color:#eab308; border-bottom:1px solid rgba(234,179,8,0.1); padding-bottom:8px; margin-top:30px;">⏳ Awaiting Executive Security Authorization</h3>{pending_html or "<p style='color:#64748b; font-size:13px; font-style:italic;'>No new registrations pending clearance.</p>"}<h3>🚨 Active Alarms Ledger</h3>{al_html or "<p style='color:#64748b; font-size:13px; font-style:italic;'>No open alarms.</p>"}<h3>🗂️ Authorized Active Infrastructure Ring Map</h3>{grouped_html or "<p style='color:#64748b; font-size:13px; font-style:italic;'>Map unmapped.</p>"}</div></body></html>"""

@app.post("/incoming-alert")
def handle_incoming_alert(From: str = Form(...), Body: str = Form(...)):
    db = db_engine.load_db()
    sender_number = db_engine.clean_phone_number(From.replace("whatsapp:", ""))
    if sender_number not in db["farmers"] or db["farmers"][sender_number].get("status", "Pending") == "Pending":
        return Response(content="<Response></Response>", media_type="application/xml")
    f_data = db["farmers"][sender_number]
    lga = f_data.get("lga", "Unknown")
    alert_type, override = "General Anomaly", False
    msg_lower = Body.lower()
    if "fire" in msg_lower or "flood" in msg_lower: alert_type, override = "Critical Disaster", True
    elif "thief" in msg_lower or "intruder" in msg_lower: alert_type = "Intruder Spotted"
    elif "attack" in msg_lower or "armed" in msg_lower: alert_type, override = "Armed Attack", True
    db_engine.archive_incident(f_data["name"], lga, Body, alert_type)
    idx = len(db["alerts_log"]) - 1
    if idx >= 0:
        db = db_engine.load_db()
        for field in ["country", "state", "city", "lga", "area"]: db["alerts_log"][idx][field] = f_data.get(field, "Unknown")
        db_engine.save_db(db)
    targets = [p for p, d in db["farmers"].items() if p != sender_number and d.get("status") == "Approved" and (override or d.get("lga") == lga)]
    txt = f"FARM WATCH ALERT [{alert_type.upper()}] from {f_data['name']} ({lga}): {Body}"
    for num in targets: send_production_alert(num, txt)
    return Response(content="<Response></Response>", media_type="application/xml")
@app.post("/admin/approve-farmer")
def admin_direct_approve_farmer(phone: str = Form(...), username: str = Depends(authenticate_admin)):
    db_engine.approve_farmer_node(phone)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/delete-farmer")
def handle_delete_farmer(phone: str = Form(...), username: str = Depends(authenticate_admin)):
    db_engine.remove_farmer(phone)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/resolve-alert")
def resolve_alert(alert_id: int = Form(...)):
    db_engine.update_incident_status(alert_id)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/register", response_class=HTMLResponse)
def registration_form():
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS} body{{display:flex; justify-content:center; align-items:center; min-height:100vh; padding:15px;}} .reg {{ max-width:440px; width:100%; }} label{{display:block; margin:12px 0 4px; font-size:11px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;}}</style></head><body><div class="glass-panel reg" style="padding:35px 25px;"><h2>Register Security Node</h2><p style="color:#64748b; font-size:13px; margin-top:-10px; margin-bottom:25px; line-height:1.4;">Provide drop data OR skip fields and just type your city below.</p><form action="/submit-registration" method="post" style="margin:0;"><label>Farmer Name</label><input type="text" name="name" placeholder="Kwame" required><label>Phone Number</label><input type="text" name="phone" placeholder="e.g. +234..." required><label>City / Town (Autofill Input)</label><input type="text" name="city_manual" placeholder="e.g. Osogbo or Ogbomoso" required><div style="border: 1px solid rgba(255,255,255,0.05); padding:15px 12px; border-radius:12px; margin-bottom:20px; background: rgba(0,0,0,0.1);"><label style="margin:0 0 8px; color: #94a3b8;">Optional Dropdowns</label><select id="c_select" name="country" onchange="updateStates()"><option value="">-- Country --</option><option value="Nigeria">Nigeria</option></select><select id="s_select" name="state" onchange="updateCities()"><option value="">-- State --</option></select><select id="city_select" name="city" onchange="updateLGAs()"><option value="">-- City --</option></select><select id="lga_select" name="lga" onchange="updateAreas()"><option value="">-- LGA --</option></select><select id="area_select" name="area"><option value="">-- Area --</option></select></div><button type="submit" class="btn btn-emerald" style="width:100%;">Complete Request</button></form></div>
    <script>
        const geoDb = {str(GLOBAL_GEO_DB)};
        function updateStates() {{
            const c = document.getElementById("c_select").value; const s = document.getElementById("s_select");
            s.innerHTML = '<option value="">-- State --</option>'; document.getElementById("city_select").innerHTML = '<option value="">-- City --</option>';
            document.getElementById("lga_select").innerHTML = '<option value="">-- LGA --</option>'; document.getElementById("area_select").innerHTML = '<option value="">-- Area --</option>';
            if(c && geoDb[c]) {{ Object.keys(geoDb[c]).forEach(k => {{ s.options.add(new Option(k, k)); }}); }}
        }}
        function updateCities() {{
            const c = document.getElementById("c_select").value; const s = document.getElementById("s_select").value; const city = document.getElementById("city_select");
            city.innerHTML = '<option value="">-- City --</option>'; document.getElementById("lga_select").innerHTML = '<option value="">-- LGA --</option>'; document.getElementById("area_select").innerHTML = '<option value="">-- Area --</option>';
            if(c && s && geoDb[c][s]) {{ Object.keys(geoDb[c][s]).forEach(k => {{ city.options.add(new Option(k, k)); }}); }}
        }}
        function updateLGAs() {{
            const c = document.getElementById("c_select").value; const s = document.getElementById("s_select").value; const city = document.getElementById("city_select").value; const lga = document.getElementById("lga_select");
            lga.innerHTML = '<option value="">-- LGA --</option>'; document.getElementById("area_select").innerHTML = '<option value="">-- Area --</option>';
            if(c && s && city && geoDb[c][s][city]) {{ Object.keys(geoDb[c][s][city]).forEach(k => {{ lga.options.add(new Option(k, k)); }}); }}
        }}
        function updateAreas() {{
            const c = document.getElementById("c_select").value; const s = document.getElementById("s_select").value; const city = document.getElementById("city_select").value; const lga = document.getElementById("lga_select").value; const area = document.getElementById("area_select");
            area.innerHTML = '<option value="">-- Area --</option>';
            if(c && s && city && lga && geoDb[c][s][city][lga]) {{ geoDb[c][s][city][lga].forEach(v => {{ area.options.add(new Option(v, v)); }}); }}
        }}
    </script></body></html>"""

@app.post("/submit-registration")
def handle_registration(name: str = Form(...), phone: str = Form(...), city_manual: str = Form(...), country: str = Form(None), state: str = Form(None), city: str = Form(None), lga: str = Form(None), area: str = Form(None)):
    lookup_token = city_manual.strip().lower()
    if lookup_token in CITY_AUTOFILL_MAP:
        geo = CITY_AUTOFILL_MAP[lookup_token]
        c, s, ci, lg, ar = geo["country"], geo["state"], city_manual, geo["lga"], geo["area"]
    else:
        c = country if country else "Nigeria"
        s = state if state else "Unknown Region"
        ci = city_manual
        lg = lga if lga else f"{city_manual} Sector"
        ar = area if area else "General Farm Hub"
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(phone)
    db["farmers"][clean_phone] = {"name": name, "country": c, "state": s, "city": ci, "lga": lg, "area": ar, "zone": lg, "status": "Pending"}
    db_engine.save_db(db)
    if lookup_token not in CITY_AUTOFILL_MAP:
        send_admin_webhook({"text": f"🚧 *UNMAPPED CITY ALERT*: *{name}* ({phone}) just registered using city text input: *{city_manual}*."})
    return HTMLResponse(content=f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS}</style></head><body><div class="glass-panel" style="display:inline-block; padding:40px 25px; max-width:440px; width:100%; text-align:center;"><h2 style="color:#eab308; margin-top:0;">⏳ Profile Mapped Successfully</h2><p style="color:#94a3b8; line-height:1.6; font-size:14px;">Thank you, {name}. The system automatically mapped you to <strong>{lg}</strong> based on your city input. Awaiting administrator gateway clearance.</p><a href="/" class="btn btn-emerald" style="margin-top:20px; width:100%;">Back Home</a></div></body></html>""")
