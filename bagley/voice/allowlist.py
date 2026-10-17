"""bagley/voice/allowlist.py — รายชื่อคนที่แบ็คลี่ "ฟังคำสั่งพูดด้วยเสียง" ในห้องเสียงได้

มี 2 กลุ่ม:
  1) กลุ่มหลัก (ตายตัวใน core/config.py: ผู้พัฒนา + ALLOWED_USERS + ผู้ใช้ Voice Relay) -> ลบไม่ได้
  2) กลุ่มที่ผู้พัฒนาเพิ่มเองด้วยคำสั่ง /voice_user_add -> เก็บในไฟล์ voice_allowlist.json
     (อยู่รอดหลังรีสตาร์ท เพิ่ม/ลบ/ดูรายการได้โดยไม่ต้องแก้โค้ด)

is_allowed() ถูกเรียกทุกแพ็กเก็ตเสียงที่เข้ามา จึงอ่านจากแรมล้วนๆ (เซ็ต) ไม่แตะดิสก์
เขียนไฟล์เฉพาะตอนเพิ่ม/ลบ และเขียนแบบอะตอมมิก (temp -> replace) กันไฟล์พังตอนไฟดับ/ปิดโปรแกรมกลางคัน
"""
from __future__ import annotations

import json
import os
import threading
import time

from bagley.core.config import (
    ALLOWED_TEACH_USERS,
    ALLOWED_USERS,
    OWNER_DISCORD_ID,
    VOICE_RELAY_ALLOWED_OWNER_IDS,
)
from bagley.core.logutil import print

FILE = os.getenv("VOICE_ALLOWLIST_FILE", "voice_allowlist.json")

_lock = threading.Lock()
_entries: dict[int, dict] = {}      # uid -> {"name": str, "added_by": int, "added_at": float}
_ids: frozenset[int] = frozenset()  # สำเนาอ่านอย่างเดียวสำหรับเช็คเร็วๆ ในเธรดรับเสียง
_loaded = False


def base_ids() -> set[int]:
    """กลุ่มหลักที่ลบไม่ได้"""
    return {OWNER_DISCORD_ID, *ALLOWED_TEACH_USERS, *ALLOWED_USERS, *VOICE_RELAY_ALLOWED_OWNER_IDS}


def is_developer(user_id: int) -> bool:
    """ผู้พัฒนา = เจ้าของบอท + ALLOWED_TEACH_USERS (เกณฑ์เดียวกับ @is_developer() ใน core/security.py)"""
    return user_id == OWNER_DISCORD_ID or user_id in ALLOWED_TEACH_USERS


def _refresh_ids() -> None:
    global _ids
    _ids = frozenset(_entries)


def _load() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        if not os.path.exists(FILE):
            return
        try:
            with open(FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in (raw.get("users") or {}).items():
                uid = int(k)
                v = v if isinstance(v, dict) else {}
                _entries[uid] = {
                    "name": str(v.get("name") or ""),
                    "added_by": int(v.get("added_by") or 0),
                    "added_at": float(v.get("added_at") or 0),
                }
        except Exception as e:  # noqa: BLE001
            # ไฟล์พัง: เก็บไฟล์เดิมไว้เป็น .corrupt (ไม่ทับ/ไม่ทิ้ง) แล้วเริ่มจากรายชื่อว่าง ไม่ให้บอทล้ม
            bad = f"{FILE}.corrupt-{int(time.time())}"
            try:
                os.replace(FILE, bad)
            except OSError:
                bad = "(ย้ายไม่ได้)"
            _entries.clear()
            print(f"⚠️ [VoiceAllow] อ่าน {FILE} ไม่ได้ ({type(e).__name__}: {e}) -> เก็บไฟล์เดิมไว้ที่ {bad} และเริ่มรายชื่อว่าง")
        _refresh_ids()


def _save_locked() -> None:
    data = {"users": {str(uid): e for uid, e in _entries.items()}}
    tmp = f"{FILE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, FILE)


def is_allowed(user_id: int) -> bool:
    """แบ็คลี่ควรฟังเสียง/ยอมให้ใช้ระบบสอนเสียงของคนนี้ไหม"""
    if not _loaded:
        _load()
    return user_id in _ids or user_id in base_ids()


def add(user_id: int, name: str, added_by: int) -> str:
    """คืน 'added' | 'exists' | 'base' (อยู่ในกลุ่มหลักแล้ว ไม่ต้องเพิ่ม)"""
    _load()
    if user_id in base_ids():
        return "base"
    with _lock:
        if user_id in _entries:
            _entries[user_id]["name"] = name or _entries[user_id].get("name", "")
            try:
                _save_locked()
            except OSError:
                pass
            return "exists"
        _entries[user_id] = {"name": name or "", "added_by": int(added_by), "added_at": time.time()}
        try:
            _save_locked()
        except OSError as e:
            del _entries[user_id]          # เขียนไฟล์ไม่ได้ = ไม่ถือว่าเพิ่มสำเร็จ (กันหลอกว่าเพิ่มแล้วแต่รีสตาร์ทหาย)
            raise RuntimeError(f"บันทึกไฟล์ไม่สำเร็จ: {e}") from e
        _refresh_ids()
    return "added"


def remove(user_id: int) -> str:
    """คืน 'removed' | 'missing' | 'base' (กลุ่มหลักลบไม่ได้)"""
    _load()
    if user_id in base_ids():
        return "base"
    with _lock:
        if user_id not in _entries:
            return "missing"
        old = _entries.pop(user_id)
        try:
            _save_locked()
        except OSError as e:
            _entries[user_id] = old
            raise RuntimeError(f"บันทึกไฟล์ไม่สำเร็จ: {e}") from e
        _refresh_ids()
    return "removed"


def list_entries() -> list[tuple[int, dict]]:
    """รายชื่อที่เพิ่มเอง เรียงตามเวลาที่เพิ่ม"""
    _load()
    with _lock:
        return sorted(((uid, dict(e)) for uid, e in _entries.items()), key=lambda x: x[1].get("added_at", 0))
