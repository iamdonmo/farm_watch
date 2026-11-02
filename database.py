import json
import os
from datetime import datetime

# Automated environment detection switch
if os.getenv("RENDER"):
    DB_FILE = "render_farmers_db.json"
else:
    DB_FILE = "/Users/mackbook/Documents/farm watch/farmers_db.json"

def clean_phone_number(phone: str) -> str:
    """Removes spaces, dashes, brackets, and formatting to normalize keys."""
    return phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "").replace("whatsapp:", "")

def get_default_data():
    """Generates foundational members who are ALREADY approved to break the login loop!"""
    return {
        "farmers": {
            "+2347015614407": {"name": "Kofi", "zone": "Zone_North", "status": "Approved"},
            "+2347015614407": {"name": "Amadi", "zone": "Zone_North", "status": "Approved"},
            "2348030003333": {"name": "Chidi", "zone": "Zone_North", "status": "Approved"},
            "2348030004444": {"name": "Musa", "zone": "Zone_South", "status": "Approved"},
        },
        "alerts_log": []
    }

def initialize_db():
    """Seeds the baseline network structure if the file is missing or corrupted."""
    folder_path = os.path.dirname(DB_FILE)
    if folder_path and not os.path.exists(folder_path):
        os.makedirs(folder_path, exist_ok=True)
        
    if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) == 0:
        with open(DB_FILE, "w") as f:
            json.dump(get_default_data(), f, indent=4)
        print(f"🆕 [DATABASE ENGINE] Seeded structural file matrix at: {DB_FILE}")

def load_db():
    initialize_db()
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print(f"💾 [DISK UPDATE] Successfully saved data changes to: {DB_FILE}")

def remove_farmer(phone_number):
    db = load_db()
    clean_phone = clean_phone_number(phone_number)
    if clean_phone in db["farmers"]:
        del db["farmers"][clean_phone]
        save_db(db)
        return True
    return False

def approve_farmer_node(phone_number):
    """Upgrades a pending farmer node to approved status."""
    db = load_db()
    clean_phone = clean_phone_number(phone_number)
    if clean_phone in db["farmers"]:
        db["farmers"][clean_phone]["status"] = "Approved"
        save_db(db)
        return True
    return False

def archive_incident(sender_name, zone, message, alert_type="Standard"):
    db = load_db()
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    incident_record = {
        "timestamp": timestamp_str,
        "sender": sender_name,
        "zone": zone,
        "message": message,
        "type": alert_type,
        "status": "Active"
    }
    db["alerts_log"].append(incident_record)
    save_db(db)
    return incident_record

def update_incident_status(alert_id, target_status="Resolved"):
    db = load_db()
    if 0 <= alert_id < len(db["alerts_log"]):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db["alerts_log"][alert_id]["status"] = target_status
        db["alerts_log"][alert_id]["resolved_at"] = now_str
        save_db(db)
        return True
    return False
