import os
import requests
from datetime import datetime

# Extract credentials safely from Render environment variables
REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_TOKEN = os.getenv("REDIS_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {REDIS_TOKEN}"} if REDIS_TOKEN else {}

# 🌟 DYNAMIC ENVIRONMENT DETECTION SWITCH
# If cloud keys aren't found, it activates local mode so your app never crashes on your laptop!
IS_CLOUD_ACTIVE = True if (REDIS_URL and REDIS_TOKEN) else False

# Local offline storage tables (Used only when running on your laptop)
LOCAL_FARMER_RAM = {
    "+2348030001111": {"name": "Kofi", "zone": "Zone_North"},
    "+2348030002222": {"name": "Amadi", "zone": "Zone_North"},
    "+2348030003333": {"name": "Chidi", "zone": "Zone_North"},
    "+2348030004444": {"name": "Musa", "zone": "Zone_South"},
}
LOCAL_ALERTS_LOG = []


def clean_phone_number(phone: str) -> str:
    """Removes spaces, dashes, brackets, and formatting to normalize keys."""
    return phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")


def initialize_db():
    """Seeds default testing farmers dynamically into whichever engine is active."""
    if IS_CLOUD_ACTIVE:
        try:
            db = load_db()
            if not db["farmers"]:
                default_farmers = {
                    "+2348030001111": {"name": "Kofi", "zone": "Zone_North"},
                    "+2348030002222": {"name": "Amadi", "zone": "Zone_North"},
                    "+2348030003333": {"name": "Chidi", "zone": "Zone_North"},
                    "+2348030004444": {"name": "Musa", "zone": "Zone_South"},
                }
                for phone, data in default_farmers.items():
                    requests.post(f"{REDIS_URL}/hset/farmers/{phone}/name={data['name']}|zone={data['zone']}", headers=HEADERS, timeout=5)
        except Exception:
            pass
    else:
        print("\n🏠 [LOCAL MODE] Running offline on laptop. Bypassing cloud database connections.")


def load_db():
    """Queries either the remote cloud database or local memory storage arrays."""
    if not IS_CLOUD_ACTIVE:
        return {"farmers": LOCAL_FARMER_RAM, "alerts_log": LOCAL_ALERTS_LOG}

    farmers = {}
    alerts_log = []
    
    try:
        # 1. Fetch cloud farmers map
        r_farmers = requests.post(f"{REDIS_URL}/hgetall/farmers", headers=HEADERS, timeout=5).json()
        if "result" in r_farmers and r_farmers["result"]:
            flat_list = r_farmers["result"]
            for i in range(0, len(flat_list), 2):
                phone = flat_list[i]
                try:
                    parts = flat_list[i+1].split("|")
                    name = parts[0].split("=")[1]
                    zone = parts[1].split("=")[1]
                    farmers[phone] = {"name": name, "zone": zone}
                except Exception:
                    pass

        # 2. Fetch cloud incident log archive timeline
        r_logs = requests.post(f"{REDIS_URL}/lrange/alerts_log/0/-1", headers=HEADERS, timeout=5).json()
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
                        "status": p[5].split("=")[1]
                    })
                except Exception:
                    pass
    except Exception as e:
        print(f"⚠️ [CLOUD DATABASE TIMEOUT] Falling back to baseline sets: {e}")
        return {"farmers": LOCAL_FARMER_RAM, "alerts_log": LOCAL_ALERTS_LOG}

    return {"farmers": farmers, "alerts_log": alerts_log}


def add_farmer_to_cloud(phone: str, name: str, zone: str):
    """Pushes a new signup straight to the active central data ledger."""
    clean_p = clean_phone_number(phone)
    if IS_CLOUD_ACTIVE:
        try:
            val_str = f"name={name}|zone={zone}"
            requests.post(f"{REDIS_URL}/hset/farmers/{clean_p}/{val_str}", headers=HEADERS, timeout=5)
            print(f"💾 [SHARED CLOUD DB] {name} committed dynamically over internet pipeline.")
        except Exception as e:
            print(f"❌ [CLOUD SAVE ERROR] Failed to connect to Upstash: {e}")
    else:
        LOCAL_FARMER_RAM[clean_p] = {"name": name, "zone": zone}
        print(f"💾 [LOCAL RAM DB] {name} added instantly to laptop storage structure.")


def remove_farmer(phone_number):
    """Deletes a farmer key out of the live ledger records mapping."""
    clean_p = clean_phone_number(phone_number)
    if IS_CLOUD_ACTIVE:
        try:
            res = requests.post(f"{REDIS_URL}/hdel/farmers/{clean_p}", headers=HEADERS, timeout=5).json()
            return True if res.get("result") else False
        except Exception:
            return False
    else:
        if clean_p in LOCAL_FARMER_RAM:
            del LOCAL_FARMER_RAM[clean_p]
            return True
        return False


def archive_incident(sender_name, zone, message, alert_type="Standard"):
    """Appends an operational threat entry record straight into live timeline arrays."""
    t_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_msg = message.replace("|", " ").replace("=", " ")
    
    if IS_CLOUD_ACTIVE:
        try:
            log_str = f"time={t_str}|sender={sender_name}|zone={zone}|msg={clean_msg}|type={alert_type}|status=Active"
            requests.post(f"{REDIS_URL}/rpush/alerts_log/{log_str}", headers=HEADERS, timeout=5)
        except Exception:
            pass
    else:
        LOCAL_ALERTS_LOG.append({
            "timestamp": t_str, "sender": sender_name, "zone": zone, 
            "message": clean_msg, "type": alert_type, "status": "Active"
        })


def update_incident_status(alert_id, target_status="Resolved"):
    """Updates active triage status variables inside the active execution array."""
    db = load_db()
    logs = db["alerts_log"]
    if 0 <= alert_id < len(logs):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if IS_CLOUD_ACTIVE:
            try:
                g = logs[alert_id]
                clean_msg = g['message'].replace("|", " ").replace("=", " ")
                updated_str = f"time={g['timestamp']}|sender={g['sender']}|zone={g['zone']}|msg={clean_msg}|type={g['type']}|status={target_status}|res_at={now_str}"
                requests.post(f"{REDIS_URL}/lset/alerts_log/{alert_id}/{updated_str}", headers=HEADERS, timeout=5)
                return True
            except Exception:
                return False
        else:
            LOCAL_ALERTS_LOG[alert_id]["status"] = target_status
            return True
    return False
