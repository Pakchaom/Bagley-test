"""bagley/voice/teach_store.py — เก็บคำที่สอนไว้ "แยกตามคน" (ไฟล์ voice_teach.json ข้างๆ bot.py)

{ "users": { "<discord_id>": { "wake": ["แบล็ค", ...],
                                "commands": [ {"send": "/tts on", "phrases": [...], "args": false}, ... ] } } }
"""
from __future__ import annotations

import json
import os
import threading

from bagley.voice.matching import norm

PATH = os.getenv("VOICE_TEACH_FILE", "voice_teach.json")
_lock = threading.Lock()


def _load() -> dict:
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"users": {}}
    except FileNotFoundError:
        return {"users": {}}
    except Exception:
        return {"users": {}}


def _save(data: dict) -> None:
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)


def get_user(uid: int) -> dict:
    with _lock:
        u = _load().get("users", {}).get(str(uid), {})
    return {"wake": list(u.get("wake", [])),
            "commands": [dict(c, phrases=list(c.get("phrases", []))) for c in u.get("commands", [])]}


def save_teach(uid: int, kind: str, phrases: list, send: str = "", args: bool = False):
    """kind = 'wake' | 'cmd'  คืน (เพิ่มกี่วลี, รายการที่ข้ามพร้อมเหตุผล)"""
    added, skipped = 0, []
    with _lock:
        data = _load()
        users = data.setdefault("users", {})
        u = users.setdefault(str(uid), {"wake": [], "commands": []})
        u.setdefault("wake", [])
        u.setdefault("commands", [])
        if kind == "wake":
            have = {norm(x) for x in u["wake"]}
            for p in phrases:
                pn = norm(p)
                if len(pn) < 2:
                    skipped.append(f"{p} (สั้นเกินไป)")
                elif pn in have:
                    continue
                else:
                    u["wake"].append(p)
                    have.add(pn)
                    added += 1
        else:
            target = next((c for c in u["commands"] if str(c.get("send", "")).strip().lower() == send.lower()), None)
            is_new = target is None
            if is_new:
                target = {"send": send, "phrases": [], "args": False}
            if args:
                target["args"] = True
            for p in phrases:
                pn = norm(p)
                if len(pn) < 2:
                    skipped.append(f"{p} (สั้นเกินไป)")
                    continue
                clash = next((c for c in u["commands"] if c is not target
                              and any(norm(x) == pn for x in c.get("phrases", []))), None)
                if clash:
                    skipped.append(f"{p} (ซ้ำกับ {clash.get('send')})")
                    continue
                if not any(norm(x) == pn for x in target["phrases"]):
                    target["phrases"].append(p)
                    added += 1
            if target["phrases"] and is_new:
                u["commands"].append(target)
        _save(data)
    return added, skipped


def delete_items(uid: int, command_indexes: list, wake_all: bool = False) -> list:
    """ลบคำสั่งตามลำดับ (เริ่ม 0) และ/หรือล้างชื่อเรียกทั้งหมด คืนชื่อที่ลบ"""
    removed = []
    with _lock:
        data = _load()
        u = data.get("users", {}).get(str(uid))
        if not u:
            return removed
        for i in sorted(set(command_indexes), reverse=True):
            if 0 <= i < len(u.get("commands", [])):
                removed.append(str(u["commands"].pop(i).get("send", "?")))
        if wake_all and u.get("wake"):
            u["wake"] = []
            removed.append("ชื่อเรียกแบ็คลี่")
        _save(data)
    return list(reversed(removed))
