import json
import os
from datetime import datetime

# Forces the application to target your exact hard drive json file path
DB_FILE = "farmers_db.json"

def clean_phone_number(phone: str) -> str:
    """Removes spaces, dashes, brackets, and formatting to normalize keys."""
    return phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

def initialize_db():
    """Seeds default testing farmers directly into your local JSON file if it doesn't exist."""
    if not os.path.exists(DB_FILE):
        initial_data = {
            "farmers": {
                "+2348030001111": {"name": "Kofi", "zone": "Zone_North"},
                "+2348030002222": {"name": "Amadi", "zone": "Zone_North"},
                "+2348030003333": {"name": "Chidi", "zone": "Zone_North"},
                "+2348030004444": {"name": "Musa", "zone": "Zone_South"},
            },
            "alerts_log": []
        }
        with open(DB_FILE, "w") as f:
            json.dump(initial_data, f, indent=4)

def load_db():
    """Forces the script to pull data straight from the physical hard drive file every time."""
    initialize_db()
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    """Commits updates instantly into the physical hard drive json file."""
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print("💾 [DATABASE FILE SYNCED] Changes written successfully to farmers_db.json")

def remove_farmer(phone_number):
    """Safely erases a farmer from the json file mapping."""
    db = load_db()
    clean_phone = clean_phone_number(phone_number)
    if clean_phone in db["farmers"]:
        del db["farmers"][clean_phone]
        save_db(db)
        return True
    return False

def archive_incident(sender_name, zone, message, alert_type="Standard"):
    """Appends an operational threat record straight to the file timeline archive."""
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
    """Updates active triage status variables inside the physical file."""
    db = load_db()
    if 0 <= alert_id < len(db["alerts_log"]):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db["alerts_log"][alert_id]["status"] = target_status
        db["alerts_log"][alert_id]["resolved_at"] = now_str
        save_db(db)
        return True
    return False
