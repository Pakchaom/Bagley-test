"""ทดสอบชั้น AI: tier talk + Groq/Gemini สำรองกัน + กันโมเดลคิดจนตอบว่าง (ใช้คีย์ปลอม ไม่ยิงเน็ตจริง)
รัน: PYTHONPATH=. python3 tests/test_provider_groq.py"""
import asyncio, os, sys, json
for _k in list(os.environ):
    if _k.startswith(("AI_", "GROQ_", "GEMINI_", "CEREBRAS_", "GITHUB_", "OPENROUTER_", "OPENAI_")):
        os.environ.pop(_k)
os.environ.update({
    "GEMINI_API_KEY": "fake-gemini", "GROQ_API_KEY": "fake-groq", "GROQ_MODEL_TALK": "openai/gpt-oss-120b",
    "AI_ORDER_FAST": "groq,gemini", "AI_ORDER_CHAT": "gemini,groq", "AI_ORDER_TALK": "groq,gemini",
    "AI_ORDER_VISION": "gemini",
})
from bagley.ai import provider as p

fails = 0
def check(name, cond):
    global fails
    print(("PASS" if cond else "FAIL"), name); fails += (not cond)

def ok_body(text="สวัสดีครับ", finish="stop", tool=None):
    msg = {"content": text}
    if tool: msg["tool_calls"] = [{"function": {"name": tool, "arguments": "{}"}}]
    return {"choices": [{"message": msg, "finish_reason": finish}]}

async def main():
    c = p.AIClient()
    check("orders: talk = groq,gemini", c.orders["talk"] == ["groq", "gemini"])
    check("orders: fast = groq,gemini", c.orders["fast"] == ["groq", "gemini"])
    check("orders: chat = gemini,groq (มีสำรองแล้ว)", c.orders["chat"] == ["gemini", "groq"])
    check("orders: vision = gemini", c.orders["vision"] == ["gemini"])
    check("groq talk model อ่านจาก GROQ_MODEL_TALK", c.specs["groq"].models["talk"] == "openai/gpt-oss-120b")
    check("gemini talk model = chat model", c.specs["gemini"].models["talk"] == c.specs["gemini"].models["chat"])

    calls = []
    async def fake_post(spec, payload, timeout):
        calls.append((spec.name, payload))
        return ok_body(f"จาก {spec.name}")
    c._post_json = fake_post

    # 1) talk ไปที่ groq ก่อน ด้วยโมเดล talk
    r = await c.ask("ทักหน่อย", tier="talk")
    check("talk -> groq ก่อน", r.provider == "groq" and calls[-1][1]["model"] == "openai/gpt-oss-120b")

    # 2) headroom: max_tokens ของ groq ถูกเผื่อที่คิด (40 -> 40+384)
    calls.clear()
    await c.ask("x", tier="fast", max_tokens=40, json_mode=True, cache_ttl=0)
    check("groq: max_tokens 40 ถูกเผื่อเป็น 424", calls[-1][0] == "groq" and calls[-1][1].get("max_tokens") == 424)

    # 3) gemini ไม่ถูกเผื่อ (ไม่ใช่โมเดลคิดแบบ effort)
    calls.clear()
    c2 = p.AIClient(); c2._post_json = fake_post
    await c2.ask("x", tier="chat", max_tokens=100)   # chat: gemini ก่อน
    check("gemini: max_tokens คงเดิม 100", calls[-1][0] == "gemini" and calls[-1][1].get("max_tokens") == 100)

    # 4) groq ตอบว่างเพราะ length -> สลับไป gemini ทันที (ไม่ส่งคำตอบว่างกลับ)
    c3 = p.AIClient(); calls3 = []
    async def post3(spec, payload, timeout):
        calls3.append(spec.name)
        if spec.name == "groq":
            return ok_body("", finish="length")
        return ok_body("gemini ช่วยตอบ")
    c3._post_json = post3
    r = await c3.ask("x", tier="talk")
    check("groq length+ว่าง -> ตกไป gemini", calls3 == ["groq", "gemini"] and r.text == "gemini ช่วยตอบ")

    # 5) router: ไม่มีข้อความแต่มี tool_call ต้องไม่ถูกมองว่าล้มเหลว
    c4 = p.AIClient()
    async def post4(spec, payload, timeout): return ok_body("", finish="tool_calls", tool="play")
    c4._post_json = post4
    r = await c4.ask("x", tier="fast", tools=[{"type": "function", "function": {"name": "play"}}])
    check("tool_call ล้วนๆ ผ่านได้ (ไม่ถูก retry)", r.provider == "groq" and r.tool_calls and r.tool_calls[0].name == "play")

    # 6) groq 429 -> สลับ gemini ไม่ขึ้น AIError
    c5 = p.AIClient()
    async def post5(spec, payload, timeout):
        if spec.name == "groq": raise p._Retryable("429 rate", cooldown=20)
        return ok_body("ok gemini")
    c5._post_json = post5
    r = await c5.ask("x", tier="talk")
    check("groq 429 -> gemini รับช่วง", r.provider == "gemini")

    # 7) ทั้งสองเจ้าล่ม -> AIError (นี่คือจุดที่บอทขึ้น 'สมองไม่ทำงาน')
    c6 = p.AIClient()
    async def post6(spec, payload, timeout): raise p._Retryable("503", cooldown=10)
    c6._post_json = post6
    try:
        await c6.ask("x", tier="talk", wait_budget=0.1)
        check("ล่มทั้งคู่ -> AIError", False)
    except p.AIError:
        check("ล่มทั้งคู่ -> AIError", True)

    # 8) compat layer: generate_content(model="talk")
    c7 = p.AIClient(); c7._post_json = fake_post; calls.clear()
    r = await c7.aio.models.generate_content(model="talk", contents="สวัสดี")
    check("generate_content(model='talk') ใช้ tier talk", r.provider == "groq")

    print("\nFAILS:", fails)
asyncio.run(main())
