import secrets
import requests
from fastapi import FastAPI, Form, Response, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import database as db_engine

app = FastAPI()
security = HTTPBasic()

db_engine.initialize_db()

# Set your secure administrative login credentials here!
ADMIN_USERNAME = "chief"
ADMIN_PASSWORD = "securepassword123"

# Local Android Gateway configuration properties
ANDROID_GATEWAY_IP = "http://192.168.1.50:8080"
ANDROID_API_TOKEN = "YOUR_ANDROID_APP_PASSWORD_OR_TOKEN"


def send_physical_sms(to_number: str, message_text: str):
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
    """Renders a modern, visual landing portal homepage for the root domain URL."""
    return """
    <html>
        <head>
            <title>Farm Watch - Security Network</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family:sans-serif; background:linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color:white; margin:0; padding:20px; display:flex; justify-content:center; align-items:center; min-height:100vh; box-sizing:border-box;">
            <div style="background:rgba(255,255,255,0.1); backdrop-filter:blur(10px); border:1px solid rgba(255,255,255,0.2); padding:40px; border-radius:16px; max-width:600px; width:100%; text-align:center; box-shadow:0 8px 32px rgba(0,0,0,0.15);">
                <h1 style="font-size:36px; margin-top:0;">📡 Farm Watch Gateway</h1>
                <p style="font-size:16px; color:#cbd5e1; margin-bottom:35px; line-height:1.5;">Protecting our fields together. An automated, community-driven lookout network safeguarding local livelihoods.</p>
                <a href="/register" style="display:block; background:#2ecc71; color:white; padding:15px; font-weight:bold; border-radius:8px; text-decoration:none; margin-bottom:15px; box-shadow:0 4px 10px rgba(46,204,113,0.2);">➕ Register My Farm Location</a>
                <a href="/dashboard" style="display:block; border:2px solid white; color:white; padding:13px; font-weight:bold; border-radius:8px; text-decoration:none;">🖥️ Access Admin Control Center</a>
            </div>
        </body>
    </html>
    """


@app.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(username: str = Depends(authenticate_admin)):
    """Displays active registered farmers, triggers, and historical logging items."""
    db = db_engine.load_db()
    farmers = db["farmers"]
    alerts_log = db["alerts_log"]

    north_zone_html = ""
    for phone, info in farmers.items():
        if info['zone'] == "Zone_North":
            north_zone_html += f'<li style="margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;"><span><strong>{info["name"]}</strong> ({phone})</span><form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:none; border:none; color:#e74c3c; cursor:pointer; font-weight:bold; font-size:12px;">❌ Remove</button></form></li>'

    south_zone_html = ""
    for phone, info in farmers.items():
        if info['zone'] == "Zone_South":
            south_zone_html += f'<li style="margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;"><span><strong>{info["name"]}</strong> ({phone})</span><form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:none; border:none; color:#e74c3c; cursor:pointer; font-weight:bold; font-size:12px;">❌ Remove</button></form></li>'

    active_alerts_html = ""
    resolved_history_html = ""
    for idx, incident in enumerate(alerts_log):
        badge_color = "#e74c3c" if incident.get("type") == "Critical" else "#e67e22"
        if incident.get("status") == "Active":
            active_alerts_html += f'<div style="background:#fadbd8; border-left:5px solid {badge_color}; padding:15px; margin-bottom:12px; border-radius:4px; display:flex; justify-content:space-between; align-items:center;"><div><strong>🚨 [{incident.get("type")}] ({incident["zone"]}):</strong> "{incident["message"]}"<br><span style="font-size:12px; color:#555;">Reported by: {incident["sender"]}</span></div><form action="/resolve-alert" method="post" style="margin:0;"><input type="hidden" name="alert_id" value="{idx}"><button type="submit" style="background:#27ae60; color:white; border:none; padding:6px 12px; border-radius:4px; cursor:pointer; font-weight:bold;">⚡ Clear</button></form></div>'
        else:
            resolved_history_html += f'<div style="background:#eaeded; border-left:5px solid #7f8c8d; padding:10px; margin-bottom:8px; border-radius:4px; font-size:12px; color:#7f8c8d;"><strong>⚠️ Closed [{incident["zone"]}]:</strong> "{incident["message"]}" ({incident["sender"]})</div>'

    return f"""
    <html><head><title>Dashboard Control Center</title></head>
    <body style="font-family:sans-serif; background:#ecf0f1; padding:30px; color:#2c3e50;">
        <div style="max-width:950px; margin:0 auto; background:white; padding:30px; border-radius:8px; box-shadow:0 4px 10px rgba(0,0,0,0.02);">
            <h1>📡 Live Central Command Dashboard</h1>
            <div style="display:flex; gap:20px; margin-top:20px;">
                <div style="flex:1; background:#e8f8f5; padding:20px; border-radius:6px; border-left:4px solid #1abc9c;"><h3>🟢 Zone_North (Maize & Cocoa)</h3><ul>{north_zone_html or "<li>No active profiles.</li>"}</ul></div>
                <div style="flex:1; background:#fef9e7; padding:20px; border-radius:6px; border-left:4px solid #f1c40f;"><h3>🟡 Zone_South (Yam & Livestock)</h3><ul>{south_zone_html or "<li>No active profiles.</li>"}</ul></div>
            </div>
            <div style="display:flex; gap:20px; margin-top:30px;">
                <div style="flex:1; background:#fdf2e9; padding:20px; border-radius:6px; border:1px solid #e59866;"><h3>🚨 Active Threat Alerts</h3>{active_alerts_html or "<p style='color:#27ae60; font-style:italic;'>🟢 System Clear. All sectors reporting safe.</p>"}</div>
                <div style="flex:1; background:#f4f6f7; padding:20px; border-radius:6px; border:1px solid #d5dbdb;"><h3>📜 Historical Archive Logs</h3>{resolved_history_html or "<p style='color:#7f8c8d;'>No records.</p>"}</div>
            </div>
            <br><a href="/" style="display:inline-block; background:#34495e; color:white; padding:10px 15px; text-decoration:none; border-radius:4px;">⬅️ Return Home</a>
        </div>
    </body></html>
    """


@app.post("/incoming-alert")
def handle_incoming_alert(From: str = Form(...), Body: str = Form(...)):
    db = db_engine.load_db()

    # Automatically running through the data cleaning layer to strip spaces/brackets
    sender_number = db_engine.clean_phone_number(From.replace("whatsapp:", ""))
    alert_message = Body

    if sender_number not in db["farmers"]:
        print(f"\n❌ [SECURITY REJECTED] Cleaned lookup token key missing from storage index: '{sender_number}'")
        return Response(content="<Response></Response>", media_type="application/xml")

    sender_name = db["farmers"][sender_number]["name"]
    sender_zone = db["farmers"][sender_number]["zone"]

    # Intelligent emergency priority sorting
    alert_type = "Standard"
    is_master_override = False
    if any(k in alert_message.lower() for k in ["fire", "flood", "attack", "armed"]):
        alert_type = "Critical"
        is_master_override = True

    db_engine.archive_incident(sender_name, sender_zone, alert_message, alert_type)

    neighbors_to_alert = []
    for number, data in db["farmers"].items():
        if number != sender_number:
            if is_master_override or data["zone"] == sender_zone:
                neighbors_to_alert.append((number, data["name"]))

    print(f"\n🚨 [AUTHORIZED TRIGGER ALERT] {sender_name} ({sender_zone}): '{alert_message}'")

    if neighbors_to_alert:
        print(f"📡 [HARDWARE OUTBOX ROUTER SECTORS POPULATED]...")
        broadcast_text = f"FARM WATCH ALERT from {sender_name} ({sender_zone}): {alert_message}"
        for neighbor_number, neighbor_name in neighbors_to_alert:
            print(f"   💬 Broadcast Target Node: {neighbor_name} ({neighbor_number})")
            send_physical_sms(neighbor_number, broadcast_text)

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
    """Renders a styled, responsive, centered sign-up web card layout card."""
    return """
    <html><body style="font-family:sans-serif; background:#f4f7f6; display:flex; justify-content:center; align-items:center; height:100vh; margin:0; padding:20px; box-sizing:border-box;">
        <div style="background:white; padding:30px; border-radius:12px; box-shadow:0 4px 20px rgba(0,0,0,0.08); width:100%; max-width:360px;">
            <h2 style="color:#2c3e50; text-align:center; margin-top:0;">Register New Farm</h2>
            <form action="/submit-registration" method="post">
                <label style="font-weight:bold; color:#34495e;">Farmer Name</label><input type="text" name="name" style="width:100%; padding:10px; margin:5px 0 15px 0; border:1px solid #ccc; border-radius:6px;" placeholder="Kwame" required><br>
                <label style="font-weight:bold; color:#34495e;">Phone Number</label><input type="text" name="phone" style="width:100%; padding:10px; margin:5px 0 15px 0; border:1px solid #ccc; border-radius:6px;" placeholder="e.g. +2348030001111" required><br>
                <label style="font-weight:bold; color:#34495e;">Farm Zone Sector</label><select name="zone" style="width:100%; padding:10px; margin:5px 0 20px 0; border:1px solid #ccc; border-radius:6px;">
                    <option value="Zone_North">Zone_North (Maize/Cocoa)</option>
                    <option value="Zone_South">Zone_South (Yam/Livestock)</option>
                </select><br>
                <button type="submit" style="width:100%; background:#27ae60; color:white; padding:12px; border:none; border-radius:6px; font-weight:bold; cursor:pointer;">Register</button>
            </form>
        </div>
    </body></html>
    """


@app.post("/submit-registration")
def handle_registration(name: str = Form(...), phone: str = Form(...), zone: str = Form(...)):
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(phone)
    db["farmers"][clean_phone] = {"name": name, "zone": zone}
    db_engine.save_db(db)
    return RedirectResponse(url="/dashboard", status_code=303)
