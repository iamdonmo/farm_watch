import json
import os
from datetime import datetime

# Saves inside Render's persistent folder if online, otherwise saves locally
DB_FILE = "/data/farmers_db.json" if os.path.exists("/data") else "farmers_db.json"



def initialize_db():
    if not os.path.exists(DB_FILE):
        initial_data = {
            "farmers": {
                "+2347015614407": {"name": "Kofi", "zone": "Zone_North"},
                "+2347063873827": {"name": "Amadi", "zone": "Zone_North"},
                "+2347015614407": {"name": "Chidi", "zone": "Zone_North"},
                "+2347015614407": {"name": "Musa", "zone": "Zone_South"},
            },
            "alerts_log": []
        }
        with open(DB_FILE, "w") as f:
            json.dump(initial_data, f, indent=4)


def load_db():
    initialize_db()
    with open(DB_FILE, "r") as f:
        return json.load(f)


def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)


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


def remove_farmer(phone_number):
    """Locates a farmer by their phone number key and erases them from disk."""
    db = load_db()
    clean_phone = phone_number.strip()

    if clean_phone in db["farmers"]:
        # Delete the farmer key entirely from our dictionary mapping
        del db["farmers"][clean_phone]
        save_db(db)
        return True
    return False
