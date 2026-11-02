import secrets
import requests
from fastapi import FastAPI, Form, Response, Depends, HTTPException, status, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import database as db_engine

app = FastAPI(title="Farm Watch Production Node", version="2.1.0")
security = HTTPBasic()
db_engine.initialize_db()

# Administrative Settings Profile
ADMIN_USERNAME = "chief"
ADMIN_PASSWORD = "securepassword123"
ANDROID_GATEWAY_IP = "http://192.168.1.50:8080"
ANDROID_API_TOKEN = "YOUR_ANDROID_APP_PASSWORD_OR_TOKEN"

def mask_phone_number(phone: str) -> str:
    clean = str(phone).strip()
    if len(clean) <= 6:
        return "••••" + clean[-2:] if len(clean) > 2 else "••••"
    return f"{clean[:4]}••••{clean[-3:]}"

def send_production_alert(to_number: str, message_text: str):
    url = f"{ANDROID_GATEWAY_IP}/api/v1/sms/send"
    payload = {"phone": to_number, "message": message_text}
    headers = {"Authorization": f"Bearer {ANDROID_API_TOKEN}", "Content-Type": "application/json"}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        return res.status_code == 200
    except Exception:
        return False

def authenticate_admin(credentials: HTTPBasicCredentials = Depends(security)):
    is_user = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    is_pass = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (is_user and is_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

def get_current_farmer(farmer_session: str = Cookie(None)):
    if not farmer_session:
        return None
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(farmer_session)
    if clean_phone in db["farmers"]:
        return {"phone": clean_phone, "data": db["farmers"][clean_phone]}
    return None

@app.get("/", response_class=HTMLResponse)
def community_homepage():
    return """<html><head><title>Farm Watch - Security Network</title><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>body { font-family: sans-serif; background: #0b0f19; color: white; display: flex; justify-content: center; align-items: center; min-height: 100vh; text-align: center; } .box { background: #111827; padding: 40px; border-radius: 24px; max-width: 500px; } a { display: block; margin: 15px 0; padding: 15px; color: white; text-decoration: none; border-radius: 10px; font-weight: bold; } .b1 { background: #10b981; } .b2 { background: #3b82f6; } .b3 { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); }</style></head><body><div class="box"><h1>📡 <span>Farm Watch</span> Ecosystem</h1><p>Safeguarding local smallholder agricultural livelihoods.</p><a href="/register" class="b1">➕ Join Network (New Farm)</a><a href="/portal/login" class="b2">👩‍🌾 Enter Farmer Member Portal</a><a href="/dashboard" class="b3">🖥️ Access Admin Control Flight Center</a></div></body></html>"""

@app.get("/portal/login", response_class=HTMLResponse)
def farmer_login_page(error: str = None):
    err_box = f'<p style="color:#ef4444; font-weight:bold;">⚠️ {error}</p>' if error else ""
    return f"""<html><head><title>Login</title></head><body style="font-family:sans-serif; background:#0b0f19; color:white; display:flex; justify-content:center; align-items:center; height:100vh;"><div style="background:#111827; padding:35px; border-radius:20px; width:300px;"><h2>Member Login</h2>{err_box}<form action="/portal/auth" method="post"><label style="color:#9ca3af; font-size:12px;">PHONE NUMBER</label><input type="text" name="phone" style="width:100%; padding:10px; margin:10px 0; background:#1f2937; color:white; border:none; border-radius:5px;" required><button type="submit" style="width:100%; background:#3b82f6; color:white; padding:10px; border:none; border-radius:5px; font-weight:bold; cursor:pointer;">Secure Sign In</button></form></div></body></html>"""

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
    if not current_user:
        return RedirectResponse(url="/portal/login?error=Session expired.", status_code=303)
    f_phone, f_name, f_zone = current_user["phone"], current_user["data"]["name"], current_user["data"]["zone"]
    if current_user["data"].get("status", "Pending") == "Pending":
        return f"""<html><body style="font-family:sans-serif; background:#0b0f19; color:white; text-align:center; padding:50px;"><h2>⏳ Connection Pending</h2><p>Hello {f_name}. Please ask an approved neighbor in {f_zone} to verify your node.</p><a href="/" style="color:white;">Exit</a></body></html>"""
    db = db_engine.load_db()
    feed_html = "".join([f'<div style="background:rgba(255,255,255,0.02); padding:12px; margin:8px 0; border-radius:8px;"><div>⏱️ {i["timestamp"]} - <span style="color:#ef4444; font-weight:bold;">{i["status"]}</span></div><strong>[{i.get("type")}]</strong><br>"{i["message"]}"</div>' for i in reversed(db["alerts_log"]) if i["zone"] == f_zone])
    nb_html = "".join([f'<div style="background:rgba(59,130,246,0.05); padding:10px; margin:5px 0; border-radius:5px; display:flex; justify-content:space-between;"><span>{info["name"]} ({mask_phone_number(p)})</span><form action="/portal/approve-node" method="post"><input type="hidden" name="target_phone" value="{p}"><button type="submit" style="background:#3b82f6; color:white; border:none; padding:5px; border-radius:3px; cursor:pointer;">Verify</button></form></div>' for p, info in db["farmers"].items() if info["zone"] == f_zone and info.get("status", "Pending") == "Pending" and p != f_phone])
    return f"""<html><body style="font-family:sans-serif; background:#0b0f19; color:#e2e8f0; padding:20px;"><div style="max-width:600px; margin:0 auto; background:#111827; padding:20px; border-radius:20px;"><h2>👨‍🌾 {f_name}'s Guard Station ({f_zone})</h2><a href="/portal/logout" style="color:#9ca3af;">Exit</a><div style="background:rgba(239,68,68,0.05); padding:15px; border-radius:10px; margin:20px 0;"><h3>🚨 Broadcast Emergency Network Incident</h3><form action="/portal/alert/raise" method="post"><select name="alert_type" style="padding:8px; background:#1f2937; color:white;"><option value="Intruder Spotted">Intruder Spotted</option><option value="Critical Disaster">Critical Disaster</option></select><input type="text" name="message" placeholder="Situation details..." required><button type="submit" style="background:#ef4444; color:white; border:none; padding:8px; cursor:pointer;">Dispatch</button></form></div><h3>🤝 Verification Desk</h3>{nb_html or "<p>No neighbors waiting.</p>"}<h3>📡 Security Feed</h3>{feed_html or "<p>Quiet.</p>"}</div></body></html>"""

@app.post("/portal/alert/raise")
def farmer_raise_alert(alert_type: str = Form(...), message: str = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user: return RedirectResponse(url="/portal/login", status_code=303)
    f_phone, f_name, f_zone = current_user["phone"], current_user["data"]["name"], current_user["data"]["zone"]
    db = db_engine.load_db()
    db_engine.archive_incident(f_name, f_zone, message, alert_type)
    override = alert_type in ["Critical Disaster", "Armed Attack"]
    targets = [p for p, d in db["farmers"].items() if p != f_phone and d.get("status") == "Approved" and (override or d["zone"] == f_zone)]
    txt = f"FARM WATCH ALERT [{alert_type.upper()}] from {f_name} ({f_zone}): {message}"
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
    n_html = "".join([f'<li>{info["name"]} ({phone}) <form action="/delete-farmer" method="post"><input type="hidden" name="phone" value="{phone}"><button type="submit">❌</button></form></li>' for phone, info in db["farmers"].items() if info['zone'] == "Zone_North"])
    s_html = "".join([f'<li>{info["name"]} ({phone}) <form action="/delete-farmer" method="post"><input type="hidden" name="phone" value="{phone}"><button type="submit">❌</button></form></li>' for phone, info in db["farmers"].items() if info['zone'] == "Zone_South"])
    al_html = "".join([f'<div>🚨 {i["type"]} ({i["zone"]}): "{i["message"]}" <form action="/resolve-alert" method="post"><input type="hidden" name="alert_id" value="{idx}"><button type="submit">Clear</button></form></div>' for idx, i in enumerate(db["alerts_log"]) if i.get("status") == "Active"])
    return f"""<html><body style="font-family:sans-serif; background:#0b0f19; color:white; padding:20px;"><h1>📡 Global Control Center</h1><p>Devices: {total} | Alarms: {active} | Settled: {resolved}</p><h3>🚨 Active Alerts</h3>{al_html or "<p>Secure.</p>"}<h3>🟢 Zone North</h3><ul>{n_html}</ul><h3>🟡 Zone South</h3><ul>{s_html}</ul></body></html>"""

@app.post("/incoming-alert")
def handle_incoming_alert(From: str = Form(...), Body: str = Form(...)):
    db = db_engine.load_db()
    sender_number = db_engine.clean_phone_number(From.replace("whatsapp:", ""))
    if sender_number not in db["farmers"] or db["farmers"][sender_number].get("status", "Pending") == "Pending":
        return Response(content="<Response></Response>", media_type="application/xml")

    sender_name = db["farmers"][sender_number]["name"]
    sender_zone = db["farmers"][sender_number]["zone"]
    alert_type, override = "General Anomaly", False
    msg_lower = Body.lower()

    if "fire" in msg_lower or "flood" in msg_lower:
        alert_type, override = "Critical Disaster", True
    elif "thief" in msg_lower or "intruder" in msg_lower:
        alert_type = "Intruder Spotted"
    elif "attack" in msg_lower or "armed" in msg_lower:
        alert_type, override = "Armed Attack", True

    db_engine.archive_incident(sender_name, sender_zone, Body, alert_type)
    targets = [p for p, d in db["farmers"].items() if p != sender_number and d.get("status") == "Approved" and (override or d["zone"] == sender_zone)]
    txt = f"FARM WATCH ALERT [{alert_type.upper()}] from {sender_name} ({sender_zone}): {Body}"
    for num in targets:
        send_production_alert(num, txt)

    return Response(content="<Response></Response>", media_type="application/xml")

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
    return """<html><body style="font-family:sans-serif; background:#0b0f19; color:white; display:flex; justify-content:center; align-items:center; height:100vh;"><div style="background:#111827; padding:35px; border-radius:20px; width:320px;"><h2>Register Node</h2><form action="/submit-registration" method="post"><label>Name</label><input type="text" name="name" style="width:100%; padding:12px; margin:10px 0; background:#1f2937; color:white; border:none;" required><br><label>Phone</label><input type="text" name="phone" style="width:100%; padding:12px; margin:10px 0; background:#1f2937; color:white; border:none;" required><br><label>Zone</label><select name="zone" style="width:100%; padding:12px; margin:10px 0; background:#1f2937; color:white;"><option value="Zone_North">Zone_North</option><option value="Zone_South">Zone_South</option></select><br><button type="submit" style="width:100%; background:#10b981; color:white; padding:12px; border:none; font-weight:bold; cursor:pointer;">Sign Up</button></form></div></body></html>"""

@app.post("/submit-registration")
def handle_registration(name: str = Form(...), phone: str = Form(...), zone: str = Form(...)):
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(phone)
    db["farmers"][clean_phone] = {"name": name, "zone": zone, "status": "Pending"}
    db_engine.save_db(db)
    return HTMLResponse(content=f"""<html><body style="font-family:sans-serif; background:#0b0f19; color:white; text-align:center; padding-top:100px;"><h2>⏳ Connection Pending</h2><p>Thank you, {name}. Your account is initialized. Ask an approved partner in {zone} to verify your node.</p><a href="/" style="color:#10b981; font-weight:bold;">Back Home</a></body></html>""")
