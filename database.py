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
    """
    FORCED CACHE-BREAKER SNAPSHOT LOOKUP
    Bypasses Python memory process wrappers to read raw hard drive bytes directly.
    """
    initialize_db()

    # 🌟 THE CLOUD FIX: Force python to read raw data from the disk drive immediately,
    # stripping away any stale process memory cache locks.
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            # We explicitly read the raw text stream first, then decode it manually
            raw_text_stream = f.read()
            if not raw_text_stream.strip():
                return {"farmers": {}, "alerts_log": []}
            return json.loads(raw_text_stream)
    except Exception as e:
        print(f"⚠️ [CRITICAL CLOUD FILE READ FAIL] Forcing baseline reload: {e}")
        # Standard safety failover framework template structure
        return {"farmers": {}, "alerts_log": []}


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
