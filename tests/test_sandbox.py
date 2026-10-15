import pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
import pathlib, asyncio, sys, importlib.util
spec = importlib.util.spec_from_file_location("sandbox", str(ROOT / "bagley/features/sandbox.py"))
sb = importlib.util.module_from_spec(spec); spec.loader.exec_module(sb)

METHODS = {"send","react","random_int","choice","shuffle","now","recent_messages"}
class API:
    def __init__(s): s.out=[]; s._message="SECRET"
    async def send(s,t): s.out.append(t)
    async def react(s,e): s.out.append("r"+e)
    async def random_int(s,a,b): return a
    async def choice(s,l): return l[0]
    async def shuffle(s,l): return list(reversed(l))
    async def now(s): return "12:00"
    async def recent_messages(s,n=5): return [{"author":"a","text":"hi"}]

def attempt(src):
    try:
        run = sb.compile_tool(src, METHODS)
    except sb.SandboxError as e:
        return "BLOCKED", str(e)
    api = API()
    try:
        asyncio.run(sb.run_tool(run, api, timeout=3))
    except sb.SandboxError as e:
        return "BUDGET", str(e)
    except Exception as e:
        return "ERR", repr(e)
    return "OK", api.out

attacks = {
 "private attr token":  "async def run(api):\n    await api.send(api._message._state.http.token)",
 "format string":       "async def run(api):\n    await api.send('{0._message}'.format(api))",
 "fstring attr":        "async def run(api):\n    await api.send(f'{api._message}')",
 "dunder class":        "async def run(api):\n    x = [].__class__.__mro__\n    await api.send(str(x))",
 "import":              "async def run(api):\n    import os\n    await api.send('x')",
 "while true":          "async def run(api):\n    while True:\n        pass",
 "str doubling":        "async def run(api):\n    s = 'ab'\n    for i in range(30):\n        s = s + s\n    await api.send(s)",
 "str mul bomb":        "async def run(api):\n    await api.send('a' * 100000)",
 "pow":                 "async def run(api):\n    await api.send(str(9**9**9))",
 "int squaring":        "async def run(api):\n    x = 99999\n    for i in range(40):\n        x = x * x\n    await api.send(str(x))",
 "huge range":          "async def run(api):\n    for i in range(100000000):\n        pass",
 "nested loops":        "async def run(api):\n    for i in range(1000):\n        for j in range(1000):\n            pass",
 "nested comp":         "async def run(api):\n    x = [[1 for a in range(1000)] for b in range(1000)]",
 "lambda":              "async def run(api):\n    f = lambda: 1\n    await api.send('x')",
 "getattr":             "async def run(api):\n    await api.send(getattr(api,'send'))",
 "open":                "async def run(api):\n    open('/etc/passwd')",
 "eval":                "async def run(api):\n    eval('1')",
 "type":                "async def run(api):\n    type(api)",
 "unlisted api":        "async def run(api):\n    await api.kick('x')",
 "api no await":        "async def run(api):\n    api.send('x')",
 "bound method leak":   "async def run(api):\n    f = api.send\n    await f('x')",
 "pct format bomb":     "async def run(api):\n    await api.send('%99999999d' % 1)",
 "fstring spec bomb":   "async def run(api):\n    await api.send(f'{1:>99999999}')",
 "try/except swallow":  "async def run(api):\n    try:\n        pass\n    except:\n        pass",
 "assign api":          "async def run(api):\n    api = 1",
 "replace bomb":        "async def run(api):\n    await api.send('a'.replace('a','b'))",
 "two funcs":           "async def run(api):\n    pass\nasync def other(api):\n    pass",
 "nested def":          "async def run(api):\n    async def f():\n        pass",
 "sync def":            "def run(api):\n    pass",
 "generator frame":     "async def run(api):\n    x = (i for i in [1])\n    await api.send(x.gi_frame)",
 "subclasses via str":  "async def run(api):\n    await api.send(''.__class__)",
 "global":              "async def run(api):\n    global x",
 "walrus":              "async def run(api):\n    (y := 1)",
 "starred call":        "async def run(api):\n    await api.send(*['a'])",
 "send flood loop":     None,
}
bad = 0
for k, src in attacks.items():
    if src is None: continue
    r, info = attempt(src)
    ok = r in ("BLOCKED","BUDGET")
    # 'ERR' that's a normal runtime error is also safe; mark leaks only if OK
    if r == "OK": ok=False
    print(("PASS" if ok else "FAIL"), f"{k:22s}", r, str(info)[:70])
    bad += (not ok)

good = {
 "hello":  "async def run(api):\n    await api.send('hi')",
 "poll-ish loop": "async def run(api):\n    opts = ['a','b','c']\n    for i, o in enumerate(opts):\n        await api.send(f'{i+1}. {o}')",
 "random pick": "async def run(api):\n    n = await api.random_int(1, 6)\n    await api.send(f'ได้ {n}')",
 "recent summary": "async def run(api):\n    msgs = await api.recent_messages(5)\n    names = [m['author'] for m in msgs]\n    await api.send(', '.join(names))",
 "aug add": "async def run(api):\n    total = 0\n    for i in range(10):\n        total += i\n    await api.send(str(total))",
 "string add": "async def run(api):\n    s = 'a' + 'b'\n    s += 'c'\n    await api.send(s)",
 "sorted/min": "async def run(api):\n    xs = [3,1,2]\n    await api.send(str(sorted(xs)) + str(max(xs)))",
 "listcomp": "async def run(api):\n    ev = [x for x in range(20) if x % 2 == 0]\n    await api.send(str(len(ev)))",
 "kwargs": "async def run(api):\n    await api.send(str(round(3.14159, 2)))",
}
for k, src in good.items():
    r, info = attempt(src)
    ok = r == "OK"
    print(("PASS" if ok else "FAIL"), f"{k:22s}", r, str(info)[:70])
    bad += (not ok)
print("FAILED:", bad)
sys.exit(1 if bad else 0)
