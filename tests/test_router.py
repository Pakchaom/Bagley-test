import asyncio, sys, types, discord
from discord.ext import commands
from bagley.ai import router, understanding

bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
LOG=[]
@bot.hybrid_command(name="play", description="เปิดเพลง")
async def play(ctx, query: str): LOG.append(("play", query))
@bot.hybrid_command(name="stop", description="หยุดเพลง")
async def stop(ctx): LOG.append(("stop",))
@bot.hybrid_command(name="queue", description="ดูคิวเพลง")
async def queue(ctx): LOG.append(("queue",))

class TC:  # tool call
    def __init__(s,n,a): s.name=n; s.args=a
class Resp:
    def __init__(s,calls=None): s.tool_calls=calls or []; s.text=""
class FakeAI:
    def __init__(s): s.script=[]; s.kind="chat"; s.picks=[]
    async def ask(s, prompt, **kw): return s.script.pop(0) if s.script else Resp()
    async def classify_json(s, prompt, **kw):
        if "Classify a Thai" in prompt: return {"kind": s.kind}
        if "pick up to 6" in prompt: return {"names": s.picks}
        return {"confident": True}

class Chan:
    id=5
    async def history(s, **kw):
        if False: yield
class Msg:
    def __init__(s,text,uid=1):
        s.content=text; s.channel=Chan(); s.author=types.SimpleNamespace(id=uid,display_name="ต้น"); s.guild=None; s.replies=[]
    async def reply(s,t,**kw): s.replies.append(t)

async def get_context(message):
    return types.SimpleNamespace(invoke=lambda cmd, **kw: _inv(cmd, kw))
async def _inv(cmd, kw): await cmd.callback(None, **kw)
bot.get_context = get_context

fails=0
def check(n,c):
    global fails; print(("PASS" if c else "FAIL"), n); fails += (not c)
find=lambda *a, **k: None

async def main():
    ai=FakeAI()
    # 1) chain of two commands
    LOG.clear(); ai.script=[Resp([TC("play",{"query":"Lemon Tree"}), TC("queue",{})])]
    m=Msg("แบ็คลี่ เปิดเพลง Lemon Tree แล้วดูคิวด้วย")
    r=await router.ai_route_and_execute(m, bot, ai, find)
    check("chained commands executed in order", r is True and LOG==[("play","Lemon Tree"),("queue",)])

    # 2) hallucinated param blocked
    LOG.clear(); ai.script=[Resp([TC("play",{"query":"Never Gonna Give You Up"})])]
    m=Msg("แบ็คลี่ เปิดเพลงหน่อย")
    r=await router.ai_route_and_execute(m, bot, ai, find)
    check("hallucinated param -> not executed", r is False and LOG==[])

    # 3) value grounded in recent chat context
    LOG.clear(); ai.script=[Resp([TC("play",{"query":"Blinding Lights"})])]
    m=Msg("แบ็คลี่ เปิดเพลงที่เมื่อกี้ให้หน่อย")
    r=await router.ai_route_and_execute(m, bot, ai, find, context_text="[เอ]: อยากฟัง Blinding Lights จัง")
    check("context-grounded param allowed", r is True and LOG==[("play","Blinding Lights")])

    # 4) ask_user -> pending -> answer completes (without saying the name again)
    LOG.clear(); ai.script=[Resp([TC("ask_user",{"question":"จะให้เปิดเพลงอะไรดีครับ"})])]
    m=Msg("แบ็คลี่ เปิดเพลงให้หน่อย", uid=9)
    r=await router.ai_route_and_execute(m, bot, ai, find)
    check("clarifying question asked", r is True and m.replies==["จะให้เปิดเพลงอะไรดีครับ"])
    m2=Msg("Shape of You", uid=9)
    check("pending detected for next msg", router.has_pending_clarification(m2))
    ai.script=[Resp([TC("play",{"query":"Shape of You"})])]
    r=await router.ai_route_and_execute(m2, bot, ai, find)
    check("answer merged -> command runs", r is True and LOG==[("play","Shape of You")])
    check("pending cleared", not router.has_pending_clarification(m2))

    # 5) semantic fallback: no keyword, but request-like and classified as command
    LOG.clear(); understanding._last_clarify.clear()
    ai.kind="command"; ai.picks=["stop"]; ai.script=[Resp([TC("stop",{})])]
    m=Msg("แบ็คลี่ ช่วยทำให้บรรยากาศสงบลงหน่อย")   # ไม่มีคำสำคัญ
    from bagley.ai import gate
    check("(premise) keyword gate misses it", not gate.looks_like_command(m.content))
    r=await router.ai_route_and_execute(m, bot, ai, find)
    check("semantic fallback routes to /stop", r is True and LOG==[("stop",)])

    # 6) classified chat -> untouched
    LOG.clear(); ai.kind="chat"
    m=Msg("แบ็คลี่ ช่วยบอกหน่อยว่าฟ้าทำไมสีฟ้า")
    r=await router.ai_route_and_execute(m, bot, ai, find)
    check("chat stays chat", r is False and LOG==[])

    # 7) ask_user spam guard
    understanding._last_clarify.clear(); understanding._PENDING.clear()
    ai.script=[Resp([TC("ask_user",{"question":"ข้อ 1?"})])]
    m=Msg("แบ็คลี่ เปิดเพลงให้หน่อย", uid=3); await router.ai_route_and_execute(m, bot, ai, find)
    understanding._PENDING.clear()
    ai.script=[Resp([TC("ask_user",{"question":"ข้อ 2?"})])]
    m=Msg("แบ็คลี่ เปิดเพลงให้หน่อย", uid=3); r=await router.ai_route_and_execute(m, bot, ai, find)
    check("clarify cooldown prevents nagging", r is False and m.replies==[])
asyncio.run(main())
print("FAILED:",fails); sys.exit(1 if fails else 0)
