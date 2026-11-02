import json
import os
from datetime import datetime

# 🌟 THE ABSOLUTE ENV SEPARATION FIX:
# Render automatically injects an environment variable called "RENDER" into its cloud servers.
# If "RENDER" is detected, it locks onto an isolated cloud file path.
# Otherwise, it locks onto your local MacBook folder path. They can NEVER overwrite each other again!
if os.getenv("RENDER"):
    DB_FILE = "render_farmers_db.json"  # Isolated entirely to your Render cloud node instance
else:
    DB_FILE = "/Users/mackbook/Documents/farm watch/farmers_db.json"  # Isolated entirely to your MacBook laptop

def clean_phone_number(phone: str) -> str:
    """Removes spaces, dashes, brackets, and formatting to normalize keys."""
    return phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "").replace("whatsapp:", "")

def initialize_db():
    """Initializes a clean database JSON structure if the file doesn't exist or is empty."""
    if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) == 0:
        blank_structure = {
            "farmers": {},
            "alerts_log": []
        }
        with open(DB_FILE, "w") as f:
            json.dump(blank_structure, f, indent=4)
        print(f"🆕 [DATABASE ENGINE] Initialized clean, isolated data file ledger at: {DB_FILE}")

def load_db():
    """Pulls data straight from the active environment file path."""
    initialize_db()
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    """Writes updates instantly directly onto the active disk storage path."""
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
