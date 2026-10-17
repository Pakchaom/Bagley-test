"""bagley/commands/voice_access.py — จัดการรายชื่อคนที่แบ็คลี่ฟังคำสั่งพูดด้วยเสียง (เฉพาะผู้พัฒนา)

  /voice_user_add    user:@ชื่อ หรือ ไอดี   เพิ่มคนที่แบ็คลี่จะฟังเสียง
  /voice_user_remove user:@ชื่อ หรือ ไอดี   ลบออก
  /voice_user_list                          ดูรายชื่อทั้งหมด (กลุ่มหลัก + ที่เพิ่มไว้) และเลือกลบได้จากเมนู

คนที่ถูกเพิ่มจะ "ได้ยินเสียง + สอนคำเรียกของตัวเองได้" เท่านั้น — คำสั่งที่พูดยังผ่านระบบสิทธิ์เดียวกับการพิมพ์ในแชท
(คำสั่งระดับผู้พัฒนา เช่น shutdown/update ยังใช้ไม่ได้) รายชื่อเก็บใน voice_allowlist.json (bagley/voice/allowlist.py)
"""
from __future__ import annotations

import datetime as _dt

import discord
from discord.ext import commands

from bagley.commands import listen as _listen
from bagley.core.app import bot
from bagley.core.config import bangkok_tz
from bagley.core.logutil import print
from bagley.voice import allowlist


async def _dev_only(ctx: commands.Context) -> bool:
    if not allowlist.is_developer(ctx.author.id):
        await ctx.send("🛑 คำสั่งนี้จำกัดสิทธิ์เฉพาะผู้พัฒนาบอทเท่านั้นครับ", ephemeral=True)
        return False
    return True


def _label(uid: int, name: str = "") -> str:
    return f"{name} (`{uid}`)" if name else f"`{uid}`"


async def _resolve_name(user: discord.abc.User) -> str:
    return getattr(user, "display_name", None) or getattr(user, "name", "") or ""


@bot.hybrid_command(name="voice_user_add", description="[Developer Only] เพิ่มคนที่แบ็คลี่จะฟังคำสั่งพูดด้วยเสียง (ใส่ @ชื่อ หรือไอดี)")
async def voice_user_add(ctx: commands.Context, user: discord.User):
    if not await _dev_only(ctx):
        return
    if user.bot:
        await ctx.send("❌ เพิ่มบอทไม่ได้ครับ (แบ็คลี่ไม่ฟังเสียงบอท)", ephemeral=True)
        return
    name = await _resolve_name(user)
    try:
        result = allowlist.add(user.id, name, ctx.author.id)
    except RuntimeError as e:
        await ctx.send(f"❌ {e}", ephemeral=True)
        return
    if result == "added":
        print(f"🎙️ [VoiceAllow] {ctx.author} เพิ่ม {user} ({user.id}) เข้ารายชื่อฟังเสียง")
        await ctx.send(f"✅ เพิ่ม {_label(user.id, name)} เข้ารายชื่อแล้วครับ — แบ็คลี่จะฟังเสียงเขาได้ทันที "
                       f"(ถ้าเปิด `/listen on` อยู่) ให้เขาลอง `/voice_teach_wake` สอนชื่อเรียกของตัวเองได้", ephemeral=True)
    elif result == "exists":
        await ctx.send(f"ℹ️ {_label(user.id, name)} อยู่ในรายชื่ออยู่แล้วครับ (อัปเดตชื่อให้แล้ว)", ephemeral=True)
    else:
        await ctx.send(f"ℹ️ {_label(user.id, name)} อยู่ในกลุ่มหลักของบอทอยู่แล้ว ไม่ต้องเพิ่มครับ", ephemeral=True)


@bot.hybrid_command(name="voice_user_remove", description="[Developer Only] ลบคนออกจากรายชื่อที่แบ็คลี่ฟังเสียง (ใส่ @ชื่อ หรือไอดี)")
async def voice_user_remove(ctx: commands.Context, user: discord.User):
    if not await _dev_only(ctx):
        return
    await ctx.send(await _do_remove(user.id, await _resolve_name(user), ctx.author), ephemeral=True)


async def _do_remove(uid: int, name: str, actor) -> str:
    try:
        result = allowlist.remove(uid)
    except RuntimeError as e:
        return f"❌ {e}"
    if result == "removed":
        _listen.forget_user(uid)
        print(f"🎙️ [VoiceAllow] {actor} ลบ {uid} ออกจากรายชื่อฟังเสียง")
        return f"🗑️ ลบ {_label(uid, name)} ออกจากรายชื่อแล้วครับ — แบ็คลี่เลิกฟังเสียงเขาทันที"
    if result == "base":
        return f"🔒 {_label(uid, name)} เป็นกลุ่มหลักของบอท (ตั้งไว้ใน config) ลบผ่านคำสั่งไม่ได้ครับ"
    return f"ℹ️ {_label(uid, name)} ไม่ได้อยู่ในรายชื่อที่เพิ่มไว้ครับ"


def _fmt_time(ts: float) -> str:
    if not ts:
        return "-"
    return _dt.datetime.fromtimestamp(ts, bangkok_tz).strftime("%d/%m/%y %H:%M")


class _RemoveView(discord.ui.View):
    def __init__(self, owner_id: int, entries: list[tuple[int, dict]]):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.names = {uid: e.get("name", "") for uid, e in entries}
        self.selected: set[str] = set()
        opts = [discord.SelectOption(label=(e.get("name") or str(uid))[:90], description=str(uid), value=str(uid))
                for uid, e in entries[:25]]
        self._sel = discord.ui.Select(placeholder="เลือกคนที่จะลบออก", min_values=1, max_values=len(opts), options=opts)
        self._sel.callback = self._on_select
        self.add_item(self._sel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or not allowlist.is_developer(interaction.user.id):
            await interaction.response.send_message("เมนูนี้เฉพาะผู้พัฒนาที่เรียกคำสั่งครับ", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        self.selected = set(self._sel.values)
        await interaction.response.defer()

    @discord.ui.button(label="ลบที่เลือก", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected:
            await interaction.response.send_message("เลือกรายชื่อก่อนครับ", ephemeral=True)
            return
        lines = [await _do_remove(int(v), self.names.get(int(v), ""), interaction.user) for v in self.selected]
        self.stop()
        await interaction.response.edit_message(content="\n".join(lines), view=None)


@bot.hybrid_command(name="voice_user_list", description="[Developer Only] ดูรายชื่อคนที่แบ็คลี่ฟังคำสั่งเสียง และเลือกลบได้")
async def voice_user_list(ctx: commands.Context):
    if not await _dev_only(ctx):
        return
    entries = allowlist.list_entries()
    lines = [f"🎙️ **รายชื่อที่แบ็คลี่ฟังเสียง** (เพิ่มไว้ {len(entries)} คน)"]
    if entries:
        for i, (uid, e) in enumerate(entries, 1):
            adder = f"<@{e['added_by']}>" if e.get("added_by") else "-"
            lines.append(f"{i}. {_label(uid, e.get('name', ''))} — เพิ่มโดย {adder} เมื่อ {_fmt_time(e.get('added_at', 0))}")
    else:
        lines.append("_(ยังไม่มีใครที่เพิ่มไว้ — ใช้ `/voice_user_add`)_")
    base = sorted(allowlist.base_ids())
    lines.append("\n🔒 **กลุ่มหลัก (ลบไม่ได้):** " + ", ".join(f"<@{u}>" for u in base))
    text = "\n".join(lines)
    if len(text) > 1900:
        text = text[:1900] + "\n…(ยาวเกิน ตัดบางส่วน)"
    view = _RemoveView(ctx.author.id, entries) if entries else None
    kwargs = {"view": view} if view else {}
    await ctx.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **kwargs)
