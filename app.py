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
# 🔑 CUSTOM SECRET ADMINISTRATIVE CREDENTIALS
# ---------------------------------------------------------
ADMIN_USERNAME = "Admin"  # 👈 Change this to your custom username
ADMIN_PASSWORD = "279901"  # 👈 Change this to your custom password

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
        # Color code the alert card badge dynamically based on threat selection category
        if incident.get("type") in ["Critical Disaster", "Armed Attack"]:
            badge_color = "#e74c3c"  # Bright Red for extreme critical events
        elif incident.get("type") == "Intruder Spotted":
            badge_color = "#e67e22"  # Orange for active security threat
        else:
            badge_color = "#f1c40f"  # Yellow for theft or asset damage

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


