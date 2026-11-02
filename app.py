import secrets
import requests
from fastapi import FastAPI, Form, Response, Depends, HTTPException, status
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
    """Locks the dashboard panel behind HTTP Basic Authentication."""
    is_correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    is_correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.get("/", response_class=HTMLResponse)
def community_homepage():
    """Renders a visual, responsive landing portal homepage for the root domain URL."""
    return """
    <html>
        <head>
            <title>Farm Watch - Security Network</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: linear-gradient(135deg, #111827 0%, #1f2937 100%); color: white; margin: 0; padding: 0; display: flex; justify-content: center; align-items: center; min-height: 100vh; box-sizing: border-box; }
                .hero-container { background: rgba(255, 255, 255, 0.03); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); padding: 40px; border-radius: 24px; max-width: 600px; width: 100%; text-align: center; box-sizing: border-box; }
                h1 { font-size: 38px; margin-top: 0; font-weight: 800; letter-spacing: -1px; color: #fff; }
                h1 span { color: #10b981; }
                p.tagline { font-size: 16px; color: #9ca3af; margin-bottom: 35px; line-height: 1.6; }
                .action-box { display: flex; flex-direction: column; gap: 15px; }
                .btn { display: block; padding: 16px; text-decoration: none; font-weight: 700; font-size: 16px; border-radius: 12px; transition: all 0.2s; text-align: center; }
                .btn-register { background: #10b981; color: white; }
                .btn-register:hover { background: #059669; transform: translateY(-2px); }
                .btn-dashboard { background: rgba(255, 255, 255, 0.05); color: white; border: 1px solid rgba(255,255,255,0.2); }
                .btn-dashboard:hover { background: rgba(255, 255, 255, 0.1); transform: translateY(-2px); }
                .footer { margin-top: 30px; font-size: 12px; color: #4b5563; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
            </style>
        </head>
        <body>
            <div class="hero-container">
                <h1>📡 <span>Farm Watch</span> Central</h1>
                <p class="tagline">Protecting our fields together. An automated, community-driven lookout network safeguarding local smallholder agricultural livelihoods.</p>
                <div class="action-box">
                    <a href="/register" class="btn btn-register">➕ Join Network (Register Farm)</a>
                    <a href="/dashboard" class="btn btn-dashboard">🖥️ Access Admin Control Center</a>
                </div>
                <div class="footer">Ecosystem Node Guard Active</div>
            </div>
        </body>
    </html>
    """


@app.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(username: str = Depends(authenticate_admin)):
    """Displays active registered farmers, stats meters, triage modules, and case archives."""
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
            honor_score = sum(
                1 for a in alerts_log if a.get("sender") == info["name"] and a.get("status") == "Resolved")
            stars = "⭐" * min(honor_score + 1, 5)
            north_zone_html += f'<li style="margin-bottom:12px; background:rgba(255,255,255,0.02); padding:12px; border-radius:8px; display:flex; justify-content:space-between; align-items:center; border:1px solid rgba(255,255,255,0.03);"><div><span style="font-weight:700; color:#f3f4f6;">{info["name"]}</span> <span style="font-size:12px;">{stars}</span><br><span style="font-size:12px; color:#9ca3af;">{phone}</span></div><form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:none; border:none; color:#f87171; cursor:pointer; font-weight:700;">❌ Remove</button></form></li>'

    south_zone_html = ""
    for phone, info in farmers.items():
        if info['zone'] == "Zone_South":
            honor_score = sum(
                1 for a in alerts_log if a.get("sender") == info["name"] and a.get("status") == "Resolved")
            stars = "⭐" * min(honor_score + 1, 5)
            south_zone_html += f'<li style="margin-bottom:12px; background:rgba(255,255,255,0.02); padding:12px; border-radius:8px; display:flex; justify-content:space-between; align-items:center; border:1px solid rgba(255,255,255,0.03);"><div><span style="font-weight:700; color:#f3f4f6;">{info["name"]}</span> <span style="font-size:12px;">{stars}</span><br><span style="font-size:12px; color:#9ca3af;">{phone}</span></div><form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:none; border:none; color:#f87171; cursor:pointer; font-weight:700;">❌ Remove</button></form></li>'
    active_alerts_html = ""
    resolved_history_html = ""

    for idx, incident in enumerate(alerts_log):
        if incident.get("type") in ["Critical Disaster", "Armed Attack"]:
            badge_color = "#ef4444"
            bg_color = "rgba(239, 68, 68, 0.15)"
            border_color = "rgba(239, 68, 68, 0.4)"
        elif incident.get("type") == "Intruder Spotted":
            badge_color = "#f97316"
            bg_color = "rgba(249, 115, 22, 0.1)"
            border_color = "rgba(249, 115, 22, 0.3)"
        else:
            badge_color = "#eab308"
            bg_color = "rgba(234, 179, 8, 0.05)"
            border_color = "rgba(234, 179, 8, 0.2)"

        if incident.get("status") == "Active":
            active_alerts_html += f'<div style="background:{bg_color}; border:1px solid {border_color}; border-left:6px solid {badge_color}; padding:16px; margin-bottom:14px; border-radius:12px; display:flex; justify-content:space-between; align-items:center;"><div><div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;"><span style="background:{badge_color}; color:white; font-size:10px; font-weight:800; padding:3px 8px; border-radius:20px; text-transform:uppercase;">{incident.get("type")}</span><span style="font-size:11px; color:#9ca3af;">⏱️ {incident["timestamp"]}</span></div><span style="font-size:15px; color:#f3f4f6; font-weight:600; display:block; margin:6px 0;">"{incident["message"]}"</span><span style="font-size:12px; color:#6b7280;">Node: <strong>{incident["sender"]} ({incident["zone"]})</strong></span></div><form action="/resolve-alert" method="post" style="margin:0;"><input type="hidden" name="alert_id" value="{idx}"><button type="submit" style="background:#10b981; color:white; border:none; padding:10px 16px; border-radius:8px; cursor:pointer; font-weight:700; font-size:14px;">⚡ Clear Case</button></form></div>'
        else:
            resolved_history_html += f'<div style="background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.05); border-left:4px solid #4b5563; padding:12px; margin-bottom:10px; border-radius:8px; font-size:13px; color:#9ca3af;"><span style="font-size:11px; color:#4b5563; float:right;">✅ Closed</span><strong>🔒 Archive Case #{idx} [{incident["zone"]}]:</strong> "{incident["message"]}" <br><span style="font-size:11px; color:#4b5563;">Reported by: {incident["sender"]}</span></div>'

    audio_matrix_trigger = ""
    if has_critical_disaster:
        audio_matrix_trigger = """
        <script>
            function fireSiren() {
                var context = new (window.AudioContext || window.webkitAudioContext)();
                var osc = context.createOscillator();
                var gain = context.createGain();
                osc.type = 'sawtooth';
                osc.frequency.setValueAtTime(440, context.currentTime);
                osc.frequency.linearRampToValueAtTime(880, context.currentTime + 0.5);
                osc.frequency.linearRampToValueAtTime(440, context.currentTime + 1.0);
                osc.connect(gain);
                gain.gain.setValueAtTime(0.03, context.currentTime);
                gain.connect(context.destination);
                osc.start();
                setTimeout(function() { context.close(); }, 1000);
            }
            setInterval(fireSiren, 2000);
        </script>
        """

    return f"""
    <html>
        <head>
            <title>Smart Guard Dashboard</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#0b0f19; padding:25px; color:#e2e8f0; margin:0; }}
                .app-wrapper {{ max-width: 1200px; margin: 0 auto; }}
                header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 20px; }}
                h1 {{ font-size: 28px; font-weight: 800; margin: 0; }}
                h1 span {{ color: #10b981; }}
                .stats-panel {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 30px; }}
                .stat-card {{ background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 16px; padding: 20px; }}
                .stat-num {{ font-size: 32px; font-weight: 800; color: #fff; }}
                .stat-lbl {{ font-size: 13px; color: #9ca3af; text-transform: uppercase; font-weight:600; }}
                .section-box {{ background: #111827; border: 1px solid rgba(255,255,255,0.05); border-radius: 16px; padding: 24px; margin-bottom:25px; }}
                .section-title {{ font-size: 18px; font-weight: 700; margin: 0 0 20px 0; border-left: 4px solid #10b981; padding-left: 10px; }}
                ul {{ list-style: none; padding: 0; margin: 0; }}
            </style>
            {audio_matrix_trigger}
        </head>
        <body>
            <div class="app-wrapper">
                <header>
                    <div><h1>📡 Smart Guard <span>Center</span></h1><span style="font-size:12px; color:#4b5563; font-weight:700;">LIVE LOG INTERLOCK TRACKER ACTIVE</span></div>
                    <a href="/" style="background:rgba(255,255,255,0.05); color:white; padding:10px 18px; text-decoration:none; border-radius:8px; border:1px solid rgba(255,255,255,0.1); font-weight:700;">🏠 Sign Out</a>
                </header>
                <div class="stats-panel">
                    <div class="stat-card" style="border-top: 4px solid #10b981;"><div class="stat-num">{total_protected}</div><div class="stat-lbl">Protected Farms</div></div>
                    <div class="stat-card" style="border-top: 4px solid #ef4444;"><div class="stat-num">{active_incidents}</div><div class="stat-lbl">Active Threats</div></div>
                    <div class="stat-card" style="border-top: 4px solid #3b82f6;"><div class="stat-num">{resolved_incidents}</div><div class="stat-lbl">Settled Logs</div></div>
                </div>
                <div class="section-box">
                    <h3 class="section-title" style="border-color:#f97316;">🚨 Incident Triage Stream</h3>
                    {active_alerts_html or "<p style='color:#10b981; font-style:italic;'>🟢 Grid secure. Anomaly metrics quiet.</p>"}
                </div>
                <div class="section-box">
                    <h3 class="section-title" style="border-color:#4b5563;">📜 Resolution Ledger Archive</h3>
                    {resolved_history_html or "<p style='color:#4b5563;'>Log empty.</p>"}
                </div>
                <div class="section-box">
                    <h3 class="section-title" style="border-color:#10b981;">🟢 Sector_North Nodes</h3>
                    <ul>{north_zone_html or "<li>Empty</li>"}</ul>
                </div>
                <div class="section-box">
                    <h3 class="section-title" style="border-color:#eab308;">🟡 Sector_South Nodes</h3>
                    <ul>{south_zone_html or "<li>Empty</li>"}</ul>
                </div>
            </div>
        </body>
    </html>
    """


@app.post("/incoming-alert")
def handle_incoming_alert(From: str = Form(...), Body: str = Form(...)):
    db = db_engine.load_db()
    sender_number = db_engine.clean_phone_number(From.replace("whatsapp:", ""))
    alert_message = Body

    if sender_number not in db["farmers"]:
        print(f"\n❌ [SECURITY REJECTED] Unknown lookup token key: '{sender_number}'")
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
        if number != sender_number:
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
    db["farmers"][clean_phone] = {"name": name, "zone": zone}
    db_engine.save_db(db)

    print(f"\n💾 [WEB REGISTRATION SUCCESS] {name} added under {zone} with number: {clean_phone}")

    return HTMLResponse(content=f"""
    <html>
        <body style="font-family: sans-serif; background-color: #0b0f19; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; padding: 20px;">
            <div style="background: #111827; border: 1px solid rgba(255,255,255,0.05); padding: 35px; border-radius: 20px; width: 100%; max-width: 400px; text-align: center; color: white;">
                <h2 style="color: #10b981; margin-top: 0;">✅ Registration Secured!</h2>
                <p style="color: #9ca3af; line-height: 1.6;">Welcome, <strong>{name}</strong>. Your device node has been successfully verified and mapped to the <strong>{zone}</strong> grid matrix.</p>
                <hr style="border: 0; border-top: 1px solid rgba(255,255,255,0.05); margin: 25px 0;">
                <a href="/" style="display: inline-block; background: #1f2937; color: white; padding: 12px 24px; text-decoration: none; border-radius: 10px; font-weight: 700;">⬅️ Back Home</a>
            </div>
        </body>
    </html>
    """)
