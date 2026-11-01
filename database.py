import os
import requests
from datetime import datetime

# Safely extract your live database credentials from Render's cloud environment keys
REDIS_URL = os.getenv("REDIS_URL", "YOUR_UPSTASH_REST_URL_HERE")
REDIS_TOKEN = os.getenv("REDIS_TOKEN", "YOUR_UPSTASH_REST_TOKEN_HERE")

HEADERS = {"Authorization": f"Bearer {REDIS_TOKEN}"}

def clean_phone_number(phone: str) -> str:
    """Removes spaces, dashes, brackets, and formatting to normalize keys."""
    return phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

def initialize_db():
    """Seeds default testing farmers directly into your remote cloud storage room."""
    db = load_db()
    if not db["farmers"]:
        default_farmers = {
            "+2348030001111": {"name": "Kofi", "zone": "Zone_North"},
            "+2348030002222": {"name": "Amadi", "zone": "Zone_North"},
            "+2348030003333": {"name": "Chidi", "zone": "Zone_North"},
            "+2348030004444": {"name": "Musa", "zone": "Zone_South"},
        }
        for phone, data in default_farmers.items():
            # Save each farmer key into your permanent cloud table map
            requests.post(f"{REDIS_URL}/hset/farmers/{phone}/name/{data['name']}/zone/{data['zone']}", headers=HEADERS)

def load_db():
    """Queries your remote database to fetch the comprehensive live network structure."""
    # 1. Fetch all registered farmers
    farmers = {}
    r_farmers = requests.post(f"{REDIS_URL}/hgetall/farmers", headers=HEADERS).json()
    if "result" in r_farmers and r_farmers["result"]:
        # Upstash returns hgetall as a flat list: [key1, val1, key2, val2...]
        flat_list = r_farmers["result"]
        for i in range(0, len(flat_list), 2):
            phone = flat_list[i]
            # Parse the inner string representations safely back to dictionaries
            try:
                # Expecting value format to look like name=Kofi|zone=Zone_North
                parts = flat_list[i+1].split("|")
                name = parts[0].split("=")[1]
                zone = parts[1].split("=")[1]
                farmers[phone] = {"name": name, "zone": zone}
            except Exception:
                pass

    # 2. Fetch all incident logs
    alerts_log = []
    r_logs = requests.post(f"{REDIS_URL}/lrange/alerts_log/0/-1", headers=HEADERS).json()
    if "result" in r_logs and r_logs["result"]:
        for log_str in r_logs["result"]:
            try:
                p = log_str.split("|")
                alerts_log.append({
                    "timestamp": p[0].split("=")[1],
                    "sender": p[1].split("=")[1],
                    "zone": p[2].split("=")[1],
                    "message": p[3].split("=")[1],
                    "type": p[4].split("=")[1],
                    "status": p[5].split("=")[1],
                    "resolved_at": p[6].split("=")[1] if len(p) > 6 else ""
                })
            except Exception:
                pass

    return {"farmers": farmers, "alerts_log": alerts_log}

def add_farmer_to_cloud(phone: str, name: str, zone: str):
    """Pushes a new registration straight into the shared cloud environment database room."""
    clean_p = clean_phone_number(phone)
    val_str = f"name={name}|zone={zone}"
    requests.post(f"{REDIS_URL}/hset/farmers/{clean_p}/{val_str}", headers=HEADERS)

def remove_farmer(phone_number):
    """Deletes a farmer key out of the central cloud records map."""
    clean_p = clean_phone_number(phone_number)
    res = requests.post(f"{REDIS_URL}/hdel/farmers/{clean_p}", headers=HEADERS).json()
    return True if res.get("result") else False

def archive_incident(sender_name, zone, message, alert_type="Standard"):
    """Appends an operational threat record to your cloud database timeline array list."""
    t_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_msg = message.replace("|", " ").replace("=", " ")
    log_str = f"time={t_str}|sender={sender_name}|zone={zone}|msg={clean_msg}|type={alert_type}|status=Active"
    requests.post(f"{REDIS_URL}/rpush/alerts_log/{log_str}", headers=HEADERS)

def update_incident_status(alert_id, target_status="Resolved"):
    """Updates active triage status parameters directly inside your cloud log array lists."""
    db = load_db()
    logs = db["alerts_log"]
    if 0 <= alert_id < len(logs):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Update our targeted item record metrics
        g = logs[alert_id]
        clean_msg = g['message'].replace("|", " ").replace("=", " ")
        updated_str = f"time={g['timestamp']}|sender={g['sender']}|zone={g['zone']}|msg={clean_msg}|type={g['type']}|status={target_status}|res_at={now_str}"
        # Set the array index directly in cloud storage
        requests.post(f"{REDIS_URL}/lset/alerts_log/{alert_id}/{updated_str}", headers=HEADERS)
        return True
    return False
