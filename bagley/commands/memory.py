"""bagley/commands/memory.py — คำสั่งความจำ: teach / remember / forget / รายชื่อ"""
import discord
import re as regex_lib
from discord import app_commands
from discord.ext import commands

from bagley.core.app import bot
from bagley.core.config import ALLOWED_TEACH_USERS, OWNER_DISCORD_ID
from bagley.core.logutil import print
from bagley.data.storage import get_realtime_name, load_user_data, save_user_data
from bagley.db import conn
from bagley.features import knowledge as bagley_knowledge, rules as bagley_rules
from bagley.phrases import say
from bagley.ui.views import IdentityListPaginator
from bagley.voice.tts import bagley_speak


# --- 3. ล้างความจำ (clear_memory) ---
@bot.hybrid_command(name="clear_memory", description="ล้างประวัติการสนทนาส่วนตัวของคุณกับ Bagley")
async def clear_memory(ctx: commands.Context):
    if ctx.interaction:
        await ctx.interaction.response.defer() # บอก Discord ว่าขอเวลาประมวลผลแป๊บครับ

    user_id = str(ctx.author.id) # แปลงเป็น string ให้ตรงกับตอนเซฟ
    global conn
    c = conn.cursor()
    
    # ลบเฉพาะประวัติของตัวเองคนเดียว
    c.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    
    msg = "เรียบร้อย! ผมล้างหน่วยความจำที่เกี่ยวกับคุณทิ้งหมดแล้ว"
    
    if ctx.interaction:
        await ctx.interaction.followup.send(msg)
    else:
        await ctx.send(msg)
    
    # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" ออก bagley_speak() รอเสียงเดิมจบเองอยู่แล้ว
    if ctx.guild.voice_client:
        await bagley_speak(ctx.guild, say("memory_cleared"))


@bot.hybrid_command(name="teach", description="สอนให้แบ็คลี่จำคีย์เวิร์ดคำถามและคำตอบ")
async def teach(ctx: commands.Context, keyword: str, response: str):
    await ctx.defer()

    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send("❌ **[ACCESS DENIED]** " + say("dev_denied", name=get_realtime_name(ctx.author.id, ctx.author.display_name)))
        return

    clean_keyword = keyword.lower().strip()

    if len(clean_keyword) == 0:
        await ctx.send("⚠️ **[TEACH REJECTED]** คีย์เวิร์ดต้องมีตัวอักษรด้วยนะคร้าบ! ❌")
        return

    global conn
    c = conn.cursor()
    
    c.execute(
        "INSERT OR REPLACE INTO teach_memory (keyword, response) VALUES (?, ?)",
        (clean_keyword, response.strip())
    )
    conn.commit()
    
    await ctx.send(f"รับทราบครับ! แบ็คลี่จดบันทึกคีย์เวิร์ด **'{keyword}'** เข้าคลังสมองกลเรียบร้อยแล้วครับ! 🧠✨")


@bot.hybrid_command(name="unteach", description="สั่งให้แบ็คลี่ลืมคีย์เวิร์ดคำถามที่ไม่ต้องการ")
async def unteach(ctx: commands.Context, keyword: str):
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send("❌ **[ACCESS DENIED]** " + say("dev_denied", name=get_realtime_name(ctx.author.id, ctx.author.display_name)))
        return

    await ctx.defer(ephemeral=False)
    global conn
    c = conn.cursor()
    
    clean_keyword = keyword.lower().strip()
    
    c.execute("SELECT response FROM teach_memory WHERE keyword = ?", (clean_keyword,))
    result = c.fetchone()
    
    if result is None:
        await ctx.send(f"🤖 แบ็คลี่ลองค้นดูแล้ว... ไม่พบคีย์เวิร์ด **'{keyword}'** ในระบบเลยครับ!")
        return

    c.execute("DELETE FROM teach_memory WHERE keyword = ?", (clean_keyword,))
    conn.commit()
    
    await ctx.send(f"รับทราบครับ! แบ็คลี่ทำการลบและลืมคีย์เวิร์ด **'{keyword}'** ออกเรียบร้อยแล้วครับ! 🧼❌")


@bot.hybrid_command(name="list_teach", description="เรียกดูรายการคีย์เวิร์ดทั้งหมดที่เคยสอนแบ็คลี่ไว้")
async def list_teach(ctx: commands.Context):
    await ctx.defer()

    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send("❌ **[ACCESS DENIED]** " + say("dev_denied", name=get_realtime_name(ctx.author.id, ctx.author.display_name)))
        return

    global conn
    c = conn.cursor()
    
    c.execute("SELECT keyword, response FROM teach_memory ORDER BY keyword ASC")
    rows = c.fetchall()
    
    if not rows:
        await ctx.send("🤖 ตอนนี้คลังสมองของแบ็คลี่ยังว่างเปล่า ไม่มีคีย์เวิร์ดที่เคยสอนไว้เลยครับ!")
        return

    formatted_list = []
    for keyword, response in rows:
        response_text = response if response else "*(ไม่มีคำตอบบันทึกไว้)*"
        # ตัดคำตอบที่ยาวเกินไปกันข้อความในเอ็มเบดล้นหน้า
        if len(response_text) > 150:
            response_text = response_text[:150] + "..."
        formatted_list.append(f"**{keyword}**\n> {response_text}")

    title_text = "🧠 BAGLEY MEMORY BANK: รายการคีย์เวิร์ดที่ทีมพัฒนาเคยสอนไว้"
    view = IdentityListPaginator(title_text=title_text, data_list=formatted_list, per_page=5)
    view.message = await ctx.send(embed=view.create_embed(), view=view)


@bot.hybrid_command(name="list_rules", description="เรียกดูรายการ 'กฎ' ที่แบ็คลี่เคยถูกสอนไว้ (จากการพิมพ์คุยเฉยๆ) — มีผลทุกเซิร์ฟเวอร์")
async def list_rules(ctx: commands.Context):
    await ctx.defer()

    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send("❌ **[ACCESS DENIED]** " + say("dev_denied", name=get_realtime_name(ctx.author.id, ctx.author.display_name)))
        return

    rules_text = bagley_rules.list_rules_text()
    embed = discord.Embed(
        title="📜 BAGLEY RULE BANK: กฎที่เคยถูกสอนไว้ (ใช้ทุกเซิร์ฟเวอร์)",
        description=rules_text[:4000],
        color=discord.Color.blurple(),
    )
    await ctx.send(embed=embed)


@bot.hybrid_command(name="forget_rule", description="สั่งให้แบ็คลี่ลืมกฎที่เคยถูกสอนไว้ (ดูเลข id ได้จาก /list_rules)")
@app_commands.describe(rule_id="เลข id ของกฎที่จะลบ (ดูได้จาก /list_rules)")
async def forget_rule(ctx: commands.Context, rule_id: int):
    if ctx.author.id not in ALLOWED_TEACH_USERS:
        await ctx.send("❌ **[ACCESS DENIED]** " + say("dev_denied", name=get_realtime_name(ctx.author.id, ctx.author.display_name)))
        return

    await ctx.defer()
    if bagley_rules.forget_rule(rule_id):
        await ctx.send(f"รับทราบครับ! ลบกฎ `#{rule_id}` ออกจากคลังสมองเรียบร้อยแล้วครับ! 🧼❌")
    else:
        await ctx.send(f"🤖 แบ็คลี่ลองค้นดูแล้ว... ไม่พบกฎ `#{rule_id}` ในระบบเลยครับ!")


@bot.hybrid_command(name="remember", description="สั่งให้แบ็คลี่จดจำชื่อเล่น/วันเกิดของใครก็ได้ลงคลังความจำ (ใครก็สั่งได้ ไม่จำกัดแค่ทีมพัฒนา)")
@app_commands.describe(
    member="แท็กสมาชิก (@ชื่อ), ใส่ User ID ตรง ๆ, หรือพิมพ์ 'ตัวเอง' ถ้าจะจำข้อมูลของตัวเอง",
    category="ประเภทข้อมูลที่จะบันทึก",
    info="ข้อมูลที่ต้องการบันทึก (เช่น ชื่อเล่น หรือ วันเกิด)"
)
@app_commands.choices(category=[
    app_commands.Choice(name="ชื่อเล่น (Nickname)", value="nickname"),
    app_commands.Choice(name="วันเกิด (Birthday)", value="birthday"),
])
async def remember(ctx: commands.Context, member: str, category: str, info: str):
    """เวอร์ชันสแลชคอมมานด์ของคำสั่งพูดคุย 'จำไว้ว่า'
    ✅ เปิดให้ทุกคนสั่งให้แบ็คลี่จำ/เปลี่ยนชื่อเล่นหรือวันเกิดของใครก็ได้ในคลังความจำ ไม่ต้องเช็คแล้วว่า
    เป็นเจ้าของไอดีเองหรือทีมพัฒนาที่เป็นคนสั่ง — ใครบอกให้เรียกใครว่าอะไร ก็บันทึกตามนั้นได้เลย"""
    await ctx.defer()

    # 🔍 รองรับทั้งการแท็ก @สมาชิก, ใส่ User ID ตรง ๆ, หรือพิมพ์คำแทนตัวเอง (ดึงตัวเลข ID ออกมา
    # แบบเดียวกับคำสั่ง "จำไว้ว่า")
    _SELF_KEYWORDS = ("ตัวเอง", "ตัวข้าเอง", "ฉันเอง", "ผมเอง", "กูเอง", "เราเอง", "self", "myself", "me")
    member_lower = member.strip().lower()

    has_id = regex_lib.search(r'(\d{17,19})', member)
    if has_id:
        target_id = int(has_id.group(1))
    elif member_lower in _SELF_KEYWORDS or member_lower == "":
        target_id = ctx.author.id
    else:
        target_id = None

    if target_id is None:
        await ctx.send(
            "❌ ไม่พบผู้ใช้ที่ระบุครับ กรุณาแท็ก (@) สมาชิก, ใส่ User ID, หรือพิมพ์ 'ตัวเอง' ถ้าจะจำข้อมูลของตัวเองนะครับ!"
        )
        return

    target_user = ctx.guild.get_member(target_id) if ctx.guild else None
    if target_user is None:
        try:
            target_user = await bot.fetch_user(target_id)
        except Exception:
            target_user = None

    if target_user is None:
        await ctx.send(f"❌ แบ็คลี่หาผู้ใช้ ID `{target_id}` ไม่เจอเลยครับ ลองเช็ก ID อีกทีนะครับ!")
        return

    target_id_str = str(target_user.id)
    target_display_name = get_realtime_name(target_user.id, getattr(target_user, "display_name", None) or target_user.name)
    clean_info = info.strip()

    if not clean_info:
        await ctx.send("⚠️ **[REMEMBER REJECTED]** ข้อมูลที่จะให้จำต้องไม่ว่างเปล่านะครับ! ❌")
        return

    user_data = load_user_data()

    if target_id_str not in user_data or isinstance(user_data[target_id_str], str):
        user_data[target_id_str] = {"nickname": "ยังไม่มีชื่อเล่น", "birthday": "ยังไม่ได้ระบุ"}

    if category == "birthday":
        user_data[target_id_str]["birthday"] = clean_info
        save_user_data(user_data)
        await ctx.send(f"รับทราบครับ! ผมบันทึกวันเกิดของ คุณ {target_display_name} ว่าเกิดวันที่ **{clean_info}** ลงสมองกลเรียบร้อยแล้วครับ! 🎂✨")
    else:
        user_data[target_id_str]["nickname"] = clean_info
        save_user_data(user_data)
        await ctx.send(f"รับทราบครับ! ผมบันทึกฉายาของ คุณ {target_display_name} ว่าคือ **{clean_info}** เรียบร้อยครับ! 🤠")


@bot.hybrid_command(name="forget", description="ลบข้อมูลชื่อเล่นหรือวันเกิดของพรรคพวกออกจากคลังสมองของแบ็คลี่")
@app_commands.describe(target="พรรคพวกที่ต้องการให้บอทลืมข้อมูล (หากต้องการลบของตัวเอง ไม่ต้องใส่ช่องนี้)")
async def forget(ctx: commands.Context, target: discord.User = None):
    await ctx.defer()
    
    data_memory = load_user_data()
    reply_text = ""

    # 🧠 ลบความจำระยะยาวที่เรียนรู้จากการคุย (knowledge) ด้วย — เจ้าตัวลบของตัวเองได้ / ทีมพัฒนาลบของคนอื่นได้
    _k_target_id = target.id if target else ctx.author.id
    _k_removed = 0
    if _k_target_id == ctx.author.id or ctx.author.id in ALLOWED_TEACH_USERS:
        _k_removed = bagley_knowledge.forget_all_for_user(_k_target_id)
    
    if target:
        target_id = str(target.id)
        if target_id in data_memory:
            del data_memory[target_id]
            save_user_data(data_memory)
            reply_text = f"เรียบร้อยครับ! ผมกวาดข้อมูลของ คุณ {get_realtime_name(target.id, target.display_name)} ออกจากสมองกลเกลี้ยงตับ สะอาดสะอ้านเหมือนไม่เคยรู้จักกันมาก่อนเลยครับ!"
        else:
            reply_text = f"เอ่อ... ครับ ในสมองผมไม่มีข้อมูลของ คุณ {get_realtime_name(target.id, target.display_name)} อยู่เลยสักเมกะไบต์ จะให้ผมลบความว่างเปล่าเหรอครับ!"

    # 👤 เคสที่ 2: สั่งให้ลบข้อมูลของ "ตัวเอง"
    else:
        user_id = str(ctx.author.id)
        if user_id in data_memory:
            del data_memory[user_id]
            save_user_data(data_memory)
            reply_text = "รับทราบครับ! ผมทำการล้างสมองตัวเองเกี่ยวกับข้อมูลของคุณเกลี้ยงแล้ว ต่อจากนี้เราคือคนแปลกหน้าในร่างคู่หูคนเดิมครับ!"
        else:
            reply_text = "ฮั่นแน่ คุณแกล้งปั่นหัวสมองกลผมเล่นหรือเปล่าครับ? ข้อมูลคุณผมยังไม่เคยบันทึกไว้เลย จะให้ลบอะไรก่อนครับ!"
                
    if _k_removed:
        reply_text += f" (ลบเรื่องที่จำจากการคุยกันอีก {_k_removed} เรื่องด้วยครับ)"
    await ctx.send(reply_text)

    # 🔧 [แก้บั๊ก] เอาเงื่อนไข "not is_playing()" และ "ต้องอยู่ห้องเดียวกับคนสั่ง" ออก
    # bagley_speak() รอเสียงเดิมจบเองอยู่แล้ว และแบ็คลี่ควรพูดทุกครั้งที่ตอบกลับ
    if ctx.guild and ctx.guild.voice_client and ctx.guild.voice_client.channel:
        try:
            import re
            clean_voice_text = re.sub(r'[^\w\s\u0e00-\u0e7f]+', '', reply_text)
            await bagley_speak(ctx.guild, clean_voice_text)
        except Exception as tts_err:
            print(f"🚨 Forget Command TTS Error: {tts_err}")


@bot.hybrid_command(name="memberlist", description="เปิดสมุดคลังความจำดูรายชื่อพรรคพวกในดิสคอร์ด")
@app_commands.describe(scope="เลือกขอบเขต: 'current' ดูเฉพาะเซิร์ฟนี้, 'all' ดูทุกเซิร์ฟเวอร์ (สิทธิ์มาสเตอร์)")
@app_commands.choices(scope=[
    app_commands.Choice(name="ดูเฉพาะเซิร์ฟเวอร์นี้", value="current"),
    app_commands.Choice(name="ระบบตาทิพย์ ดูทุกเซิร์ฟเวอร์ (เฉพาะผู้สร้าง)", value="all")
])
async def member_list(ctx: commands.Context, scope: str = "current"):
    try:
        MY_MASTER_ID = OWNER_DISCORD_ID
        user_data = load_user_data()

        if not user_data:
            return await ctx.send("ตอนนี้คลังความจำของผมยังว่างเปล่าอยู่เลยครับ")

        formatted_list = []

        if scope == "all" or ctx.guild is None:
            if ctx.author.id != MY_MASTER_ID:
                return await ctx.send("ขออภัยครับ คำสั่งระดับสูงนี้ถูกจำกัดสิทธิ์ไว้เฉพาะผู้สร้างผมขึ้นมาเท่านั้นครับ! 🤫❌", ephemeral=True)
            
            title_text = "👁️ คลังระบบตาทิพย์: รายชื่อพรรคพวกทั้งหมดจากทุกเซิร์ฟ"
            
            for user_id_str, data in user_data.items():
                if not user_id_str.isdigit(): continue  # ข้าม key ที่ไม่ใช่ user id เช่น "reminders", "schedules"
                nickname = data.get("nickname", "ยังไม่มีชื่อเล่น") if isinstance(data, dict) else data
                birthday = data.get("birthday", "ยังไม่ได้ระบุ") if isinstance(data, dict) else "ยังไม่ได้ระบุ"
                formatted_list.append(f"<@{user_id_str}> (ID: {user_id_str}): {nickname} (วันเกิด: {birthday})")

        else:
            guild = ctx.guild
            title_text = f"📊 รายชื่อพรรคพวกในดิส '{guild.name}' ที่ผมจำได้"
            
            for user_id_str, data in user_data.items():
                if not user_id_str.isdigit(): continue  # ข้าม key ที่ไม่ใช่ user id เช่น "reminders", "schedules"
                
                member = guild.get_member(int(user_id_str))
                if not member: continue
                
                nickname = data.get("nickname", "ยังไม่มีชื่อเล่น") if isinstance(data, dict) else data
                birthday = data.get("birthday", "ยังไม่ได้ระบุ") if isinstance(data, dict) else "ยังไม่ได้ระบุ"
                
                if birthday != "ยังไม่ได้ระบุ":
                    formatted_list.append(f"<@{user_id_str}>: {nickname} (วันเกิด: {birthday})")
                else:
                    formatted_list.append(f"<@{user_id_str}>: {nickname}")

        if not formatted_list:
            return await ctx.send("ในขอบเขตนี้ผมยังไม่มีข้อมูลคลังความจำของพรรคพวกคนไหนเลยครับ!")

        view = IdentityListPaginator(title_text=title_text, data_list=formatted_list, per_page=10)
        view.message = await ctx.send(embed=view.create_embed(), view=view)

    except Exception as e:
        print(f"🚨 ERROR ระบบรายชื่อใหม่: {e}")
        await ctx.send("เกิดข้อผิดพลาดในการดึงข้อมูลรายชื่อครับ")


# ============================================================
# 🧠 ความจำระยะยาวที่แบ็คลี่เรียนรู้เองจากการคุย (ดู bagley/features/knowledge.py)
# ============================================================
@bot.hybrid_command(name="my_memory", description="ดูว่าแบ็คลี่จำอะไรเกี่ยวกับคุณไว้บ้าง (เห็นเฉพาะคุณคนเดียว)")
async def my_memory(ctx: commands.Context):
    rows = bagley_knowledge.facts_of_user(ctx.author.id)
    if not rows:
        text = "ตอนนี้ผมยังไม่ได้จดอะไรเกี่ยวกับคุณไว้เลยครับ ลองเล่าอะไรให้ฟังบ้างสิ"
    else:
        body = "\n".join(f"`#{rid}` {fact}" for rid, _c, fact, _s, _e in rows)[:1800]
        text = "สิ่งที่ผมจำเกี่ยวกับคุณได้ (ลบข้อไหนใช้ /forget_fact เลขข้อ):\n" + body
    if ctx.interaction:  # slash: ส่งแบบเห็นคนเดียว
        await ctx.interaction.response.send_message(text, ephemeral=True)
    else:                # พิมพ์ !my_memory: ส่ง DM กันเรื่องส่วนตัวหลุดกลางห้อง
        try:
            await ctx.author.send(text)
            await ctx.send("ส่งใน DM ให้แล้วครับ")
        except discord.Forbidden:
            await ctx.send("ผมส่ง DM ไม่ได้ครับ เปิดรับ DM จากสมาชิกเซิร์ฟเวอร์ก่อนนะ หรือใช้ /my_memory แบบ slash")


@bot.hybrid_command(name="forget_fact", description="ให้แบ็คลี่ลืมเรื่องที่จำไว้ 1 ข้อ (ดูเลขข้อจาก /my_memory)")
@app_commands.describe(fact_id="เลขข้อที่จะลบ")
async def forget_fact(ctx: commands.Context, fact_id: int):
    ok = bagley_knowledge.forget_fact_by_id(fact_id, ctx.author.id, is_admin=ctx.author.id in ALLOWED_TEACH_USERS)
    msg = f"ลืมข้อ `#{fact_id}` ให้แล้วครับ" if ok else f"ไม่พบข้อ `#{fact_id}` หรือคุณไม่ใช่เจ้าของข้อมูลนี้ครับ"
    if ctx.interaction:
        await ctx.interaction.response.send_message(msg, ephemeral=True)
    else:
        await ctx.send(msg)
