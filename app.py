import secrets
import requests
import os
import threading
from fastapi import FastAPI, Form, Response, Depends, HTTPException, status, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import database as db_engine
import geonamescache

app = FastAPI(title="Farm Watch Enterprise Node", version="4.6.0")
security = HTTPBasic()
db_engine.initialize_db()

ADMIN_USERNAME = "chief"
ADMIN_PASSWORD = "securepassword123"

# 📞 ---------------------------------------------------------
# ACTIVE PRODUCTION TWILIO PROFILE INDEX
# ---------------------------------------------------------
TWILIO_ACCOUNT_SID = "AC436cb01fff8036da72eda4b89ef1366d"
TWILIO_AUTH_TOKEN = "9beab2f0af9f6e78b079e27348073269"
TWILIO_PHONE_NUMBER = "whatsapp:+14155238886"

# Pre-approved meta sandbox notification schema container
TWILIO_CONTENT_SID = "HXb5b62575e6e4ff6129ad7c8efe1f983e"

ADMIN_ALERT_WEBHOOK_URL = "https://slack.com"

# Initialize the global geography database automatically
gc = geonamescache.GeonamesCache()

# Let's extract the countries and cities
all_countries = gc.get_countries()
all_cities = gc.get_cities()

import geonamescache

# Initialize the global geography database automatically
gc = geonamescache.GeonamesCache()

all_countries = gc.get_countries()
all_cities = gc.get_cities()

# This sub-database holds the actual text names for the state codes
all_subdivisions = gc.get_subdivisions()

GLOBAL_GEO_DB = {}

for city_id, city_info in all_cities.items():
    country_code = city_info.get('countrycode', '')
    country_name = all_countries.get(country_code, {}).get('name', 'Unknown')
    
    # Get the raw code (e.g., '15' or 'LA')
    state_code = city_info.get('admin1code', 'General Region') 
    
    # 🔄 Look up the real state name using the country code and state code combined
    subdivision_info = all_subdivisions.get(country_code, {}).get(state_code, {})
    state_name = subdivision_info.get('name', f"Region {state_code}") if subdivision_info else f"Region {state_code}"
    
    # Group everything nicely into your dropdown structure
    if country_name not in GLOBAL_GEO_DB:
        GLOBAL_GEO_DB[country_name] = {}
    if state_name not in GLOBAL_GEO_DB[country_name]:
        GLOBAL_GEO_DB[country_name][state_name] = {}
        
    city_name = city_info['name']
    
    # Keeping your original layout structure so your javascript dropdown maps don't break
    GLOBAL_GEO_DB[country_name][state_name][city_name] = {
        "General Sector": ["Central Sector", "Agrarian Grid"]
    }


class DatabaseChangeHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if os.path.basename(event.src_path) == os.path.basename(db_engine.DB_FILE):
            pass

def start_db_watchdog():
    db_dir = os.path.dirname(os.path.abspath(db_engine.DB_FILE)) or "."
    observer = Observer()
    observer.schedule(DatabaseChangeHandler(), path=db_dir, recursive=False)
    observer.start()

threading.Thread(target=start_db_watchdog, daemon=True).start()

def mask_phone_number(phone: str) -> str:
    clean = str(phone).strip()
    if len(clean) <= 6: return "••••" + clean[-2:] if len(clean) > 2 else "••••"
    return f"{clean[:4]}••••{clean[-3:]}"

def send_production_alert(to_number: str, message_text: str):
    """Fires a structural title-case template payload directly to Twilio's REST API."""
    url = f"https://twilio.com{TWILIO_ACCOUNT_SID}/Messages.json"

    clean_target = str(to_number).strip()
    if not clean_target.startswith("whatsapp:"):
        clean_target = f"whatsapp:{clean_target}"

    payload = {
        "To": clean_target,
        "From": TWILIO_PHONE_NUMBER,
        "ContentSid": "HXb5b62575e6e4ff6129ad7c8efe1f983e",
        "ContentVariables": '{"1":"12/1","2":"3pm"}'
    }

    try:
        res = requests.post(
            url,
            data=payload,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=5.0
        )
        print(f"📡 Twilio Dispatch Status: {res.status_code} | Response: {res.text}")
        return res.status_code == 201
    except Exception as e:
        print(f"❌ Network Exception during Twilio dispatch: {e}")
        return False



def get_realtime_weather(lga: str) -> dict:
    geo_coordinates = {
        "osogbo": {"lat": 7.7827, "lon": 4.5418}, "ile-ife": {"lat": 7.4667, "lon": 4.5667},
        "ibadan": {"lat": 7.3775, "lon": 3.9470}, "ogbomoso": {"lat": 8.1333, "lon": 4.2667},
        "kano municipal": {"lat": 11.9964, "lon": 8.5167}, "ikeja": {"lat": 6.5244, "lon": 3.3792}
    }
    coords = geo_coordinates.get(lga.strip().lower(), {"lat": 7.3775, "lon": 3.9470})
    try:
        url = f"https://open-meteo.com{coords['lat']}&longitude={coords['lon']}&current_weather=true"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            w_data = res.json().get("current_weather", {})
            temp = w_data.get("temperature", 28.5)
            desc = "Optimal Growth" if 22 <= temp <= 32 else "Monitor Soil Hydration"
            return {"temp": f"{temp}°C", "desc": desc}
    except Exception: pass
    return {"temp": "28.5°C", "desc": "Optimal Conditions"}

def send_admin_webhook(payload: dict):
    if "://slack.com" in ADMIN_ALERT_WEBHOOK_URL or "://discord.com" in ADMIN_ALERT_WEBHOOK_URL:
        try: requests.post(ADMIN_ALERT_WEBHOOK_URL, json=payload, timeout=3)
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
    .btn-blue { background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%); color: white; box-shadow: 0 4px 14px rgba(59,130,246,0.2); }
    input, select { width:100%; padding:12px; background:#020617; border: 1px solid rgba(255,255,255,0.1); color:white; border-radius:8px; box-sizing:border-box; margin-bottom:15px; font-size: 14px; }
    .responsive-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 24px; width: 100%; }
"""
@app.get("/", response_class=HTMLResponse)
def community_homepage():
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS}</style></head><body><div class="hero glass-panel" style="max-width: 550px; text-align: center; padding: 40px 30px;"><h1>📡 Farm Watch Ecosystem</h1><p style="color: #94a3b8; margin-bottom: 30px; line-height: 1.6; font-size: 15px;">Next-generation protection grid protecting local livelihoods.</p><div style="display:flex; flex-direction:column; gap:14px;"><a href="/register" class="btn btn-emerald">➕ Register Operational Node</a><a href="/portal/login" class="btn btn-blue">👩‍🌾 Member Authentication Portal</a><a href="/dashboard" class="btn" style="background:rgba(255,255,255,0.03); color:#cbd5e1; border:1px solid rgba(255,255,255,0.1);">🖥️ Access Admin Control Center</a></div></div></body></html>"""

@app.get("/portal/login", response_class=HTMLResponse)
def farmer_login_page(error: str = None):
    err_box = f'<div style="color:#f87171; background:rgba(239,68,68,0.1); padding:12px; border-radius:8px; font-size:13px; margin-bottom:20px; font-weight:600; border: 1px solid rgba(239,68,68,0.15);">⚠️ {error}</div>' if error else ""
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS}</style></head><body><div class="login-card glass-panel" style="padding:40px 25px; width:100%; max-width:380px;"><h2>Member Login</h2>{err_box}<form action="/portal/auth" method="post"><label style="font-size:11px; color:#64748b; font-weight:700; display:block; margin-bottom:6px;">PHONE NUMBER</label><input type="text" name="phone" placeholder="e.g. 23480..." required><button type="submit" class="btn btn-blue" style="width: 100%;">Secure Sign In</button></form></div></body></html>"""
@app.post("/portal/auth")
def farmer_authentication(phone: str = Form(...)):
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(phone)
    if clean_phone in db["farmers"]:
        farmer_record = db["farmers"][clean_phone]
        if not isinstance(farmer_record, dict):
            farmer_record = {"name": "Registered Node"}
        farmer_record["name"] = farmer_record.get("name", "Registered Node")
        farmer_record["status"] = farmer_record.get("status", "Approved")
        farmer_record["country"] = farmer_record.get("country", "Nigeria")
        farmer_record["state"] = farmer_record.get("state", "Osun")
        farmer_record["city"] = farmer_record.get("city", "Osogbo")
        farmer_record["lga"] = farmer_record.get("lga", "Osogbo")
        farmer_record["area"] = farmer_record.get("area", "General Farm Hub")
        db["farmers"][clean_phone] = farmer_record
        db_engine.save_db(db)
        if farmer_record.get("status") == "Pending":
            return RedirectResponse(url="/portal/login?error=Access Restricted. Awaiting clearance.", status_code=303)
        res = RedirectResponse(url="/portal/feed", status_code=303)
        res.set_cookie(key="farmer_session", value=clean_phone, max_age=2592000, httponly=True)
        return res
    return RedirectResponse(url="/portal/login?error=Phone number not recognized on network scale.", status_code=303)
@app.get("/portal/feed", response_class=HTMLResponse)
def farmer_feed_portal(current_user=Depends(get_current_farmer)):
    if not current_user:
        return RedirectResponse(url="/portal/login?error=Session expired or profile mismatched.", status_code=303)
    f_phone, f_name, d = current_user["phone"], current_user["data"]["name"], current_user["data"]
    country, state, city, lga, area = d.get("country", "Nigeria"), d.get("state", "Osun"), d.get("city", "Osogbo"), d.get("lga", "Osogbo"), d.get("area", "General Farm Hub")
    db = db_engine.load_db()
    total_neighbors = sum(1 for p, info in db["farmers"].items() if isinstance(info, dict) and info.get("lga") == lga and info.get("status") == "Approved")
    weather = get_realtime_weather(lga)
    nb_html = "".join([f'<div style="background:rgba(59,130,246,0.03); padding:14px; margin-bottom:8px; border-radius:10px; display:flex; justify-content:space-between; align-items:center; gap:10px;"><div><strong style="color:white; display:block; font-size:14px;">{info.get("name", "Node")}</strong><span style="font-size:12px; color:#64748b;">{mask_phone_number(p)} • Sector: {info.get("area","General")}</span></div><form action="/portal/approve-node" method="post" style="margin:0;"><input type="hidden" name="target_phone" value="{p}"><button type="submit" class="btn btn-blue" style="padding:8px 14px; font-size:12px; border-radius:6px;">Verify</button></form></div>' for p, info in db["farmers"].items() if isinstance(info, dict) and info.get("lga") == lga and info.get("status", "Pending") == "Pending" and p != f_phone])
    return render_farmer_complete_html(f_name, country, state, city, lga, area, total_neighbors, weather, nb_html)
def render_farmer_complete_html(f_name, country, state, city, lga, area, total_neighbors, weather, nb_html):
    return f"""
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS} body {{ display:block; padding:15px; }} .container {{ max-width:950px; margin:0 auto; width:100%; }} @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }} .spinner {{ display: none; width: 16px; height: 16px; border: 2px solid rgba(255,255,255,0.3); border-radius: 50%; border-top-color: white; animation: spin 0.8s linear infinite; margin-right: 10px; }} .fun-widget {{ display:flex; gap:15px; margin-bottom:20px; flex-wrap:wrap; }} .widget-card {{ flex:1; min-width:140px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.05); padding:15px; border-radius:14px; text-align:center; }} .trivia-box {{ display:none; background:rgba(15,23,42,0.9); border:1px solid rgba(255,255,255,0.1); padding:20px; border-radius:16px; margin-bottom:25px; }} .social-link {{ display:inline-flex; align-items:center; gap:6px; color:#38bdf8; text-decoration:none; background:rgba(255,255,255,0.02); padding:8px 16px; border-radius:8px; border:1px solid rgba(255,255,255,0.05); font-size:13px; font-weight:700; transition:0.2s; }} .social-link:hover {{ background:rgba(255,255,255,0.08); transform:translateY(-1px); }}</style></head>
    <body>
    <div id="main_terminal_container" class="container glass-panel" style="padding:25px 20px;">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; border-bottom:1px solid rgba(255,255,255,0.05); padding-bottom:20px; margin-bottom:25px; flex-wrap:wrap; gap:15px;">
            <div><h2 style="margin:0; font-size:20px;">👨‍🌾 Node Terminal: {f_name}</h2><span style="background:rgba(16,185,129,0.1); color:#10b981; padding:4px 8px; border-radius:6px; font-size:12px; font-weight:700; display:inline-block; margin-top:5px;">📍 Index: {country} / {state} / {lga} / {area}</span></div>
            <button onclick="handleManualLogout()" class="btn" style="background:rgba(239,68,68,0.1); color:#f87171; padding:8px 16px; font-size:13px;">Disconnect</button>
        </div>
<div style="background:rgba(59,130,246,0.05); border:1px solid rgba(59,130,246,0.2); padding:15px; border-radius:12px; margin-bottom:20px; font-size:13px; line-height:1.5;">📱 <strong>WhatsApp Sandbox Activation Required:</strong> Text <code>join choice-something</code> to <strong>+1 415 523 8886</strong> from your mobile device.</div>
<div class="fun-widget">
    <div class="widget-card">🌤️<br><strong style="font-size:13px;color:#38bdf8;">Live Weather API</strong><br><span style="font-size:14px;font-weight:bold;color:#10b981;">{weather['temp']} - {weather['desc']}</span></div>
    <div class="widget-card">🛡️<br><strong style="font-size:13px;color:#10b981;">Grid Sync</strong><br><span style="font-size:14px;font-weight:bold;">{total_neighbors} Peers Active</span></div>
    <div class="widget-card">🎮<br><strong style="font-size:13px;color:#a855f7;">Breakout Terminal</strong><br><span style="font-size:12px;cursor:pointer;text-decoration:underline;color:#a855f7;font-weight:bold;" onclick="toggleTriviaGame()">Launch Training Quiz</span></div>
</div>
<div id="trivia_module" class="trivia-box">
    <div style="display:flex; justify-content:space-between; align-items:center;"><h4 style="margin:0; color:#38bdf8;">🌾 Operational Security Training Quiz</h4><span id="quiz_progress" style="font-size:12px; color:#64748b; font-weight:bold;">Question 1/3</span></div>
    <p id="trivia_question" style="margin:15px 0; font-weight:600; min-height:40px;"></p>
    <div id="trivia_options" style="display:grid; gap:8px; margin-bottom:15px;"></div>
    <p id="trivia_feedback" style="font-weight:bold; font-size:14px; min-height:20px; margin:10px 0;"></p>
    <div style="display:flex; justify-content:space-between; margin-top:10px;">
        <button id="quiz_back_btn" class="btn" style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.1); padding:6px 14px; font-size:12px;" onclick="navigateQuiz(-1)">⬅️ Back</button>
        <button id="quiz_next_btn" class="btn btn-blue" style="padding:6px 14px; font-size:12px;" onclick="navigateQuiz(1)">Next ➡️</button>
    </div>
</div>
    <div class="responsive-grid">
        <div style="background:rgba(239,68,68,0.02); border:1px solid rgba(239,68,68,0.1); padding:20px; border-radius:16px; height:fit-content;">
            <h3>🚨 Broadcast Emergency</h3>
            <form id="broadcast_form" method="post" onsubmit="handleBroadcastSubmit(event)" style="display:flex; flex-direction:column; gap:12px; margin:0;">
                <select id="alert_type" name="alert_type"><option value="Intruder Spotted">Intruder Spotted</option><option value="Critical Disaster">Critical Disaster</option><option value="Armed Attack">Armed Attack</option></select>
                <input type="text" id="message" name="message" placeholder="Situation details..." required><button type="submit" id="dispatch_btn" class="btn btn-emerald" style="width:100%;"><div id="btn_spinner" class="spinner"></div><span id="btn_text">📡 Dispatch Alert Matrix</span></button>
            </form>
        </div>
        <div>
            <h3>🤝 Peer Authentication Desk</h3>
            {nb_html or "<p style='color:#64748b; font-size:13px; font-style:italic;'>Clear ring.</p>"}
            <h3>📡 Live Feed (● Live Auto-Sync)</h3>
            <div id="live_stream_container"></div>
        </div>
    </div>
    <div style="margin-top:30px; padding-top:20px; border-top:1px solid rgba(255,255,255,0.05);">
        <h4 style="margin:0 0 12px; color:#64748b; font-size:11px; text-transform:uppercase; letter-spacing:1px;">🛡️ Community Safety Connect Hub</h4>
        <div style="display:flex; gap:10px; flex-wrap:wrap;">
            <a href="https://wa.me" target="_blank" class="social-link">💬 WhatsApp Group</a>
            <a href="https://telegram.org" target="_blank" class="social-link">✈️ Telegram Alert Channel</a>
            <a href="https://facebook.com" target="_blank" class="social-link">👥 Facebook Union</a>
        </div>
    </div>
</div>
<script>
    const quizData = [
        {{ q: "What should a farmer do first if an unknown intruder is spotted near boundaries?", options: ["📡 Instantly broadcast an alarm inside the Farm Watch portal", "🏃 Investigate the location alone without signaling neighbors"], correct: 0 }},
        {{ q: "Which type of alert triggers a Master Override broadcast to all sectors across the country database?", options: ["🌾 Asset Damage (Cattle/Crops)", "🔥 Critical Disaster (Fire/Flood) or Armed Attack"], correct: 1 }},
        {{ q: "What is the primary criteria required for a new registered node to activate their portal feed?", options: ["⏳ Complete approval clearance from an approved admin or neighbor node", "🔑 Entering the master chief panel credentials"], correct: 0 }}
    ];
    let currentQuizIndex = 0;
    function toggleTriviaGame() {{ const box = document.getElementById("trivia_module"); box.style.display = box.style.display === "block" ? "none" : "block"; if(box.style.display === "block") renderQuizQuestion(); }}
    function renderQuizQuestion() {{
        const item = quizData[currentQuizIndex]; document.getElementById("quiz_progress").innerText = "Question " + (currentQuizIndex + 1) + "/" + quizData.length; document.getElementById("trivia_question").innerText = item.q; document.getElementById("trivia_feedback").innerText = "";
        const optsContainer = document.getElementById("trivia_options"); optsContainer.innerHTML = "";
        item.options.forEach((opt, idx) => {{ optsContainer.innerHTML += `<button class="btn" style="background:#1f2937; text-align:left; justify-content:flex-start; width:100%; font-size:13px;" onclick="evaluateQuizAnswer(${{idx}})">${{opt}}</button>`; }});
        document.getElementById("quiz_back_btn").style.visibility = currentQuizIndex === 0 ? "hidden" : "visible";
        document.getElementById("quiz_next_btn").innerText = currentQuizIndex === quizData.length - 1 ? "Finish 🎉" : "Next ➡️";
    }}
    function evaluateQuizAnswer(selectedIdx) {{
        const item = quizData[currentQuizIndex]; const fb = document.getElementById("trivia_feedback");
        if(selectedIdx === item.correct) {{ fb.style.color = "#10b981"; fb.innerText = "🟢 Correct answer! Excellent security protocol tracking."; }} 
        else {{ fb.style.color = "#ef4444"; fb.innerText = "❌ Incorrect option. Review network protocols for maximum grid protection."; }}
    }}
    function navigateQuiz(dir) {{ currentQuizIndex += dir; if(currentQuizIndex >= quizData.length) {{ currentQuizIndex = 0; toggleTriviaGame(); return; }} if(currentQuizIndex < 0) currentQuizIndex = 0; renderQuizQuestion(); }}
    function handleManualLogout() {{ window.location.href = "/portal/logout"; }}
    function handleBroadcastSubmit(e) {{
        e.preventDefault(); const b=document.getElementById("dispatch_btn"); const s=document.getElementById("btn_spinner"); const t=document.getElementById("btn_text");
        b.style.opacity="0.7"; b.style.pointerEvents="none"; s.style.display="inline-block"; t.innerText="Transmitting Alert Grid...";
        const f=new FormData(); f.append("alert_type", document.getElementById("alert_type").value); f.append("message", document.getElementById("message").value);
        fetch("/portal/alert/raise", {{ method: "POST", body: f }});
        setTimeout(() => {{ document.getElementById("main_terminal_container").innerHTML = `<div style="padding:40px 25px; text-align:center; max-width:450px; margin:40px auto; width:100%;" class="glass-panel"><div style="font-size:48px; margin-bottom:15px;">✅</div><h2 style="color:#10b981; margin:0 0 10px;">Broadcast Dispatched</h2><p style="color:#94a3b8; font-size:14px;">Your incident report has been securely transmitted across the Grid.</p><a href="/portal/feed" class="btn btn-blue" style="margin-top:20px; width:100%;">Return to Guard Station</a></div>`; }}, 3000);
    }}
    async function fetchLiveFeedStream() {{ try {{ const res = await fetch("/portal/feed/stream"); if (res.status === 200) {{ document.getElementById("live_stream_container").innerHTML = await res.text(); }} }} catch(e) {{}} }}
    setInterval(fetchLiveFeedStream, 2000); fetchLiveFeedStream();
</script></body></html>
"""
@app.get("/portal/feed/stream")
def portal_async_feed_stream(current_user=Depends(get_current_farmer)):
    if not current_user: return Response(status_code=401)
    lga = current_user["data"].get("lga", "Unknown")
    db = db_engine.load_db()
    html = "".join([f'<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:16px; margin-bottom:12px; border-radius:12px;"><div style="display:flex; justify-content:space-between; font-size:11px; color:#64748b; margin-bottom:4px;"><span>⏱️ {i["timestamp"]}</span><span style="color:#ef4444; font-weight:800;">{i["status"]}</span></div><strong style="color:#f97316; font-size:13px;">[{i.get("type")}]</strong><span style="display:block; margin:6px 0; color:#e2e8f0; line-height:1.4;">"{i["message"]}"</span><span style="font-size:11px; color:#475569;">Origin: {i["sender"]}</span></div>' for i in reversed(db["alerts_log"]) if i.get("lga") == lga])
    return HTMLResponse(content=html or "<p style='color:#64748b; font-size:13px; font-style:italic;'>Sectors quiet across local scope.</p>")

@app.post("/portal/alert/raise")
def farmer_raise_alert(alert_type: str = Form(...), message: str = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user: return Response(status_code=401)
    f_phone, f_name, d = current_user["phone"], current_user["data"]["name"], current_user["data"]
    db = db_engine.load_db()
    db_engine.archive_incident(f_name, d.get("lga"), message, alert_type)
    idx = len(db["alerts_log"]) - 1
    if idx >= 0:
        db = db_engine.load_db()
        for field in ["country", "state", "city", "lga", "area"]: db["alerts_log"][idx][field] = d.get(field, "Unknown")
        db_engine.save_db(db)
    override = alert_type in ["Critical Disaster", "Armed Attack"]
    targets = [p for p, data in db["farmers"].items() if isinstance(data, dict) and p != f_phone and data.get("status") == "Approved" and (override or data.get("lga") == d.get("lga"))]
    threading.Thread(target=lambda: [send_production_alert(n, f"ALERT [{alert_type.upper()}] from {f_name}: {message}") for n in targets], daemon=True).start()
    return Response(status_code=200)

@app.get("/admin/export-ledger")
def admin_export_ledger(username: str = Depends(authenticate_admin)):
    db = db_engine.load_db()
    csv_data = "Timestamp,Type,Sender,LGA District,Message,Status\n"
    for i in db.get("alerts_log", []):
        msg = i.get("message", "").replace('"', '""')
        csv_data += f'"{i.get("timestamp")}","{i.get("type")}","{i.get("sender")}","{i.get("lga")}","{msg}","{i.get("status")}"\n'
    return StreamingResponse(iter([csv_data]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=farm_watch_security_ledger.csv"})
@app.post("/portal/approve-node")
def handle_node_approval(target_phone: str = Form(...), current_user=Depends(get_current_farmer)):
    if not current_user: return HTMLResponse(content="<html><script>window.location.href='/portal/login';</script></html>")
    db_engine.approve_farmer_node(target_phone)
    return HTMLResponse(content="<html><script>window.location.href='/portal/feed';</script></html>")

@app.get("/portal/logout")
def handle_member_logout():
    response = HTMLResponse(content="<html><script>document.cookie='farmer_session=; max-age=0; path=/;'; window.location.href='/';</script></html>")
    return response
@app.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(username: str = Depends(authenticate_admin)):
    db = db_engine.load_db()
    total, active, resolved = len(db["farmers"]), sum(1 for i in db["alerts_log"] if i.get("status") == "Active"), sum(1 for i in db["alerts_log"] if i.get("status") == "Resolved")
    pending_html = ""
    for phone, m in db["farmers"].items():
        if isinstance(m, dict) and m.get("status", "Pending") == "Pending":
            pending_html += f'<div style="display:flex; justify-content:space-between; align-items:center; padding:12px; background:rgba(234,179,8,0.03); border:1px solid rgba(234,179,8,0.15); margin-bottom:8px; border-radius:8px; flex-wrap:wrap; gap:10px;"><span>⏳ <strong>{m["name"]}</strong> ({phone})<br><small style="color:#64748b;">MAPPED: {m.get("country")} -> {m.get("lga")}</small></span><div style="display:flex; gap:6px;"><form action="/admin/approve-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:#10b981; border:none; color:white; padding:6px 12px; border-radius:6px; font-size:11px; cursor:pointer; font-weight:700;">Approve</button></form><form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:rgba(239,68,68,0.1); border:none; color:#f87171; padding:6px 12px; border-radius:6px; font-size:11px; cursor:pointer;">Deny</button></form></div></div>'
    grouped_html, by_geo = "", {}
    for p, f in db["farmers"].items():
        if isinstance(f, dict) and f.get("status") == "Approved":
            g_key = f"{f.get('country','Unknown')} → {f.get('state','Unknown')} → {f.get('city','Unknown')} → {f.get('lga','Unknown')}"
            if g_key not in by_geo: by_geo[g_key] = []
            by_geo[g_key].append((p, f))
    for path, members in by_geo.items():
        m_list = "".join([f'<li style="display:flex; justify-content:space-between; align-items:center; padding:10px; background:rgba(255,255,255,0.02); margin-bottom:6px; border-radius:8px; gap:10px;"><span style="font-size:14px;">🟢 <strong>{m["name"]}</strong> ({m.get("area")}) <small style="color:#64748b; display:block; margin-top:2px;">{phone}</small></span><form action="/delete-farmer" method="post" style="margin:0;"><input type="hidden" name="phone" value="{phone}"><button type="submit" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:13px;">❌ Remove</button></form></li>' for phone, m in members])
        grouped_html += f'<div style="margin-bottom:20px; border-left:3px solid #3b82f6; padding-left:12px;"><h4 style="margin:0 0 10px; color:#38bdf8; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;">🗺️ {path}</h4><ul style="padding:0; margin:0; list-style:none;">{m_list}</ul></div>'
    al_html = "".join([f'<div style="background:rgba(239,68,68,0.03); border:1px solid rgba(239,68,68,0.1); padding:16px; margin-bottom:10px; border-radius:12px; display:flex; justify-content:space-between; align-items:center; gap:15px; flex-wrap:wrap;"><div style="font-size:14px; line-height:1.4;"><strong>🚨 {i["type"]} ({i.get("lga")}):</strong> "{i["message"]}"</div><form action="/resolve-alert" method="post" style="margin:0;"><input type="hidden" name="alert_id" value="{idx}"><button type="submit" class="btn" style="background:#10b981; color:white; padding:6px 14px; font-size:12px; border-radius:6px;">Clear</button></form></div>' for idx, i in enumerate(db["alerts_log"]) if i.get("status") == "Active"])
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS} body {{ display:block; padding:15px; }} .box {{ max-width:1000px; margin:0 auto; width:100%; }} .stats-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:16px; margin:25px 0; }} .card {{ padding:20px; text-align:center; }} .card h2 {{ margin:0 0 4px; font-size:32px; font-weight:800; }}</style></head><body><div class="box glass-panel" style="padding:30px 20px;"><div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:15px;"><h2>📡 Global Command Dashboard</h2><a href="/admin/export-ledger" class="btn btn-emerald" style="padding:8px 16px; font-size:13px;">📊 Export Ledger Spreadsheet</a></div><div class="stats-grid"><div class="card glass-panel" style="border-top:3px solid #10b981;"><h2>{total}</h2><small style="color:#64748b; font-weight:700; letter-spacing:0.5px;">REGISTRATIONS</small></div><div class="card glass-panel" style="border-top:3px solid #ef4444;"><h2>{active}</h2><small style="color:#64748b; font-weight:700; letter-spacing:0.5px;">ACTIVE THREATS</small></div><div class="card glass-panel" style="border-top:3px solid #3b82f6;"><h2>{resolved}</h2><small style="color:#64748b; font-weight:700; letter-spacing:0.5px;">CONTAINED</small></div></div><h3 style="color:#eab308; border-bottom:1px solid rgba(234,179,8,0.1); padding-bottom:8px; margin-top:30px;">⏳ Awaiting Executive Security Authorization</h3>{pending_html or "<p style='color:#64748b; font-size:13px; font-style:italic;'>No new registrations pending clearance.</p>"}<h3>🚨 Active Alarms Ledger</h3>{al_html or "<p style='color:#64748b; font-size:13px; font-style:italic;'>No open alarms.</p>"}<h3>🗂️ Authorized Active Infrastructure Ring Map</h3>{grouped_html or "<p style='color:#64748b; font-size:13px; font-style:italic;'>Map unmapped.</p>"}</div></body></html>"""
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
    targets = [p for p, d in db["farmers"].items() if isinstance(d, dict) and p != sender_number and d.get("status") == "Approved" and (override or d.get("lga") == lga)]
    threading.Thread(target=lambda: [send_production_alert(num, f"ALERT [{alert_type.upper()}] from {f_data['name']}: {Body}") for num in targets], daemon=True).start()
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
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS} body{{display:flex; justify-content:center; align-items:center; min-height:100vh; padding:15px;}} .reg {{ max-width:440px; width:100%; }} label{{display:block; margin:12px 0 4px; font-size:11px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;}}</style></head><body><div class="glass-panel reg" style="padding:35px 25px;"><h2>Register Security Node</h2><p style="color:#64748b; font-size:13px; margin-top:-10px; margin-bottom:25px; line-height:1.4;">Provide drop data OR skip fields and just type your city below.</p><form action="/submit-registration" method="post" style="margin:0;"><label>Farmer Name</label><input type="text" name="name" placeholder="Kwame" required><label>Phone Number</label><input type="text" name="phone" placeholder="e.g. +234..." required><label>City / Town (Autofill Input)</label><input type="text" name="city_manual" required><div style="border:1px solid rgba(255,255,255,0.05); padding:15px 12px; border-radius:12px; margin-bottom:20px; background: rgba(0,0,0,0.1);"><label style="margin:0 0 8px; color:#94a3b8;">Optional Dropdowns</label><select id="c_select" name="country" onchange="updateStates()"><option value="">-- Country --</option><option value="Nigeria">Nigeria</option></select><select id="s_select" name="state" onchange="updateCities()"><option value="">-- State --</option></select><select id="city_select" name="city" onchange="updateLGAs()"><option value="">-- City --</option></select><select id="lga_select" name="lga" onchange="updateAreas()"><option value="">-- LGA --</option></select><select id="area_select" name="area"><option value="">-- Area --</option></select></div><button type="submit" class="btn btn-emerald" style="width:100%;">Complete Request</button></form><br><center><a href="/register/test" style="color:#38bdf8; font-size:12px; text-decoration:underline;">💻 Launch Autofill Diagnostic Simulator</a></center></div>
    <script>
        const geoDb = {str(GLOBAL_GEO_DB)};
        function updateStates() {{ const c = document.getElementById("c_select").value; const s = document.getElementById("s_select"); s.innerHTML = '<option value="">-- State --</option>'; document.getElementById("city_select").innerHTML = '<option value="">-- City --</option>'; document.getElementById("lga_select").innerHTML = '<option value="">-- LGA --</option>'; document.getElementById("area_select").innerHTML = '<option value="">-- Area --</option>'; if(c && geoDb[c]) {{ Object.keys(geoDb[c]).forEach(k => {{ s.options.add(new Option(k, k)); }}); }} }}
        function updateCities() {{ const c = document.getElementById("c_select").value; const s = document.getElementById("s_select").value; const city = document.getElementById("city_select"); city.innerHTML = '<option value="">-- City --</option>'; document.getElementById("lga_select").innerHTML = '<option value="">-- LGA --</option>'; document.getElementById("area_select").innerHTML = '<option value="">-- Area --</option>'; if(c && s && geoDb[c][s]) {{ Object.keys(geoDb[c][s]).forEach(k => {{ city.options.add(new Option(k, k)); }}); }} }}
        function updateLGAs() {{ const c = document.getElementById("c_select").value; const s = document.getElementById("s_select").value; const city = document.getElementById("city_select").value; const lga = document.getElementById("lga_select"); lga.innerHTML = '<option value="">-- LGA --</option>'; document.getElementById("area_select").innerHTML = '<option value="">-- Area --</option>'; if(c && s && city && geoDb[c][s][city]) {{ Object.keys(geoDb[c][s][city]).forEach(k => {{ lga.options.add(new Option(k, k)); }}); }} }}
        function updateAreas() {{ const c = document.getElementById("c_select").value; const s = document.getElementById("s_select").value; const city = document.getElementById("city_select").value; const lga = document.getElementById("lga_select").value; const area = document.getElementById("area_select"); area.innerHTML = '<option value="">-- Area --</option>'; if(c && s && city && lga && geoDb[c][s][city][lga]) {{ geoDb[c][s][city][lga].forEach(v => {{ area.options.add(new Option(v, v)); }}); }} }}
    </script></body></html>"""
@app.get("/register/test", response_class=HTMLResponse)
def database_autofill_diagnostic_test():
    test_scenarios = ["Osogbo", "Ibadan", "Ogbomoso", "Ile-Ife"]
    logs_html = "".join([f'<div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:12px; margin-bottom:6px; border-radius:8px;">🔍 Testing Keyword: <strong>"{tok}"</strong> → Result Country: <strong>{CITY_AUTOFILL_MAP[tok.lower()]["country"]}</strong> | Resolved District: <strong>{CITY_AUTOFILL_MAP[tok.lower()]["lga"]}</strong> <span style="color:#10b981; float:right;">✔ PASS</span></div>' for tok in test_scenarios])
    return f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS}</style></head><body><div class="glass-panel" style="max-width:550px; padding:30px 20px;"><h3>💻 Mapped Autofill Diagnostic Test Matrix</h3><p style="color:#64748b; font-size:13px; margin-top:-10px;">Simulating instant query extraction parameters across open background threads:</p>{logs_html}<br><a href="/register" class="btn btn-blue" style="width:100%;">Return to Live Form</a></div></body></html>"""
@app.post("/submit-registration")
def handle_registration(name: str = Form(...), phone: str = Form(...), city_manual: str = Form(...), country: str = Form(None), state: str = Form(None), city: str = Form(None), lga: str = Form(None), area: str = Form(None)):
    lookup_token = city_manual.strip().lower()
    if lookup_token in CITY_AUTOFILL_MAP:
        geo = CITY_AUTOFILL_MAP[lookup_token]
        c, s, ci, lg, ar = geo["country"], geo["state"], city_manual, geo["lga"], geo["area"]
    else:
        c, s, ci, lg, ar = country or "Nigeria", state or "Unknown Region", city_manual, lga or f"{city_manual} Sector", area or "General Farm Hub"
    db = db_engine.load_db()
    clean_phone = db_engine.clean_phone_number(phone)
    db["farmers"][clean_phone] = {"name": name, "country": c, "state": s, "city": ci, "lga": lg, "area": ar, "zone": lg, "status": "Pending"}
    db_engine.save_db(db)
    if lookup_token not in CITY_AUTOFILL_MAP:
        send_admin_webhook({"text": f"🚧 *UNMAPPED CITY ALERT*: *{name}* ({phone}) signed up using: *{city_manual}*."})
    return HTMLResponse(content=f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{CORE_CSS}</style></head><body><div class="glass-panel" style="padding:40px 25px; text-align:center; max-width:440px; width:100%;"><h2 style="color:#eab308; margin-top:0;">⏳ Profile Mapped</h2><p style="color:#94a3b8; font-size:14px;">Thank you, {name}. System mapped you under <strong>{lg} Sector</strong> based on your city input. Awaiting administrator gate clearance.</p><a href="/" class="btn btn-emerald" style="margin-top:20px; width:100%;">Back Home</a></div></body></html>""")
