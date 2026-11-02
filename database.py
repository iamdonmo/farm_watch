import json
import os
from datetime import datetime

# Absolute hard-locked path on your MacBook
DB_FILE = "/Users/mackbook/Documents/farm watch/farmers_db.json"

def clean_phone_number(phone: str) -> str:
    """Removes spaces, dashes, brackets, and formatting to normalize keys."""
    return phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "").replace("whatsapp:", "")

def initialize_db():
    """
    Creates a clean, blank database framework ONLY if the file does not exist.
    It no longer carries the starter numbers, so it will NEVER overwrite your edits!
    """
    folder_path = os.path.dirname(DB_FILE)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path, exist_ok=True)
        
    if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) == 0:
        # We start with a completely empty ledger framework
        blank_structure = {
            "farmers": {},
            "alerts_log": []
        }
        with open(DB_FILE, "w") as f:
            json.dump(blank_structure, f, indent=4)
        print(f"🆕 Created a clean, permanent database file ledger at: {DB_FILE}")

def load_db():
    """Pulls directly from your MacBook file disk with zero default overrides."""
    initialize_db()
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    """Writes changes instantly and directly onto your MacBook disk file."""
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print(f"💾 [DISK UPDATE COMPLETE] Saved directly to: {DB_FILE}")

def remove_farmer(phone_number):
    db = load_db()
    clean_phone = clean_phone_number(phone_number)
    if clean_phone in db["farmers"]:
        del db["farmers"][clean_phone]
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
