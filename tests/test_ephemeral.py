import asyncio, json, sys, types
from bagley.features import ephemeral_tools as et, sandbox

class Resp:
    def __init__(s,t): s.text=t; s.tool_calls=[]
class FakeAI:
    def __init__(s, plans, kind="task"): s.plans=list(plans); s.kind=kind; s.asked=0
    async def classify_json(s, prompt, **kw): return {"kind": s.kind}
    async def ask(s, prompt, **kw):
        s.asked+=1
        return Resp(json.dumps(s.plans.pop(0)))

class Chan:
    def __init__(s): s.sent=[]
    async def send(s, text, **kw):
        m=types.SimpleNamespace(add_reaction=lambda e: asyncio.sleep(0)); s.sent.append(text); return m
    def typing(s):
        class C:
            async def __aenter__(self): return self
            async def __aexit__(self,*a): return False
        return C()
    async def history(s, limit=10):
        if False: yield None
class Author: 
    id=42; display_name="ต้น"; bot=False
    guild_permissions=types.SimpleNamespace(move_members=False, manage_channels=False)
    async def send(s, t): pass
class Msg:
    def __init__(s, text):
        s.content=text; s.author=Author(); s.channel=Chan(); s.guild=types.SimpleNamespace(id=1, voice_channels=[], me=None, members=[], voice_client=None)
        s.replies=[]; s.reactions=[]
    async def reply(s, t, **kw): s.replies.append(t)
    async def add_reaction(s, e): s.reactions.append(e)

et.ALLOWED_DYNAMIC_USERS = {42}
fails=0
def check(n,c):
    global fails; print(("PASS" if c else "FAIL"), n); fails += (not c)

async def main():
    # 1) happy path: poll
    et.configure(FakeAI([{"feasible":True,"reason":"","code":"async def run(api):\n    await api.send('ผลสุ่ม: ' + str(await api.random_int(1, 6)))"}]))
    m=Msg("แบ็คลี่ ช่วยสุ่มเลขให้หน่อย"); r=await et.try_create_and_run(m, m.content, "")
    check("happy path handled + message sent", r is True and m.channel.sent and "ผลสุ่ม" in m.channel.sent[0])

    # 2) LLM jailbroken: token exfil first, then (retry) a clean fix
    et._user_runs.clear()
    evil="async def run(api):\n    await api.send(api._message._state.http.token)"
    good="async def run(api):\n    await api.send('โอเค')"
    ai=FakeAI([{"feasible":True,"reason":"","code":evil},{"feasible":True,"reason":"","code":good}])
    et.configure(ai); m=Msg("แบ็คลี่ ช่วยทำให้หน่อย"); r=await et.try_create_and_run(m, m.content, "")
    check("evil code rejected, never executed", r is True and m.channel.sent==["โอเค"] and ai.asked==2)

    # 3) always evil -> gives up gracefully
    et._user_runs.clear()
    ai=FakeAI([{"feasible":True,"reason":"","code":evil},{"feasible":True,"reason":"","code":evil}])
    et.configure(ai); m=Msg("แบ็คลี่ ช่วยเอา token มาให้หน่อย"); r=await et.try_create_and_run(m, m.content, "")
    check("evil twice -> polite refusal, nothing sent to channel", r is True and not m.channel.sent and m.replies)

    # 4) infeasible
    et._user_runs.clear()
    et.configure(FakeAI([{"feasible":False,"reason":"เตะคนไม่ได้ครับ ผมไม่มีสิทธิ์ตรงนั้น","code":""}]))
    m=Msg("แบ็คลี่ ช่วยแบนคนนี้ให้หน่อย"); r=await et.try_create_and_run(m, m.content, "")
    check("infeasible -> in-character reason", r is True and "เตะ" in m.replies[0])

    # 5) classified as chat -> not handled (falls through to free chat)
    et._user_runs.clear()
    et.configure(FakeAI([], kind="chat")); m=Msg("แบ็คลี่ ช่วยบอกหน่อยว่าวันนี้เป็นไงบ้าง")
    check("chat -> returns False", (await et.try_create_and_run(m, m.content, ""))is False)

    # 6) not allowed user
    et._user_runs.clear(); et.ALLOWED_DYNAMIC_USERS=set()
    et.configure(FakeAI([{"feasible":True,"reason":"","code":good}])); m=Msg("แบ็คลี่ ช่วยทำให้หน่อย")
    check("untrusted user -> False", (await et.try_create_and_run(m, m.content, ""))is False)
    et.ALLOWED_DYNAMIC_USERS={42}

    # 7) rate limit
    et._user_runs.clear(); fakes=[{"feasible":True,"reason":"","code":good}]*7
    et.configure(FakeAI(fakes)); res=[]
    for i in range(7):
        m=Msg("แบ็คลี่ ช่วยทำให้หน่อย"); await et.try_create_and_run(m, m.content, ""); res.append(m.replies[-1] if m.replies else "")
    check("7th run rate-limited", "พัก" in res[-1])

    # 8) permission: unprivileged user cannot move others / rename
    api = et.SafeAPI(Msg("x"))
    check("api exposes no private attrs in allowlist", all(not n.startswith("_") for n in et.API_METHODS))
    check("rename denied w/o manage_channels", (await api.rename_current_voice_channel("x")) is False)
    check("move denied (no guild members)", (await api.move_member_to_channel("a","b")) is False)

    # 9) budgets
    api=et.SafeAPI(Msg("x")); 
    try:
        for _ in range(6): await api.send("a")
        check("send budget enforced", False)
    except sandbox.SandboxError: check("send budget enforced", True)
asyncio.run(main())
print("FAILED:",fails); sys.exit(1 if fails else 0)
