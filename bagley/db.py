"""bagley/db.py — ฐานข้อมูล SQLite (เปิดโหมด WAL = เขียน/อ่านพร้อมกันได้ เร็วขึ้น และมี index)"""
import sqlite3

DB_PATH = "bagley_memory.db"

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
for _pragma in ("journal_mode=WAL", "synchronous=NORMAL", "temp_store=MEMORY", "cache_size=-8000"):
    try:
        conn.execute(f"PRAGMA {_pragma}")
    except sqlite3.DatabaseError:
        pass


def init_db():
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS chat_history (user_id INTEGER, role TEXT, text TEXT)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_chat_history_user ON chat_history(user_id)')
    c.execute('''CREATE TABLE IF NOT EXISTS youtube_channels (channel_id TEXT PRIMARY KEY, channel_name TEXT, last_video_id TEXT, guild_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS youtube_settings (guild_id TEXT PRIMARY KEY, target_channel_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS registration_settings(guild_id INTEGER PRIMARY KEY, questions TEXT, target_role_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_status(user_id TEXT PRIMARY KEY, status_message TEXT, is_away INTEGER, timestamp DATETIME)''')
    c.execute('''CREATE TABLE IF NOT EXISTS teach_memory (keyword TEXT PRIMARY KEY, response TEXT)''')
    conn.commit()


def save_message(user_id, role, text):
    conn.execute("INSERT INTO chat_history VALUES (?, ?, ?)", (user_id, role, text))
    conn.commit()


def load_history(user_id, limit: int = 30):
    rows = conn.execute(
        "SELECT role, text FROM (SELECT rowid AS rid, role, text FROM chat_history WHERE user_id = ? "
        "ORDER BY rid DESC LIMIT ?) ORDER BY rid ASC", (user_id, limit)).fetchall()
    return [{"role": r[0], "parts": [{"text": r[1]}]} for r in rows]


init_db()
