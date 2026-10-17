"""ทดสอบรายชื่อคนที่บอทฟังเสียง + คำสั่ง /voice_user_* (ต้องเป็นผู้พัฒนาเท่านั้น)
รัน: PYTHONPATH=. python3 tests/test_voice_allowlist.py"""
import asyncio
import importlib
import json
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ["VOICE_ALLOWLIST_FILE"] = os.path.join(TMP, "voice_allowlist.json")
os.environ.setdefault("DISCORD_TOKEN", "x")

from bagley.core import config  # noqa: E402
from bagley.voice import allowlist as al  # noqa: E402

bad = 0


def check(name, cond, info=""):
    global bad
    print(("PASS" if cond else "FAIL"), name, info)
    bad += (not cond)


DEV = config.OWNER_DISCORD_ID
STRANGER, FRIEND, FRIEND2 = 111, 222, 333

check("stranger not allowed by default", not al.is_allowed(STRANGER))
check("developer always allowed", al.is_allowed(DEV))
check("is_developer: owner", al.is_developer(DEV))
check("is_developer: stranger no", not al.is_developer(STRANGER))

check("add new -> added", al.add(FRIEND, "เพื่อน", DEV) == "added")
check("added user is allowed", al.is_allowed(FRIEND))
check("add again -> exists", al.add(FRIEND, "เพื่อน", DEV) == "exists")
check("add base id -> base (ไม่เพิ่มซ้ำ)", al.add(DEV, "x", DEV) == "base")
check("add many", al.add(FRIEND2, "อีกคน", DEV) == "added")
check("list has both, in order", [u for u, _ in al.list_entries()] == [FRIEND, FRIEND2])

# persisted on disk, valid JSON
raw = json.load(open(os.environ["VOICE_ALLOWLIST_FILE"], encoding="utf-8"))
check("persisted to file", set(raw["users"]) == {str(FRIEND), str(FRIEND2)})
check("no stray tmp files", not [f for f in os.listdir(TMP) if f.endswith(".tmp")])

# survives restart (reload module state)
al._entries.clear(); al._refresh_ids(); al._loaded = False
check("reload from disk after restart", al.is_allowed(FRIEND) and al.is_allowed(FRIEND2))

check("remove -> removed", al.remove(FRIEND) == "removed")
check("removed user no longer allowed", not al.is_allowed(FRIEND))
check("remove again -> missing", al.remove(FRIEND) == "missing")
check("cannot remove base/developer", al.remove(DEV) == "base" and al.is_allowed(DEV))
al._entries.clear(); al._refresh_ids(); al._loaded = False
check("removal persisted across restart", not al.is_allowed(FRIEND) and al.is_allowed(FRIEND2))

# corrupt file must not crash and must be preserved
with open(os.environ["VOICE_ALLOWLIST_FILE"], "w", encoding="utf-8") as f:
    f.write("{not json")
al._entries.clear(); al._refresh_ids(); al._loaded = False
check("corrupt file -> no crash, empty list", not al.is_allowed(FRIEND2))
check("corrupt file kept as .corrupt-*", any(".corrupt-" in f for f in os.listdir(TMP)))
check("can add again after corruption", al.add(FRIEND, "เพื่อน", DEV) == "added")

# ---- commands: only developers ----
import bot  # noqa: E402,F401  (ลงทะเบียนคำสั่งทั้งหมด)
from bagley.core.app import bot as discord_bot  # noqa: E402


class FakeAuthor:
    def __init__(self, uid):
        self.id = uid
    def __str__(self):
        return f"u{self.id}"


class FakeCtx:
    def __init__(self, uid):
        self.author = FakeAuthor(uid)
        self.sent = []
    async def send(self, content=None, **kw):
        self.sent.append(content)


class FakeUser:
    def __init__(self, uid, bot_=False):
        self.id, self.bot, self.display_name, self.name = uid, bot_, f"n{uid}", f"n{uid}"


def run(cmd, uid, *args):
    ctx = FakeCtx(uid)
    asyncio.run(discord_bot.get_command(cmd).callback(ctx, *args))
    return ctx.sent


before = set(u for u, _ in al.list_entries())
out = run("voice_user_add", STRANGER, FakeUser(999))
check("non-dev cannot add", "จำกัดสิทธิ์" in (out[0] or "") and not al.is_allowed(999), str(out)[:60])
out = run("voice_user_remove", STRANGER, FakeUser(FRIEND))
check("non-dev cannot remove", al.is_allowed(FRIEND), str(out)[:60])
out = run("voice_user_list", STRANGER)
check("non-dev cannot list", "จำกัดสิทธิ์" in (out[0] or ""))
out = run("voice_user_add", FRIEND, FakeUser(999))
check("an added friend cannot add others (ไม่ใช่ผู้พัฒนา)", not al.is_allowed(999))

out = run("voice_user_add", DEV, FakeUser(999))
check("developer can add", al.is_allowed(999), str(out)[:50])
out = run("voice_user_add", DEV, FakeUser(555, bot_=True))
check("cannot add a bot", not al.is_allowed(555))
out = run("voice_user_list", DEV)
check("developer can list (shows added user)", "999" in (out[0] or ""))
out = run("voice_user_remove", DEV, FakeUser(999))
check("developer can remove", not al.is_allowed(999), str(out)[:50])
out = run("voice_user_remove", DEV, FakeUser(DEV))
check("developer cannot remove base id", al.is_allowed(DEV))

# router must not expose these to the AI
from bagley.ai import router  # noqa: E402
check("excluded from AI router", {"voice_user_add", "voice_user_remove", "voice_user_list"} <= router.AI_ROUTER_EXCLUDED_COMMANDS)

print("FAILED:", bad)
sys.exit(1 if bad else 0)
