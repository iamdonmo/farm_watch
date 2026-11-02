import secrets
import requests
from fastapi import FastAPI, Form, Response, Depends, HTTPException, status, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import database as db_engine

app = FastAPI(title="Farm Watch Enterprise Node", version="3.1.0")
security = HTTPBasic()
db_engine.initialize_db()

ADMIN_USERNAME = "chief"
ADMIN_PASSWORD = "securepassword123"
ANDROID_GATEWAY_IP = "http://192.168.1.50:8080"
ANDROID_API_TOKEN = "YOUR_ANDROID_APP_PASSWORD_OR_TOKEN"

# 🔔 SYSTEM ADMINISTRATIVE ALERT WEBHOOK (Slack / Discord incoming URL layout channel)
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
            "Ile-Ife": ["Ife Central Town", "Modakeke Border", "University Outpost"],
            "Ilesa": ["Ilesa East Sector", "Ilesa West Farm Ring", "Ijebu-Jesa Road"],
            "Ede": ["Ede South Agrarian", "Timi Market Node", "Federal Poly Outskirt"]
        },
        "Oyo": {
            "Ibadan": ["Ido Farming Grid", "Oluyole Frontier", "Lagelu Outpost Area"],
            "Ogbomoso": ["Ogbomoso North LAUTECH", "Ogbomoso South Central", "Ajawa Sector"],
            "Iseyin": ["Iseyin-Okeogun Central", "Ado-Awaye Route", "Agrarian North"],
            "Saki": ["Saki West Grid", "Saki East Valley", "Oke-Ogun Boundary Ring"]
        }
    },
    "Ghana": {
        "Greater Accra": {
            "Accra Metropolitan": ["Osu Node", "Labadi Sector", "Jamestown"],
            "Tema Metropolitan": ["Tema Community 1", "Tema Harbour"]
        }
    }
}
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
    """Fires a background thread JSON notification packet to the designated supervisor channel."""
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
    body { font-family: sans-serif; background: radial-gradient(circle at 10% 20%, #0f172a 0%, #020617 90%); color: #f8fafc; margin: 0; padding: 0; min-height: 100vh; display: flex; justify-content: center; align-items: center; box-sizing: border-box; }
    .glass-panel { background: rgba(15, 23, 42, 0.65); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 24px; box-shadow: 0 20px 50px rgba(0,0,0,0.4); }
    .btn { display: inline-flex; align-items: center; justify-content: center; padding: 12px 24px; border-radius: 12px; font-weight: 700; text-decoration: none; cursor: pointer; border: none; transition: 0.2s; font-size: 14px; text-align: center; }
    .btn-emerald { background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; }
    .btn-blue { background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%); color: white; }
    input, select { width:100%; padding:11px; background:#020617; border: 1px solid rgba(255,255,255,0.1); color:white; border-radius:8px; box-sizing:border-box; margin-bottom:15px; }
"""

@app.get("/", response_class=HTMLResponse)
def community_homepage():
    return f"""<html><head><style>{CORE_CSS}</style></head><body><div class="hero glass-panel" style="max-width: 500px; text-align: center; padding: 40px;"><h1>📡 Farm Watch Ecosystem</h1><p style="color: #94a3b8; margin-bottom: 30px;">Next-generation georeferenced multi-tenant network.</p><div style="display:flex; flex-direction:column; gap:12px;"><a href="/register" class="btn btn-emerald">➕ Register Operational Node</a><a href="/portal/login" class="btn btn-blue">👩‍🌾 Member Authentication Portal</a><a href="/dashboard" class="btn" style="background:rgba(255,255,255,0.03); color:#cbd5e1; border:1px solid rgba(255,255,255,0.1);">🖥️ Access Admin Control Center</a></div></div></body></html>"""
@app.get("/portal/login", response_class=HTMLResponse)
def farmer_login_page(error: str = None):
    err_box = f'<div style="color:#f87171; background:rgba(239,68,68,0.1); padding:10px; border-radius:6px; font-size:13px; margin-bottom:15px; font-weight:600;">⚠️ {error}</div>' if error else ""
    return f"""<html><head><style>{CORE_CSS}</style></head><body><div class="login-card glass-panel" style="padding:40px; width:100%; max-width:360px;"><h2>Member Login</h2>{err_box}<form action="/portal/auth" method="post"><label style="font-size:11px; color:#64748b; font-weight:700; display:block; margin-bottom:5px;">PHONE NUMBER</label><input type="text" name="phone" required><button type="submit" class="btn btn-blue" style="width: 100%;">Secure Sign In</button></form></div></body></html>"""

@app.post("/portal/auth")
def farmer_authentication(phone: str = Form(...)):
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(phone)
    if clean_phone in db["farmers"]:
        res = RedirectResponse(url="/portal/feed", status_code=303)
        res.set_cookie(key="farmer_session", value=clean_phone, max_age=2592000, httponly=True)
        return res
    return RedirectResponse(url="/portal/login?error=Phone number not recognized.", status_code=303)

@app.get("/portal/feed", response_class=HTMLResponse)
def farmer_feed_portal(current_user=Depends(get_current_farmer)):
    if not current_user: return RedirectResponse(url="/portal/login?error=Session expired.", status_code=303)
    f_phone, f_name, d = current_user["phone"], current_user["data"]["name"], current_user["data"]
    country, state, city, lga, area = d.get("country","?"), d.get("state","?"), d.get("city","?"), d.get("lga","?"), d.get("area","?")
    if d.get("status", "Pending") == "Pending":
        return f"""<html><head><style>{CORE_CSS}</style></head><body><div class="glass-panel" style="padding:40px; max-width:420px; text-align:center;"><h2 style="color:#eab308;">⏳ Integration Pending</h2><p style="color:#94a3b8;">Hello {f_name}. Please request an approved system administrator or neighbor inside your sector to authorize your node.</p><a href="/" class="btn" style="background:rgba(255,255,255,0.05); color:white;">Exit Terminal</a></div></body></html>"""
    db = db_engine.load_db()
    feed_html = "".join([f'<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:14px; margin-bottom:10px; border-radius:10px;"><div style="display:flex; justify-content:space-between; font-size:11px; color:#64748b;"><span>⏱️ {i["timestamp"]}</span><span style="color:#ef4444; font-weight:800;">{i["status"]}</span></div><strong style="color:#f97316; font-size:13px;">[{i.get("type")}]</strong><span style="display:block; margin:4px 0; color:#e2e8f0;">"{i["message"]}"</span><span style="font-size:11px; color:#475569;">Origin: {i["sender"]} | Branch: {i.get("area","General")}</span></div>' for i in reversed(db["alerts_log"]) if i.get("lga") == lga])
    nb_html = "".join([f'<div style="background:rgba(59,130,246,0.03); padding:12px; margin-bottom:8px; border-radius:8px; display:flex; justify-content:space-between; align-items:center;"><div><strong style="color:white; display:block;">{info["name"]}</strong><span style="font-size:12px; color:#64748b;">{mask_phone_number(p)} • Sector: {info.get("area")}</span></div><form action="/portal/approve-node" method="post" style="margin:0;"><input type="hidden" name="target_phone" value="{p}"><button type="submit" class="btn btn-blue" style="padding:6px 12px; font-size:12px;">🤝 Verify</button></form></div>' for p, info in db["farmers"].items() if info.get("lga") == lga and info.get("status", "Pending") == "Pending" and p != f_phone])
    return f"""<html><head><style>{CORE_CSS} body {{ display:block; padding:30px 20px; }} .container {{ max-width:800px; margin:0 auto; }}</style></head><body><div class="container glass-panel" style="padding:30px;"><div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,0.05); padding-bottom:15px; margin-bottom:25px;"><div><h2 style="margin:0;">👨‍🌾 Node Terminal: {f_name}</h2><span style="background:rgba(16,185,129,0.1); color:#10b981; padding:3px 8px; border-radius:5px; font-size:11px; font-weight:700;">📍 Index: {country} / {state} / {lga} / {area}</span></div><a href="/portal/logout" class="btn" style="background:rgba(239,68,68,0.1); color:#f87171;">Disconnect</a></div><div style="display:grid; grid-template-columns:1fr; gap:25px;"><div style="background:rgba(239,68,68,0.02); border:1px solid rgba(239,68,68,0.1); padding:20px; border-radius:16px;"><h3>🚨 Broadcast Emergency</h3><form action="/portal/alert/raise" method="post" style="display:flex; flex-direction:column; gap:12px;"><select name="alert_type"><option value="Intruder Spotted">Intruder Spotted</option><option value="Critical Disaster">Critical Disaster</option><option value="Armed Attack">Armed Attack</option></select><input type="text" name="message" placeholder="Situation details..." required><button type="submit" class="btn btn-emerald">📡 Dispatch Alert Matrix</button></form></div><div><h3>🤝 Peer Authentication Desk</h3>{nb_html or "<p style='color:#475569; font-size:13px;'>Clear ring.</p>"}<h3>📡 Security Feed</h3>{feed_html or "<p style='color:#475569; font-size:13px;'>Quiet sector.</p>"}</div></div></div></body></html>"""
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
    return RedirectResponse(url="/portal/feed", status_code=303)

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
    grouped_html, by_geo = "", {}
    for p, f in db["farmers"].items():
        g_key = f"{f.get('country','Unknown')} → {f.get('state','Unknown')} → {f.get('city','Unknown')} → {f.get('lga','Unknown')}"
        if g_key not in by_geo: by_geo[g_key] = []
        by_geo[g_key].append((p, f))
    for path, members in by_geo.items():
        m_list = ""
        for phone, m in members:
            b_color, action_lbl = ("#10b981", "🤝 Approve Node") if m.get("status", "Pending") == "Pending" else ("#475569", "🟢 Fully Approved")
            approve_btn = f'<form action="/admin/approve-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:{b_color}; border:none; color:white; padding:4px 8px; border-radius:4px; font-size:11px; cursor:pointer;" {"disabled" if m.get("status")=="Approved" else ""}>{action_lbl}</button></form>'
            m_list += f'<li style="display:flex; justify-content:space-between; align-items:center; padding:10px; background:rgba(255,255,255,0.01); margin-bottom:4px; border-radius:6px;"><span>👤 <strong>{m["name"]}</strong> ({m.get("area")}) <small style="color:#64748b;">{phone}</small></span><div style="display:flex; gap:8px; align-items:center;">{approve_btn}<form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:none; border:none; color:#ef4444; cursor:pointer;">❌ Delete</button></form></div></li>'
        grouped_html += f'<div style="margin-bottom:15px; border-left:3px solid #3b82f6; padding-left:10px;"><h4 style="margin:0 0 6px; color:#38bdf8; font-size:12px; text-transform:uppercase;">🗺️ {path}</h4><ul style="padding:0; margin:0; list-style:none;">{m_list}</ul></div>'
    al_html = "".join([f'<div style="background:rgba(239,68,68,0.03); border:1px solid rgba(239,68,68,0.1); padding:12px; margin-bottom:8px; border-radius:8px; display:flex; justify-content:space-between; align-items:center;"><div><strong>🚨 {i["type"]} ({i.get("lga")}):</strong> "{i["message"]}"</div><form action="/resolve-alert" method="post" style="margin:0;"><input type="hidden" name="alert_id" value="{idx}"><button type="submit" class="btn" style="background:#10b981; color:white; padding:4px 10px; font-size:11px;">Clear</button></form></div>' for idx, i in enumerate(db["alerts_log"]) if i.get("status") == "Active"])
    return f"""<html><head><style>{CORE_CSS} body {{ display:block; padding:40px 20px; }} .box {{ max-width:900px; margin:0 auto; }} .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(200px,1fr)); gap:15px; margin:20px 0; }} .card {{ padding:20px; text-align:center; }}</style></head><body><div class="box glass-panel" style="padding:30px;"><h2>📡 Global Command Dashboard</h2><div class="grid"><div class="card glass-panel" style="border-top:3px solid #10b981;"><h2>{total}</h2><small style="color:#64748b; font-weight:700;">REGISTRATIONS</small></div><div class="card glass-panel" style="border-top:3px solid #ef4444;"><h2>{active}</h2><small style="color:#64748b; font-weight:700;">ACTIVE THREATS</small></div><div class="card glass-panel" style="border-top:3px solid #3b82f6;"><h2>{resolved}</h2><small style="color:#64748b; font-weight:700;">CONTAINED</small></div></div><h2>🚨 Active Alarms Ledger</h2>{al_html or "<p style='color:#475569;'>No open alarms.</p>"}<h3>🗂️ Map Infrastructure & Central Approvals</h3>{grouped_html or "<p style='color:#475569;'>Map unmapped.</p>"}</div></body></html>"""
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
    """Allows administrators to directly approve members from the central master control desk layout."""
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
    return f"""<html><head><style>{CORE_CSS} body{{display:flex; justify-content:center; align-items:center; min-height:100vh; padding:20px;}} .reg {{ max-width:400px; width:100%; }} label{{display:block; margin:10px 0 4px; font-size:11px; font-weight:700; color:#64748b; text-transform:uppercase;}} .manual-field {{ display: none; }}</style></head><body><div class="glass-panel reg" style="padding:35px;"><h2>Register Security Node</h2><form action="/submit-registration" method="post"><label>Name</label><input type="text" name="name" required><label>Phone</label><input type="text" name="phone" required><label>Country</label><select id="c_select" name="country" onchange="updateStates()"><option value="">-- Country --</option><option value="Nigeria">Nigeria</option><option value="Ghana">Ghana</option><option value="MANUAL">Other (Type Manually)</option></select><input type="text" id="c_manual" name="country_manual" class="manual-field" placeholder="Type Country..."><label>State</label><select id="s_select" name="state" onchange="updateCities()"><option value="">-- State --</option></select><input type="text" id="s_manual" name="state_manual" class="manual-field" placeholder="Type State..."><label>City / Town</label><select id="city_select" name="city" onchange="updateLGAs()"><option value="">-- City --</option></select><input type="text" id="city_manual" name="city_manual" class="manual-field" placeholder="Type City..."><label>LGA / District</label><select id="lga_select" name="lga" onchange="updateAreas()"><option value="">-- LGA --</option></select><input type="text" id="lga_manual" name="lga_manual" class="manual-field" placeholder="Type LGA..."><label>Sector Area</label><select id="area_select" name="area"><option value="">-- Area --</option></select><input type="text" id="area_manual" name="area_manual" class="manual-field" placeholder="Type Area Sector..."><button type="submit" class="btn btn-emerald" style="width:100%; margin-top:15px;">Complete Request</button></form></div>
    <script>
        const geoDb = {str(GLOBAL_GEO_DB)};
        function toggleManual(selectId, manualId, checkValue) {{
            const el = document.getElementById(selectId); const man = document.getElementById(manualId);
            if(el.value === checkValue) {{ man.style.display = "block"; man.required = true; }} else {{ man.style.display = "none"; man.required = false; }}
        }}
        function updateStates() {{
            toggleManual("c_select", "c_manual", "MANUAL"); const c = document.getElementById("c_select").value; const s = document.getElementById("s_select");
            s.innerHTML = '<option value="">-- State --</option>'; document.getElementById("city_select").innerHTML = '<option value="">-- City --</option>';
            document.getElementById("lga_select").innerHTML = '<option value="">-- LGA --</option>'; document.getElementById("area_select").innerHTML = '<option value="">-- Area --</option>';
            if(c === "MANUAL") {{ s.options.add(new Option("Type Manually", "MANUAL")); }}
            if(c && geoDb[c]) {{ Object.keys(geoDb[c]).forEach(k => {{ s.options.add(new Option(k, k)); }}); s.options.add(new Option("Other", "MANUAL")); }}
        }}
        function updateCities() {{
            toggleManual("s_select", "s_manual", "MANUAL"); const c = document.getElementById("c_select").value; const s = document.getElementById("s_select").value; const city = document.getElementById("city_select");
            city.innerHTML = '<option value="">-- City --</option>'; document.getElementById("lga_select").innerHTML = '<option value="">-- LGA --</option>'; document.getElementById("area_select").innerHTML = '<option value="">-- Area --</option>';
            if(s === "MANUAL") {{ city.options.add(new Option("Type Manually", "MANUAL")); }}
            if(c && s && geoDb[c][s]) {{ Object.keys(geoDb[c][s]).forEach(k => {{ city.options.add(new Option(k, k)); }}); city.options.add(new Option("Other", "MANUAL")); }}
        }}
        function updateLGAs() {{
            toggleManual("city_select", "city_manual", "MANUAL"); const c = document.getElementById("c_select").value; const s = document.getElementById("s_select").value; const city = document.getElementById("city_select").value; const lga = document.getElementById("lga_select");
            lga.innerHTML = '<option value="">-- LGA --</option>'; document.getElementById("area_select").innerHTML = '<option value="">-- Area --</option>';
            if(city === "MANUAL") {{ lga.options.add(new Option("Type Manually", "MANUAL")); }}
            if(c && s && city && geoDb[c][s][city]) {{ Object.keys(geoDb[c][s][city]).forEach(k => {{ lga.options.add(new Option(k, k)); }}); lga.options.add(new Option("Other", "MANUAL")); }}
        }}
        function updateAreas() {{
            toggleManual("lga_select", "lga_manual", "MANUAL"); const c = document.getElementById("c_select").value; const s = document.getElementById("s_select").value; const city = document.getElementById("city_select").value; const lga = document.getElementById("lga_select").value; const area = document.getElementById("area_select");
            area.innerHTML = '<option value="">-- Area --</option>';
            if(lga === "MANUAL") {{ area.options.add(new Option("Type Manually", "MANUAL")); toggleManual("area_select", "area_manual", "MANUAL"); }}
            if(c && s && city && lga && geoDb[c][s][city][lga]) {{ geoDb[c][s][city][lga].forEach(v => {{ area.options.add(new Option(v, v)); }}); area.options.add(new Option("Other", "MANUAL")); }}
            toggleManual("area_select", "area_manual", "MANUAL");
        }}
        document.getElementById("area_select").onchange = function() {{ toggleManual("area_select", "area_manual", "MANUAL"); }};
    </script></body></html>"""


@app.post("/submit-registration")
def handle_registration(name: str = Form(...), phone: str = Form(...), country: str = Form(...), state: str = Form(...),
                        city: str = Form(...), lga: str = Form(...), area: str = Form(...),
                        country_manual: str = Form(None), state_manual: str = Form(None), city_manual: str = Form(None),
                        lga_manual: str = Form(None), area_manual: str = Form(None)):
    is_custom = "MANUAL" in [country, state, city, lga, area]
    c = country_manual if country == "MANUAL" else country
    s = state_manual if state == "MANUAL" else state
    ci = city_manual if city == "MANUAL" else city
    lg = lga_manual if lga == "MANUAL" else lga
    ar = area_manual if area == "MANUAL" else area

    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(phone)
    db["farmers"][clean_phone] = {"name": name, "country": c, "state": s, "city": ci, "lga": lg, "area": ar, "zone": lg,
                                  "status": "Pending"}
    db_engine.save_db(db)

    if is_custom:
        webhook_payload = {
            "text": f"🚧 *CUSTOM REGISTRATION RADAR*: New user *{name}* ({phone}) just signed up outside index map. Mapped Context: {c} -> {s} -> {lg}."}
        send_admin_webhook(webhook_payload)

    return HTMLResponse(
        content=f"""<html><body style="font-family:sans-serif; background:#020617; color:white; text-align:center; padding-top:100px;"><div class="glass-panel" style="display:inline-block; padding:40px; max-width:420px;"><h2 style="color:#eab308; margin-top:0;">⏳ Operational Node Active</h2><p style="color:#94a3b8;">Thank you, {name}. Your account is mapped under the <strong>{lg} Sector</strong>. Your terminal registration is under administrative trace review.</p><a href="/" class="btn btn-emerald" style="margin-top:15px;">Back Home</a></div></body></html>""")
