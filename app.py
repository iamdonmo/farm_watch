import secrets
import requests  # Library to send messages to the phone
from fastapi import FastAPI, Form, Response, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import database as db_engine

app = FastAPI()
security = HTTPBasic()

db_engine.initialize_db()

ADMIN_USERNAME = "chief"
ADMIN_PASSWORD = "securepassword123"


# ---------------------------------------------------------
# NEW ENDPOINT: MAIN COMMUNITY LANDING HOMEPAGE
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def community_homepage():
    """
    Renders a stunning, modern landing page for the Neighborhood Farm Watch platform.
    """
    return """
    <html>
        <head>
            <title>Farm Watch - Community Security Network</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { 
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
                    background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
                    color: white;
                    margin: 0; 
                    padding: 0;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    box-sizing: border-box;
                }
                .hero-container {
                    background: rgba(255, 255, 255, 0.1);
                    backdrop-filter: blur(10px);
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    padding: 40px;
                    border-radius: 16px;
                    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2);
                    max-width: 650px;
                    width: 100%;
                    text-align: center;
                    box-sizing: border-box;
                }
                h1 {
                    font-size: 36px;
                    margin-top: 0;
                    font-weight: 800;
                    letter-spacing: -0.5px;
                    color: #fff;
                }
                h1 span {
                    color: #2ecc71;
                }
                p.tagline {
                    font-size: 18px;
                    color: #e2e8f0;
                    margin-bottom: 35px;
                    line-height: 1.6;
                }
                .features-grid {
                    display: flex;
                    gap: 15px;
                    margin-bottom: 40px;
                    text-align: left;
                }
                .feature-card {
                    flex: 1;
                    background: rgba(255, 255, 255, 0.05);
                    padding: 15px;
                    border-radius: 8px;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                }
                .feature-card h3 {
                    margin-top: 0;
                    color: #2ecc71;
                    font-size: 16px;
                }
                .feature-card p {
                    margin: 0;
                    font-size: 13px;
                    color: #cbd5e1;
                    line-height: 1.4;
                }
                .action-box {
                    display: flex;
                    flex-direction: column;
                    gap: 15px;
                }
                .btn {
                    display: block;
                    padding: 15px;
                    text-decoration: none;
                    font-weight: bold;
                    font-size: 16px;
                    border-radius: 8px;
                    transition: all 0.2s ease;
                }
                .btn-register {
                    background: #2ecc71;
                    color: white;
                    box-shadow: 0 4px 15px rgba(46, 204, 113, 0.3);
                }
                .btn-register:hover {
                    background: #27ae60;
                    transform: translateY(-2px);
                }
                .btn-dashboard {
                    background: transparent;
                    color: white;
                    border: 2px solid white;
                }
                .btn-dashboard:hover {
                    background: white;
                    color: #1e3c72;
                    transform: translateY(-2px);
                }
                .footer {
                    margin-top: 30px;
                    font-size: 12px;
                    color: #94a3b8;
                }
            </style>
        </head>
        <body>
            <div class="hero-container">
                <h1>📡 <span>Farm Watch</span></h1>
                <p class="tagline">Protecting our fields together. An automated, community-driven look-out network safeguarding local smallholder livelihoods.</p>

                <div class="features-grid">
                    <div class="feature-card">
                        <h3>📍 Zone Security</h3>
                        <p>Alerts are instantly targeted specifically to your immediate neighbors to eliminate notification fatigue.</p>
                    </div>
                    <div class="feature-card">
                        <h3>⚡ Emergency Override</h3>
                        <p>Critical events like fires or floods instantly bypass geographic boundaries to keep everyone safe.</p>
                    </div>
                </div>

                <div class="action-box">
                    <a href="/register" class="btn btn-register">➕ Register My Farm Location</a>
                    <a href="/dashboard" class="btn btn-dashboard">🖥️ Access Admin Control Center</a>
                </div>

                <div class="footer">
                    Secured Node Ecosystem • Active Monitoring Enabled
                </div>
            </div>
        </body>
    </html>
    """

# ---------------------------------------------------------
# 🛠️ PHYSICAL ANDROID SMS GATEWAY CONFIGURATION
# ---------------------------------------------------------
# When you open the Android Gateway App, it will give you these 2 values:
ANDROID_GATEWAY_IP = "http://192.168.1.78:8080/send-sms"  # Example: Your phone's local network IP
ANDROID_API_TOKEN = "YOUR_ANDROID_APP_PASSWORD_OR_TOKEN"


def send_physical_sms(to_number: str, message_text: str):
    """
    Sends a local network command to your Android Phone to fire a real SIM card SMS.
    """
    # This URL path changes slightly depending on the specific gateway app you choose
    url = f"{ANDROID_GATEWAY_IP}/api/v1/sms/send"

    payload = {
        "phone": to_number,
        "message": message_text
    }
    headers = {
        "Authorization": f"Bearer {ANDROID_API_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        # We set a fast timeout so if the phone is turned off, the python server doesn't freeze
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        if response.status_code == 200:
            print(f"📲 [REAL SMS LAYER] Signal sent to Android Phone! SMS targeted to: {to_number}")
            return True
    except Exception as e:
        # Fallback if phone is offline during testing
        print(
            f"⚠️ [SIMULATION FALLBACK] Android gateway phone at {ANDROID_GATEWAY_IP} is currently offline. Details: {e}")
    return False


def authenticate_admin(credentials: HTTPBasicCredentials = Depends(security)):
    is_correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    is_correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ---------------------------------------------------------
# SECURED ENDPOINT 1: VISUAL ADMIN CONTROL DASHBOARD (UPGRADED)
# ---------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(username: str = Depends(authenticate_admin)):
    db = db_engine.load_db()
    farmers = db["farmers"]
    alerts_log = db["alerts_log"]

    # Generate the farmers list with an inline deletion form button next to each row
    north_zone_html = ""
    for phone, info in farmers.items():
        if info['zone'] == "Zone_North":
            north_zone_html += f"""
            <li style="margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
                <span><strong>{info['name']}</strong> ({phone})</span>
                <form action="/delete-farmer" method="post" style="margin: 0;" onsubmit="return confirm('Are you sure you want to remove this farmer?');">
                    <input type="hidden" name="phone" value="{phone}">
                    <button type="submit" style="background: none; border: none; color: #e74c3c; cursor: pointer; font-size: 12px; font-weight: bold;">❌ Remove</button>
                </form>
            </li>"""

    south_zone_html = ""
    for phone, info in farmers.items():
        if info['zone'] == "Zone_South":
            south_zone_html += f"""
            <li style="margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
                <span><strong>{info['name']}</strong> ({phone})</span>
                <form action="/delete-farmer" method="post" style="margin: 0;" onsubmit="return confirm('Are you sure you want to remove this farmer?');">
                    <input type="hidden" name="phone" value="{phone}">
                    <button type="submit" style="background: none; border: none; color: #e74c3c; cursor: pointer; font-size: 12px; font-weight: bold;">❌ Remove</button>
                </form>
            </li>"""

    active_alerts_html = ""
    resolved_history_html = ""

    for idx, incident in enumerate(alerts_log):
        badge_color = "#e74c3c" if incident.get("type") == "Critical" else "#e67e22"
        if incident.get("status") == "Active":
            active_alerts_html += f"""
            <div style="background: #fadbd8; border-left: 5px solid {badge_color}; padding: 15px; margin-bottom: 12px; border-radius: 4px; display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span style="font-size: 11px; color: #7f8c8d;">⏱️ {incident['timestamp']}</span><br>
                    <strong style="color: #c0392b;">🚨 [{incident.get('type', 'Standard')}] ({incident['zone']}):</strong> "{incident['message']}"<br>
                    <span style="font-size: 13px; color: #34495e;">Reported by: {incident['sender']}</span>
                </div>
                <form action="/resolve-alert" method="post" style="margin: 0;">
                    <input type="hidden" name="alert_id" value="{idx}">
                    <button type="submit" style="background: #27ae60; color: white; border: none; padding: 8px 12px; border-radius: 4px; cursor: pointer; font-weight: bold;">⚡ Clear</button>
                </form>
            </div>
            """
        else:
            resolved_history_html += f"""
            <div style="background: #eaeded; border-left: 5px solid #7f8c8d; padding: 10px; margin-bottom: 8px; border-radius: 4px; font-size: 13px; color: #7f8c8d;">
                <span>⏱️ Closed at: {incident.get('resolved_at')}</span><br>
                <strong>⚠️ Case #{idx} [{incident['zone']}]:</strong> "{incident['message']}" ({incident['sender']})
            </div>
            """

    return f"""
    <html>
        <head><title>Farm Watch Dashboard</title></head>
        <body style="font-family: sans-serif; background: #ecf0f1; padding: 30px; color: #2c3e50;">
            <div style="max-width: 950px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">
                <h1>📡 Farm Watch Central Guard</h1>
                <p>Live sector tracker with Admin Security and hardware user management layers active.</p>
                <div style="display: flex; gap: 20px; margin-top: 20px;">
                    <div style="flex: 1; padding: 20px; background: #e8f8f5; border-left: 5px solid #1abc9c; border-radius: 6px;">
                        <h3>🟢 Zone_North Network</h3>
                        <ul style="padding-left: 15px; line-height: 1.6;">{north_zone_html or "<li>No active farmers.</li>"}</ul>
                    </div>
                    <div style="flex: 1; padding: 20px; background: #fef9e7; border-left: 5px solid #f1c40f; border-radius: 6px;">
                        <h3>🟡 Zone_South Network</h3>
                        <ul style="padding-left: 15px; line-height: 1.6;">{south_zone_html or "<li>No active farmers.</li>"}</ul>
                    </div>
                </div>
                <div style="margin-top: 30px; display: flex; gap: 20px;">
                    <div style="flex: 1; background: #fdf2e9; border: 1px solid #e59866; border-radius: 6px; padding: 20px;">
                        <h3 style="color: #d35400; margin-top:0;">🚨 Active Triage Incidents</h3>
                        {active_alerts_html or "<p style='color: #27ae60; font-style: italic;'>🟢 All sectors quiet. Threat index: zero.</p>"}
                    </div>
                    <div style="flex: 1; background: #f4f6f7; border: 1px solid #d5dbdb; border-radius: 6px; padding: 20px;">
                        <h3 style="color: #7f8c8d; margin-top:0;">📜 Resolved Historical Logs</h3>
                        {resolved_history_html or "<p style='color: #7f8c8d; font-style: italic;'>Log empty.</p>"}
                    </div>
                </div>
                <br><a href="/register" style="display:inline-block; background:#34495e; color:white; padding:10px 15px; text-decoration:none; border-radius:4px;">➕ Register New Farm Location</a>
            </div>
        </body>
    </html>
    """


# ---------------------------------------------------------
# NEW ENDPOINT: REMOVE USER DATA GATEWAY
# ---------------------------------------------------------
@app.post("/delete-farmer")
def handle_delete_farmer(phone: str = Form(...), username: str = Depends(authenticate_admin)):
    """
    Catches the user removal form post request, validates admin login, and erases record from disk.
    """
    success = db_engine.remove_farmer(phone)
    if success:
        print(f"\n🗑️ [DATABASE UPDATED] Farmer with number {phone} was permanently removed from system storage.")
    else:
        print(f"\n⚠️ [DELETE FAILED] Attempted to remove non-existent phone number: {phone}")

    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/incoming-alert")
def handle_incoming_alert(From: str = Form(...), Body: str = Form(...)):
    db = db_engine.load_db()
    sender_number = From.replace("whatsapp:", "").strip()
    alert_message = Body

    if sender_number not in db["farmers"]:
        print(f"\n❌ [SECURITY REJECTED] Unknown number: {sender_number}")
        return Response(content="<Response></Response>", media_type="application/xml")

    sender_name = db["farmers"][sender_number]["name"]
    sender_zone = db["farmers"][sender_number]["zone"]

    alert_type = "Standard"
    is_master_override = False
    if any(k in alert_message.lower() for k in ["fire", "flood", "attack"]):
        alert_type = "Critical"
        is_master_override = True

    db_engine.archive_incident(sender_name, sender_zone, alert_message, alert_type)

    neighbors_to_alert = []
    for number, data in db["farmers"].items():
        if number != sender_number:
            if is_master_override or data["zone"] == sender_zone:
                neighbors_to_alert.append((number, data["name"]))

    print(f"\n🚨 [{alert_type.upper()} INCIDENT LOGGED] {sender_name} in {sender_zone} triggers: '{alert_message}'")

    if neighbors_to_alert:
        print(f"📡 [HARDWARE OUTBOX ROUTING PIPELINE DISTRIBUTING]...")
        broadcast_text = f"FARM WATCH ALERT from {sender_name} ({sender_zone}): {alert_message}"

        for neighbor_number, neighbor_name in neighbors_to_alert:
            # SIMULATION PRINT LINE: Shows you exactly who it wants to text
            print(f"   💬 [OUTBOUND CUE] Attempting SMS relay to {neighbor_name} ({neighbor_number})...")

            # LIVE HARDWARE ACTION: Calls our real physical android phone bridge loop!
            send_physical_sms(neighbor_number, broadcast_text)

    print("-" * 60)
    return Response(content="<Response></Response>", media_type="application/xml")


@app.post("/resolve-alert")
def resolve_alert(alert_id: int = Form(...)):
    db_engine.update_incident_status(alert_id)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/register", response_class=HTMLResponse)
def registration_form():
    """
    Renders a beautifully centered, mobile-first registration portal card.
    """
    return """
    <html>
        <head>
            <title>Farm Watch Registration</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { 
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
                    background-color: #f4f7f6; 
                    display: flex; 
                    justify-content: center; 
                    align-items: center; 
                    height: 100vh; 
                    margin: 0; 
                    padding: 20px;
                    box-sizing: border-box;
                }
                .card { 
                    background: white; 
                    padding: 30px; 
                    border-radius: 12px; 
                    box-shadow: 0 4px 20px rgba(0,0,0,0.08); 
                    width: 100%;
                    max-width: 380px; 
                    box-sizing: border-box;
                }
                h2 { 
                    color: #2c3e50; 
                    margin-top: 0; 
                    margin-bottom: 25px;
                    font-size: 24px;
                    text-align: center;
                    font-weight: 700;
                }
                label {
                    display: block;
                    margin-bottom: 6px;
                    font-size: 14px;
                    font-weight: 600;
                    color: #34495e;
                }
                input, select { 
                    width: 100%; 
                    padding: 12px; 
                    margin-bottom: 20px; 
                    border: 1px solid #cbd5e1; 
                    border-radius: 6px; 
                    box-sizing: border-box; 
                    font-size: 15px;
                    background-color: #f8fafc;
                    transition: border-color 0.2s;
                }
                input:focus, select:focus {
                    outline: none;
                    border-color: #27ae60;
                    background-color: #fff;
                }
                button { 
                    width: 100%; 
                    background: #27ae60; 
                    color: white; 
                    padding: 14px; 
                    border: none; 
                    border-radius: 6px; 
                    font-size: 16px; 
                    font-weight: bold;
                    cursor: pointer; 
                    transition: background 0.2s;
                    box-shadow: 0 2px 5px rgba(39,174,96,0.2);
                }
                button:hover { 
                    background: #219653; 
                }
            </style>
        </head>
        <body>
            <div class="card">
                <h2>Join Security Network</h2>
                <form action="/submit-registration" method="post">
                    <label>Farmer Name</label>
                    <input type="text" name="name" placeholder="e.g., Kwame" required>

                    <label>Phone Number (with country code)</label>
                    <input type="text" name="phone" placeholder="e.g., +2348030005555" required>

                    <label>Geographic Sector / Zone</label>
                    <select name="zone">
                        <option value="Zone_North">Zone_North (Maize & Cocoa)</option>
                        <option value="Zone_South">Zone_South (Yam & Livestock)</option>
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
    db["farmers"][phone.strip()] = {"name": name, "zone": zone}
    db_engine.save_db(db)
    return RedirectResponse(url="/dashboard", status_code=303)
