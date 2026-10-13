"""bagley/features/memory.py — บันทึกชื่อเล่น/วันเกิด/สิ่งที่ชอบของสมาชิก"""
import re as regex_lib

from bagley.core.app import bot, client
from bagley.core.logutil import print
from bagley.data.storage import get_realtime_name, load_user_data, save_user_data


async def execute_remember_logic(message):
    print("DEBUG: ตรวจพบคำสั่งจำไว้ว่า!")

    target_user = None
    target_display_name = "เพื่อน"
    target_id = None

    has_id = regex_lib.search(r'(\d{17,19})', message.content)

    if has_id:
        target_id = int(has_id.group(1))
        try:
            fetched_user = await bot.fetch_user(target_id)
            if fetched_user:
                target_user = fetched_user
                target_display_name = get_realtime_name(fetched_user.id, fetched_user.display_name)
        except:
            target_display_name = f"ID: {target_id}"

    elif message.mentions:
        # 🛡️ กันเคสข้อความแท็ก "@แบ็คลี่" (เช่น "@Bagley กูชื่อ...จำไว้ด้วย") แล้วไปตีความผิดว่า
        # แบ็คลี่คือเป้าหมายที่จะบันทึกข้อมูลให้ — เอาแต่คนจริงๆ (ไม่ใช่บอท) มาเป็นเป้าหมาย
        human_mentions = [m for m in message.mentions if not m.bot]
        if human_mentions:
            target_user = human_mentions[0]
            target_id = target_user.id
            target_display_name = get_realtime_name(target_user.id, target_user.display_name)

    # 🟢 ไม่ได้แท็กใคร/ไม่มี ID เลย -> ถือว่าเป็นการขอให้จำ "ข้อมูลของตัวเอง" โดยปริยาย
    # (เช่น "กูชื่อนิโคลัส จำไว้ด้วย" ไม่ได้แท็กใครเลย ก็ควรตีความว่าหมายถึงตัวผู้พิมพ์เอง)
    if target_user is None and target_id is None:
        target_user = message.author
        target_id = message.author.id
        target_display_name = get_realtime_name(message.author.id, message.author.display_name)

    # ✅ เปิดให้ทุกคนสั่งให้แบ็คลี่จำ/เปลี่ยนชื่อเล่นของใครก็ได้ในคลังความจำ ไม่ต้องเช็คแล้วว่าเป็นตัวเอง
    # หรือทีมพัฒนาที่เป็นคนสั่ง (ใครบอกให้เรียกใครว่าอะไร ก็บันทึกตามนั้นได้เลย)

    if target_user:
        target_id_str = str(target_id)

        ai_prompt = (
            f"ผู้ใช้พิมพ์ข้อความนี้: '{message.content}'\n"
            f"จงวิเคราะห์ว่าเขาต้องการให้จดจำข้อมูลประเภทใดเกี่ยวกับ คุณ {target_display_name}\n"
            f"ให้เลือกตอบเฉพาะคำสำคัญดังต่อไปนี้เท่านั้น (ห้ามตอบนอกเหนือจากนี้):\n"
            f"- ถ้าเป็นชื่อเล่น ฉายา หรือสถานะทั่วไป ให้ตอบคำว่า: 'nickname'\n"
            f"- ถ้าเกี่ยวข้องกับวัน เดือน ปีเกิด ให้ตอบคำว่า: 'birthday'\n"
            f"- ถ้าเกี่ยวข้องกับสิ่งที่ชอบ งานอดิเรก ของกินที่ชอบ ให้ตอบคำว่า: 'hobby'\n"
            f"คำตอบของคุณ (ตอบแค่คำสำคัญอังกฤษคำเดียวเท่านั้น):"
        )
        
        try:
            response = await client.aio.models.generate_content(
                model="chat",
                contents=ai_prompt
            )
            info_type = response.text.lower().strip()
        except Exception as e:
            print(f"DEBUG AI Error: {e}")
            info_type = "nickname"

        raw_info = message.content
        if "คือ" in raw_info:
            info = raw_info.split("คือ")[-1].strip()
        elif "เกิดวันที่" in raw_info:
            info = raw_info.split("เกิดวันที่")[-1].strip()
        else:
            info = raw_info.replace("จำไว้ว่า", "").strip()

        user_data = load_user_data()
        
        if target_id_str not in user_data or isinstance(user_data[target_id_str], str):
            user_data[target_id_str] = {"nickname": "ยังไม่มีชื่อเล่น", "birthday": "ยังไม่ได้ระบุ", "hobby": "ยังไม่ได้ระบุ"}
        elif "hobby" not in user_data[target_id_str]:
            # 🔧 [แก้บั๊ก] ข้อมูลเก่าที่บันทึกไว้ก่อนมีฟิลด์ hobby จะไม่มีคีย์นี้ ต้องเติมให้ก่อนใช้งาน
            user_data[target_id_str]["hobby"] = "ยังไม่ได้ระบุ"

        if "birthday" in info_type:
            user_data[target_id_str]["birthday"] = info
            await message.reply(f"รับทราบครับ! ผมบันทึกวันเกิดของ คุณ {target_display_name} ว่าเกิดวันที่ **{info}** ลงสมองกลเรียบร้อยแล้วครับ! 🎂✨")
        elif "hobby" in info_type:
            # 🔧 [แก้บั๊ก] เดิม hobby ถูกโยนไปรวมกับ nickname เพราะไม่มี branch แยกให้เลย
            user_data[target_id_str]["hobby"] = info
            await message.reply(f"รับทราบครับ! ผมจำไว้แล้วว่า คุณ {target_display_name} ชอบ **{info}** เรียบร้อยครับ! 🥰")
        else:
            user_data[target_id_str]["nickname"] = info
            await message.reply(f"รับทราบครับ! ผมบันทึกฉายาของ คุณ {target_display_name} ว่าคือ **{info}** เรียบร้อยครับ! 🤠")

        save_user_data(user_data)
        print(f"DEBUG: บันทึกข้อมูลสำเร็จสำหรับ ID: {target_id_str} ประเภท: {info_type}")
        return
