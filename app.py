import secrets
import requests
from fastapi import FastAPI, Form, Response, Depends, HTTPException, status, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import database as db_engine

app = FastAPI()
security = HTTPBasic()

db_engine.initialize_db()

# ---------------------------------------------------------
# 🔑 CUSTOM ADMINISTRATIVE CONFIGURATION PROFILE
# ---------------------------------------------------------
ADMIN_USERNAME = "chief"
ADMIN_PASSWORD = "securepassword123"

# Local Android Gateway configuration properties
ANDROID_GATEWAY_IP = "http://192.168.1.50:8080"
ANDROID_API_TOKEN = "YOUR_ANDROID_APP_PASSWORD_OR_TOKEN"

def send_production_alert(to_number: str, message_text: str):
    """Sends a wireless command packet to your local Android Phone to fire an SMS."""
    url = f"{ANDROID_GATEWAY_IP}/api/v1/sms/send"
    payload = {"phone": to_number, "message": message_text}
    headers = {"Authorization": f"Bearer {ANDROID_API_TOKEN}", "Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        if response.status_code == 200:
            print(f"📲 [REAL SMS LOG] Transmitted text command to Android hardware: {to_number}")
            return True
    except Exception as e:
        print(f"⚠️ [SIMULATION FALLBACK] Android gateway phone offline or unmapped: {e}")
    return False

def authenticate_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Locks the central master control panel behind admin credentials."""
    is_correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    is_correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

def get_current_farmer(farmer_session: str = Cookie(None)):
    """Validates the browser cookie to check if a farmer is currently logged in."""
    if not farmer_session:
        return None
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(farmer_session)
    if clean_phone in db["farmers"]:
        return {"phone": clean_phone, "data": db["farmers"][clean_phone]}
    return None
@app.get("/", response_class=HTMLResponse)
def community_homepage():
    """Renders a responsive, dark-themed welcome dashboard gateway portal."""
    return """
    <html>
        <head>
            <title>Farm Watch - Security Network</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: linear-gradient(135deg, #0b0f19 0%, #111827 100%); color: white; margin: 0; padding: 0; display: flex; justify-content: center; align-items: center; min-height: 100vh; box-sizing: border-box; }
                .hero-container { background: #111827; border: 1px solid rgba(255, 255, 255, 0.05); padding: 40px; border-radius: 24px; max-width: 600px; width: 100%; text-align: center; box-shadow: 0 20px 40px rgba(0,0,0,0.5); }
                h1 { font-size: 36px; margin-top: 0; font-weight: 800; }
                h1 span { color: #10b981; }
                p.tagline { font-size: 16px; color: #9ca3af; margin-bottom: 35px; line-height: 1.6; }
                .action-box { display: flex; flex-direction: column; gap: 15px; }
                .btn { display: block; padding: 16px; text-decoration: none; font-weight: 700; font-size: 16px; border-radius: 12px; transition: all 0.2s; text-align: center; }
                .btn-register { background: #10b981; color: white; }
                .btn-register:hover { background: #059669; transform: translateY(-2px); }
                .btn-portal { background: #3b82f6; color: white; }
                .btn-portal:hover { background: #2563eb; transform: translateY(-2px); }
                .btn-dashboard { background: rgba(255, 255, 255, 0.05); color: white; border: 1px solid rgba(255,255,255,0.1); }
                .btn-dashboard:hover { background: rgba(255, 255, 255, 0.1); transform: translateY(-2px); }
                .footer { margin-top: 30px; font-size: 11px; color: #4b5563; text-transform: uppercase; letter-spacing: 1px; font-weight: 700; }
            </style>
        </head>
        <body>
            <div class="hero-container">
                <h1>📡 <span>Farm Watch</span> Ecosystem</h1>
                <p class="tagline">Protecting our fields together. An automated lookout grid safeguarding local smallholder agricultural livelihoods.</p>
                <div class="action-box">
                    <a href="/register" class="btn btn-register">➕ Join Network (New Farm)</a>
                    <a href="/portal/login" class="btn btn-portal">👩‍🌾 Enter Farmer Member Portal</a>
                    <a href="/dashboard" class="btn btn-dashboard">🖥️ Access Admin Control Center</a>
                </div>
                <div class="footer">Ecosystem Node Guard Active</div>
            </div>
        </body>
    </html>
    """

@app.get("/portal/login", response_class=HTMLResponse)
def farmer_login_page(error: str = None):
    """Renders the secure member authentication form card for internet-enabled farmers."""
    error_msg = f'<p style="color:#ef4444; background:rgba(239,68,68,0.1); padding:10px; border-radius:6px; text-align:center; font-size:14px; font-weight:700;">⚠️ {error}</p>' if error else ""
    return f"""
    <html>
        <head><title>Farmer Login</title><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
        <body style="font-family:sans-serif; background-color:#0b0f19; display:flex; justify-content:center; align-items:center; height:100vh; margin:0; padding:20px; box-sizing:border-box; color:white;">
            <div style="background:#111827; border:1px solid rgba(255,255,255,0.05); padding:35px; border-radius:20px; width:100%; max-width:360px; box-shadow:0 20px 40px rgba(0,0,0,0.4);">
                <h2 style="text-align:center; margin-top:0; font-weight:800;">Member Login</h2>
                {error_msg}
                <form action="/portal/auth" method="post">
                    <label style="display:block; margin-bottom:8px; font-size:12px; font-weight:700; color:#9ca3af; text-transform:uppercase;">Registered Phone Number</label>
                    <input type="text" name="phone" style="width:100%; padding:12px; margin-bottom:20px; border:1px solid rgba(255,255,255,0.1); border-radius:10px; color:white; background:#1f2937;" placeholder="e.g. +234803..." required><br>
                    <button type="submit" style="width:100%; background:#3b82f6; color:white; padding:14px; border:none; border-radius:10px; font-size:16px; font-weight:700; cursor:pointer;">Secure Sign In</button>
                </form>
                <div style="text-align:center; margin-top:20px;"><a href="/" style="color:#9ca3af; text-decoration:none; font-size:14px;">⬅️ Return Home</a></div>
            </div>
        </body>
    </html>
    """

@app.post("/portal/auth")
def farmer_authentication(phone: str = Form(...)):
    """Verifies member exists and handles session cookie injection routing."""
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(phone)
    if clean_phone in db["farmers"]:
        response = RedirectResponse(url="/portal/feed", status_code=303)
        # Sets a tracking cookie session value valid for a rolling 30-day window
        response.set_cookie(key="farmer_session", value=clean_phone, max_age=2592000, httponly=True)
        return response
    return RedirectResponse(url="/portal/login?error=Phone number not recognized on network index.", status_code=303)


@app.get("/portal/feed", response_class=HTMLResponse)
def farmer_feed_portal(current_user=Depends(get_current_farmer)):
    """Renders the secure internal look-out stream customized for the active logged-in farmer."""
    if not current_user:
        return RedirectResponse(url="/portal/login?error=Session expired. Please sign in again.", status_code=303)

    farmer_phone = current_user["phone"]
    farmer_name = current_user["data"]["name"]
    farmer_zone = current_user["data"]["zone"]
    farmer_status = current_user["data"].get("status", "Pending")

    db = db_engine.load_db()
    farmers = db["farmers"]
    alerts_log = db["alerts_log"]

    # 🌟 GATE CHECK: If a user is still pending approval, display a clean safety alert notice
    if farmer_status == "Pending":
        return f"""
        <html><body style="font-family:sans-serif; background:#0b0f19; color:white; display:flex; justify-content:center; align-items:center; height:100vh; padding:20px; box-sizing:border-box;">
            <div style="background:#111827; border:1px solid rgba(234,179,8,0.2); padding:35px; border-radius:20px; max-width:450px; text-align:center;">
                <h2 style="color:#eab308; margin-top:0; font-weight:800;">⏳ Node Connection Pending</h2>
                <p style="color:#9ca3af; line-height:1.6;">Hello <strong>{farmer_name}</strong>. Your profile has been added, but to protect against rogue entries, you must have an existing approved neighbor in <strong>{farmer_zone}</strong> log into their portal and verify your device node.</p>
                <hr style="border:0; border-top:1px solid rgba(255,255,255,0.05); margin:20px 0;">
                <a href="/" style="display:inline-block; background:rgba(255,255,255,0.05); color:white; padding:10px 20px; text-decoration:none; border-radius:8px; font-weight:700;">Logout / Exit</a>
            </div>
        </body></html>"""

    # 1. GENERATE REGIONAL FEED: Filter logs so farmers only see data matching their specific zone sector
    sector_feed_html = ""
    for item in reversed(alerts_log):
        if item["zone"] == farmer_zone:
            badge_color = "#ef4444" if item.get("type") in ["Critical Disaster",
                                                            "Armed Attack"] else "#f97316" if item.get(
                "type") == "Intruder Spotted" else "#eab308"
            status_text = "🚨 ACTIVE THREAT" if item.get("status") == "Active" else "🟢 RESOLVED / CLEAR"
            status_style = f"color:{badge_color};" if item.get("status") == "Active" else "color:#10b981;"

            sector_feed_html += f"""
            <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:16px; margin-bottom:12px; border-radius:12px;">
                <div style="display:flex; justify-content:space-between; font-size:11px; color:#6b7280; margin-bottom:6px;">
                    <span>⏱️ {item['timestamp']}</span>
                    <span style="{status_style} font-weight:800; text-transform:uppercase;">{status_text}</span>
                </div>
                <strong style="color:{badge_color}; font-size:13px; text-transform:uppercase;">[{item.get('type')}]</strong>
                <span style="font-size:15px; color:#f3f4f6; display:block; margin:6px 0;">"{item['message']}"</span>
                <span style="font-size:12px; color:#4b5563;">Broadcast Node Origin: {item['sender']}</span>
            </div>"""

    # 2. GENERATE DESK PENDING LIST: Find brand-new neighbors inside this same zone waiting for verification
    pending_neighbors_html = ""
    for phone, info in farmers.items():
        if info["zone"] == farmer_zone and info.get("status", "Pending") == "Pending" and phone != farmer_phone:
            pending_neighbors_html += f"""
            <div style="background:rgba(59,130,246,0.05); border:1px solid rgba(59,130,246,0.2); padding:14px; margin-bottom:10px; border-radius:10px; display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <strong style="color:#fff; display:block;">{info['name']}</strong>
                    <span style="font-size:12px; color:#9ca3af;">{phone}</span>
                </div>
                <form action="/portal/approve-node" method="post" style="margin:0;">
                    <input type="hidden" name="target_phone" value="{phone}">
                    <button type="submit" style="background:#3b82f6; color:white; border:none; padding:8px 12px; border-radius:6px; cursor:pointer; font-weight:700; font-size:13px;">🤝 Verify Neighbor</button>
                </form>
            </div>"""

    return f"""
    <html>
        <head><title>Farmer Lookout Room</title><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
        <body style="font-family:sans-serif; background:#0b0f19; color:#e2e8f0; padding:20px; margin:0;">
            <div style="max-width:800px; margin:0 auto; background:#111827; border:1px solid rgba(255,255,255,0.05); padding:25px; border-radius:20px;">
                <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,0.05); padding-bottom:15px; margin-bottom:25px;">
                    <div>
                        <h1 style="font-size:24px; color:#fff; margin:0;">👨‍🌾 {farmer_name}'s Guard Station</h1>
                        <span style="color:#10b981; font-weight:700; font-size:13px;">🛰️ Sector Sync Channel: {farmer_zone}</span>
                    </div>
                    <a href="/portal/logout" style="color:#9ca3af; font-size:13px; text-decoration:none; background:rgba(255,255,255,0.03); padding:6px 12px; border-radius:6px; border:1px solid rgba(255,255,255,0.05);">Exit Station</a>
                </div>

                <div style="display:grid; grid-template-columns:1fr; gap:20px;">
                    <div>
                        <h3 style="margin-top:0; border-left:4px solid #3b82f6; padding-left:10px; color:#fff;">🤝 Neighbor Trust Verification Desk</h3>
                        <p style="font-size:13px; color:#9ca3af; margin-bottom:15px;">Approve new regional signups here to authorize their emergency text privileges.</p>
                        {pending_neighbors_html or "<p style='color:#6b7280; font-style:italic; font-size:13px;'>No pending authentication files found for this zone.</p>"}
                    </div>

                    <hr style="border:0; border-top:1px solid rgba(255,255,255,0.05); margin:10px 0;">

                    <div>
                        <h3 style="margin-top:0; border-left:4px solid #10b981; padding-left:10px; color:#fff;">📡 Live Regional Security Incident Feed</h3>
                        {sector_feed_html or "<p style='color:#6b7280; font-style:italic; font-size:13px;'>All sectors reporting fully quiet.</p>"}
                    </div>
                </div>
            </div>
        </body>
    </html>
    """


@app.post("/portal/approve-node")
def handle_node_approval(target_phone: str = Form(...), current_user=Depends(get_current_farmer)):
    """Processes dynamic neighborhood token confirmations over verified channels."""
    if not current_user:
        return RedirectResponse(url="/portal/login", status_code=303)
    db_engine.approve_farmer_node(target_phone)
    print(f"\n🤝 [NEIGHBOR NODE AUTHENTICATED] Verified by team lead member session.")
    return RedirectResponse(url="/portal/feed", status_code=303)


@app.get("/portal/logout")
def handle_member_logout():
    """Wipes browser runtime memory session cookies and forces a graceful redirect home."""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="farmer_session")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(username: str = Depends(authenticate_admin)):
    """Displays comprehensive multi-node matrix maps for global control center heads."""
    db = db_engine.load_db()
    farmers = db["farmers"]
    alerts_log = db["alerts_log"]

    total_protected = len(farmers)
    active_incidents = sum(1 for item in alerts_log if item.get("status") == "Active")
    resolved_incidents = sum(1 for item in alerts_log if item.get("status") == "Resolved")

    has_critical_disaster = any(
        item.get("status") == "Active" and item.get("type") in ["Critical Disaster", "Armed Attack"] for item in
        alerts_log)

    north_zone_html = ""
    for phone, info in farmers.items():
        if info['zone'] == "Zone_North":
            badge_lbl = f"<span style='color:#10b981; font-size:11px;'>[Approved]</span>" if info.get("status",
                                                                                                      "Pending") == "Approved" else f"<span style='color:#eab308; font-size:11px;'>[Pending Approval]</span>"
            north_zone_html += f'<li style="margin-bottom:12px; background:rgba(255,255,255,0.02); padding:12px; border-radius:8px; display:flex; justify-content:space-between; align-items:center;"><div><strong>{info["name"]}</strong> {badge_lbl}<br><span style="font-size:12px; color:#9ca3af;">{phone}</span></div><form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:none; border:none; color:#f87171; cursor:pointer; font-weight:700;">❌ Remove</button></form></li>'

    south_zone_html = ""
    for phone, info in farmers.items():
        if info['zone'] == "Zone_South":
            badge_lbl = f"<span style='color:#10b981; font-size:11px;'>[Approved]</span>" if info.get("status",
                                                                                                      "Pending") == "Approved" else f"<span style='color:#eab308; font-size:11px;'>[Pending Approval]</span>"
            south_zone_html += f'<li style="margin-bottom:12px; background:rgba(255,255,255,0.02); padding:12px; border-radius:8px; display:flex; justify-content:space-between; align-items:center;"><div><strong>{info["name"]}</strong> {badge_lbl}<br><span style="font-size:12px; color:#9ca3af;">{phone}</span></div><form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:none; border:none; color:#f87171; cursor:pointer; font-weight:700;">❌ Remove</button></form></li>'

    active_alerts_html = ""
    resolved_history_html = ""
    for idx, incident in enumerate(alerts_log):
        badge_color = "#ef4444" if incident.get("type") in ["Critical Disaster",
                                                            "Armed Attack"] else "#f97316" if incident.get(
            "type") == "Intruder Spotted" else "#eab308"
        if incident.get("status") == "Active":
            active_alerts_html += f'<div style="background:rgba(255,255,255,0.02); border-left:5px solid {badge_color}; padding:15px; margin-bottom:12px; border-radius:4px; display:flex; justify-content:space-between; align-items:center;"><div><strong>🚨 [{incident.get("type")}] ({incident["zone"]}):</strong> "{incident["message"]}"<br><span style="font-size:12px; color:#9ca3af;">Origin: {incident["sender"]}</span></div><form action="/resolve-alert" method="post" style="margin:0;"><input type="hidden" name="alert_id" value="{idx}"><button type="submit" style="background:#10b981; color:white; border:none; padding:6px 12px; border-radius:4px; cursor:pointer; font-weight:700;">⚡ Clear Case</button></form></div>'
        else:
            resolved_history_html += f'<div style="background:rgba(255,255,255,0.01); border-left:4px solid #4b5563; padding:10px; margin-bottom:8px; border-radius:4px; font-size:12px; color:#9ca3af;"><strong>⚠️ Closed [{incident["zone"]}]:</strong> "{incident["message"]}" ({incident["sender"]})</div>'

    audio_matrix_trigger = ""
    if has_critical_disaster:
        audio_matrix_trigger = "<script>function fireSiren(){var c=new(window.AudioContext||window.webkitAudioContext)();var o=c.createOscillator();var g=c.createGain();o.type='sawtooth';o.frequency.setValueAtTime(440,c.currentTime);o.frequency.linearRampToValueAtTime(880,c.currentTime+.5);o.frequency.linearRampToValueAtTime(440,c.currentTime+1);o.connect(g);g.gain.setValueAtTime(.02,c.currentTime);g.connect(c.destination);o.start();setTimeout(function(){c.close();},1000);}setInterval(fireSiren,2000);</script>"

    return f"""
    <html><head><title>Master Control Dashboard</title><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>body{{font-family:sans-serif; background:#0b0f19; padding:25px; color:#e2e8f0;}} .box{{background:#111827; padding:20px; border-radius:16px; border:1px solid rgba(255,255,255,0.05); margin-bottom:20px;}} .title{{border-left:4px solid #10b981; padding-left:10px; font-weight:700; margin-top:0;}}</style>{audio_matrix_trigger}</head><body><div style="max-width:1000px; margin:0 auto;"><header style="display:flex; justify-content:between; margin-bottom:25px;"><div><h1>📡 Global Control Center</h1></div></header><div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:15px; margin-bottom:25px;"><div class="box" style="border-top:4px solid #10b981;"><h2>{total_protected}</h2><span>Protected Devices</span></div><div class="box" style="border-top:4px solid #ef4444;"><h2>{active_incidents}</h2><span>Active Alarms</span></div><div class="box" style="border-top:4px solid #3b82f6;"><h2>{resolved_incidents}</h2><span>Settled Cases</span></div></div><div class="box"><h3 class="title" style="border-color:#f97316;">🚨 Incident Triage Stream</h3>{active_alerts_html or "<p>🟢 System Secure.</p>"}</div><div class="box"><h3 class="title" style="border-color:#4b5563;">📜 Resolution Ledger Archive</h3>{resolved_history_html or "<p>Empty.</p>"}</div><div class="box"><h3 class="title">🟢 Zone_North</h3><ul>{north_zone_html or "<li>None</li>"}</ul></div><div class="box"><h3 class="title" style="border-color:#eab308;">🟡 Zone_South</h3><ul>{south_zone_html or "<li>None</li>"}</ul></div></div></body></html>
    """


@app.post("/incoming-alert")
def handle_incoming_alert(From: str = Form(...), Body: str = Form(...)):
    db = db_engine.load_db()
    sender_number = db_engine.clean_phone_number(From.replace("whatsapp:", ""))
    alert_message = Body

    if sender_number not in db["farmers"]:
        print(f"\n❌ [SECURITY REJECTED] Unknown lookup token key: '{sender_number}'")
        return Response(content="<Response></Response>", media_type="application/xml")

    # If a node hasn't been approved by a neighbor yet, block out alert privileges!
    if db["farmers"][sender_number].get("status", "Pending") == "Pending":
        print(f"\n⚠️ [ALERT BLOCKED] {db['farmers'][sender_number]['name']} is still pending verification.")
        return Response(content="<Response></Response>", media_type="application/xml")

    sender_name = db["farmers"][sender_number]["name"]
    sender_zone = db["farmers"][sender_number]["zone"]

    alert_type = "General Anomaly"
    is_master_override = False

    msg_lower = alert_message.lower()
    if "fire" in msg_lower or "flood" in msg_lower:
        alert_type = "Critical Disaster"
        is_master_override = True
    elif "thief" in msg_lower or "intruder" in msg_lower or "someone" in msg_lower:
        alert_type = "Intruder Spotted"
    elif "cow" in msg_lower or "cattle" in msg_lower or "goat" in msg_lower or "crop" in msg_lower:
        alert_type = "Asset Damage"
    elif "attack" in msg_lower or "armed" in msg_lower:
        alert_type = "Armed Attack"
        is_master_override = True

    db_engine.archive_incident(sender_name, sender_zone, alert_message, alert_type)

    neighbors_to_alert = []
    for number, data in db["farmers"].items():
        if number != sender_number and data.get("status", "Pending") == "Approved":
            if is_master_override or data["zone"] == sender_zone:
                neighbors_to_alert.append((number, data["name"]))

    print(f"\n🚨 [AUTHORIZED ALERT: {alert_type.upper()}] {sender_name} ({sender_zone}): '{alert_message}'")

    if neighbors_to_alert:
        print(f"📡 [HARDWARE OUTBOX ROUTER SECTORS POPULATED]...")
        broadcast_text = f"FARM WATCH ALERT [{alert_type.upper()}] from {sender_name} ({sender_zone}): {alert_message}"
        for neighbor_number, neighbor_name in neighbors_to_alert:
            print(f"   💬 Broadcast Target Node: {neighbor_name} ({neighbor_number})")
            send_production_alert(neighbor_number, broadcast_text)

    print("-" * 60)
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
    return """
    <html>
        <head>
            <title>Register Farm</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { font-family: sans-serif; background-color: #0b0f19; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; padding: 20px; }
                .card { background: #111827; border: 1px solid rgba(255,255,255,0.05); padding: 35px; border-radius: 20px; width: 100%; max-width: 360px; color: white; }
                h2 { margin-top: 0; text-align: center; font-weight: 800; }
                label { display: block; margin-bottom: 6px; font-size: 13px; color: #9ca3af; font-weight: 700; text-transform: uppercase; }
                input, select { width: 100%; padding: 12px; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; color:white; background: #1f2937; }
                button { width: 100%; background: #10b981; color: white; padding: 14px; border: none; border-radius: 10px; font-size: 16px; font-weight: 700; cursor: pointer; }
            </style>
        </head>
        <body>
            <div class="card">
                <h2>Join Watch Grid</h2>
                <form action="/submit-registration" method="post">
                    <label>Farmer Name</label><input type="text" name="name" placeholder="Kwame" required>
                    <label>Phone Number</label><input type="text" name="phone" placeholder="e.g. +234..." required>
                    <label>Watch Zone Sector</label>
                    <select name="zone">
                        <option value="Zone_North">Zone_North (Maize/Cocoa)</option>
                        <option value="Zone_South">Zone_South (Yam/Livestock)</option>
                    </select>
                    <button type="submit">Complete Sign Up</button>
                </form>
            </div>
        </body>
    </html>
    """


@app.post("/submit-registration")
def handle_registration(name: str = Form(...), phone: str = Form(...), zone: str = Form(...)):
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(phone)
    # New users default to pending status until trusted by an active neighbour node
    db["farmers"][clean_phone] = {"name": name, "zone": zone, "status": "Pending"}
    db_engine.save_db(db)

    print(f"\n💾 [WEB REGISTRATION SUCCESS] {name} added under {zone} as PENDING.")

    return HTMLResponse(content=f"""
    <html>
        <body style="font-family: sans-serif; background-color: #0b0f19; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; padding: 20px;">
            <div style="background: #111827; border: 1px solid rgba(255,255,255,0.05); padding: 35px; border-radius: 20px; width: 100%; max-width: 400px; text-align: center; color: white;">
                <h2 style="color: #eab308; margin-top: 0;">⏳ Connection Pending</h2>
                <p style="color: #9ca3af; line-height: 1.6;">Thank you, <strong>{name}</strong>. Your account has been initialized. Please ask an already active approved farmer inside <strong>{zone}</strong> to log into their member portal and approve your connection node.</p>
                <hr style="border: 0; border-top: 1px solid rgba(255,255,255,0.05); margin: 25px 0;">
                <a href="/" style="display: inline-block; background: #1f2937; color: white; padding: 12px 24px; text-decoration: none; border-radius: 10px; font-weight: 700;">⬅️ Back Home</a>
            </div>
        </body>
    </html>
    """)
