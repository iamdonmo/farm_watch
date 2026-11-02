import json
import os
from datetime import datetime

# The Compatibility Switch (Render Cloud Linux vs. Your MacBook Local)
IF_RENDER_CLOUD = "/data/farmers_db.json"
IF_MACKBOOK_LOCAL = "/Users/mackbook/Documents/farm watch/farmers_db.json"

DB_FILE = IF_RENDER_CLOUD if os.path.exists("/data") else IF_MACKBOOK_LOCAL


def clean_phone_number(phone: str) -> str:
    """Removes spaces, dashes, brackets, and formatting to normalize keys."""
    return phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "").replace("whatsapp:", "")


def initialize_db():
    """Creates a clean, blank database framework ONLY if the file does not exist."""
    folder_path = os.path.dirname(DB_FILE)
    if folder_path and not os.path.exists(folder_path):
        try:
            os.makedirs(folder_path, exist_ok=True)
        except Exception:
            pass

    if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) == 0:
        blank_structure = {
            "farmers": {},
            "alerts_log": []
        }
        with open(DB_FILE, "w") as f:
            json.dump(blank_structure, f, indent=4)
        print(f"🆕 [DATABASE ENGINE] Initialized clean database file ledger at: {DB_FILE}")


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
    """Appends an operational threat record straight to the file timeline archive."""
    db = load_db()
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    incident_record = {
        "timestamp": timestamp_str,
        "sender": sender_name,
        "zone": zone,
        "message": message,
        "type": alert_type,  # Captures category (e.g., Critical, Intruder, Missing Asset)
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
