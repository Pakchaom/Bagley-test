"""
Storage utilities for handling JSON data and database operations
"""
import json
import sqlite3
import os
from config.config import (
    SERVER_SETTINGS_FILE,
    USER_DATA_FILE,
    VOICE_STATS_FILE,
    DATABASE_PATH
)

# Ensure data directory exists
os.makedirs('data', exist_ok=True)


def save_settings(data):
    """Save server settings to JSON file"""
    with open(SERVER_SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)


def load_settings():
    """Load server settings from JSON file"""
    try:
        with open(SERVER_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_user_data(data):
    """Save user data to JSON file"""
    with open(USER_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_user_data():
    """Load user data from JSON file"""
    try:
        with open(USER_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_voice_data(data):
    """Save voice statistics to JSON file"""
    with open(VOICE_STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_voice_data():
    """Load voice statistics from JSON file"""
    try:
        with open(VOICE_STATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_reminders(reminders):
    """Save reminders to JSON file"""
    with open(REMINDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(reminders, f, ensure_ascii=False, indent=4)


def load_reminders():
    """Load reminders from JSON file"""
    if os.path.exists(REMINDERS_FILE):
        with open(REMINDERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def get_database_connection():
    """Get SQLite database connection"""
    return sqlite3.connect(DATABASE_PATH, check_same_thread=False)


def get_reminders_for_user(user_id):
    """Get pending reminders for a specific user"""
    data = load_user_data()
    reminders = data.get("reminders", [])
    
    user_notes = [r['content'] for r in reminders 
                  if r['user_id'] == str(user_id) and not r.get('is_notified', False)]
    
    return ", ".join(user_notes) if user_notes else None


def add_reminder(user_id, time_str, content):
    """Add a new reminder for a user"""
    data = load_user_data()
    if "reminders" not in data:
        data["reminders"] = []
    
    new_memo = {
        "user_id": str(user_id),
        "time": time_str,
        "content": content,
        "is_notified": False
    }
    data["reminders"].append(new_memo)
    save_user_data(data)


REMINDERS_FILE = 'data/check_friend_reminders.json'
