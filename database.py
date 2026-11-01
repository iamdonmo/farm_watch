import os
from datetime import datetime

# 🌟 THE ZERO-DISK STRATEGY: Create an active global memory dictionary block!
# This dictionary lives inside Render's system RAM, making updates instant.
GLOBAL_FARMER_RAM = {
    "+2348030001111": {"name": "Kofi", "zone": "Zone_North"},
    "+2348030002222": {"name": "Amadi", "zone": "Zone_North"},
    "+2348030003333": {"name": "Chidi", "zone": "Zone_North"},
    "+2348030004444": {"name": "Musa", "zone": "Zone_South"},
}

GLOBAL_ALERTS_LOG = []

def clean_phone_number(phone: str) -> str:
    """Removes spaces, dashes, brackets, and leading padding to normalize the database key."""
    return phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

def initialize_db():
    """No disk file required in memory-routing mode."""
    pass

def load_db():
    """Returns the live memory state instantly, skipping stale hard drive lookups."""
    return {
        "farmers": GLOBAL_FARMER_RAM,
        "alerts_log": GLOBAL_ALERTS_LOG
    }

def save_db(data):
    """Saves updates by securely writing them directly into the RAM cache memory spaces."""
    global GLOBAL_FARMER_RAM, GLOBAL_ALERTS_LOG
    GLOBAL_FARMER_RAM = data["farmers"]
    GLOBAL_ALERTS_LOG = data["alerts_log"]

def remove_farmer(phone_number):
    """Safely erases a farmer from memory using their cleaned number string."""
    clean_phone = clean_phone_number(phone_number)
    if clean_phone in GLOBAL_FARMER_RAM:
        del GLOBAL_FARMER_RAM[clean_phone]
        return True
    return False

def archive_incident(sender_name, zone, message, alert_type="Standard"):
    """Appends an operational incident record straight into memory logs."""
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    incident_record = {
        "timestamp": timestamp_str,
        "sender": sender_name,
        "zone": zone,
        "message": message,
        "type": alert_type,
        "status": "Active"
    }
    GLOBAL_ALERTS_LOG.append(incident_record)
    return incident_record

def update_incident_status(alert_id, target_status="Resolved"):
    """Updates status variables instantly inside the active live array lists."""
    if 0 <= alert_id < len(GLOBAL_ALERTS_LOG):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        GLOBAL_ALERTS_LOG[alert_id]["status"] = target_status
        GLOBAL_ALERTS_LOG[alert_id]["resolved_at"] = now_str
        return True
    return False
