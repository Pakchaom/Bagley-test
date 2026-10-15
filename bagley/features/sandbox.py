"""bagley/features/sandbox.py — ตัวตรวจ + รันโค้ด Python ชั่วคราวที่ AI เขียน แบบ "อนุญาตเฉพาะที่ระบุ" (allowlist)

ทำไมต้องเขียนใหม่: ของเดิมกันด้วยการหาคำต้องห้ามในข้อความ (blacklist) ซึ่งพลาดได้ง่าย เช่น
  - api._message._state.http.token  (เข้าถึง token ของบอทผ่าน attribute ที่ขึ้นต้นด้วย _ เดี่ยว)
  - "{0._message}".format(api)       (format string แอบอ่าน attribute)
  - while True: pass                 (ลูปไม่มี await ค้างทั้งบอท เพราะ wait_for ขัดจังหวะไม่ได้)
  - s = s + s วนซ้ำ                   (ระเบิดหน่วยความจำ)

แนวทางใหม่: แปลงโค้ดเป็น AST แล้ว "ยอมรับเฉพาะ node/attribute/ชื่อ ที่อยู่ในรายการอนุญาต" ที่เหลือปฏิเสธหมด
และแม้ AI จะถูกหลอกให้เขียนอะไรมา ก็ทำได้แค่เรียกเมธอดที่ระบุใน API_METHODS เท่านั้น
(ความปลอดภัยไม่ขึ้นกับว่า AI "ว่านอนสอนง่าย" หรือเปล่า)

ข้อจำกัดที่ตั้งใจ: ไม่มี import / while / try / lambda / class / ฟังก์ชันซ้อน / ** / str.format / f-string format spec
ลูป for ถูกนับขั้น (tick) รวมไม่เกิน MAX_TICKS และ range() ยาวไม่เกิน 1000 -> รันบนอีเวนต์ลูปได้โดยไม่ค้างบอท
"""
from __future__ import annotations

import ast
import asyncio
import builtins as _py_builtins
from typing import Callable, Iterable

MAX_SOURCE_CHARS = 4000
MAX_NODES = 700
MAX_TICKS = 2500
MAX_RANGE = 1000
MAX_STR_CONST = 400
MAX_SEQ_LEN = 8000

# เมธอดของ api ที่โค้ดเรียกได้ (ตั้งจากฝั่ง ephemeral_tools ตอนเริ่ม)
DEFAULT_API_METHODS: frozenset = frozenset()

# เมธอดของ str/list/dict/set ที่ปลอดภัย (ไม่มี format/replace/ljust/center ที่สร้างข้อความยักษ์ได้)
SAFE_METHODS = frozenset({
    "lower", "upper", "strip", "lstrip", "rstrip", "split", "join", "startswith", "endswith",
    "find", "count", "title", "capitalize", "isdigit", "isalpha", "index",
    "append", "extend", "sort", "reverse", "pop", "copy",
    "get", "items", "keys", "values", "update", "setdefault",
    "add", "discard", "union",
})

SAFE_BUILTIN_NAMES = (
    "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple", "min", "max", "sum",
    "sorted", "abs", "round", "enumerate", "zip", "any", "all", "reversed", "range",
)

_RESERVED_STORE = set(SAFE_BUILTIN_NAMES) | {"api", "run", "True", "False", "None"}

_ALLOWED_NODES = (
    ast.Module, ast.AsyncFunctionDef, ast.arguments, ast.arg,
    ast.Expr, ast.Assign, ast.AugAssign, ast.If, ast.For, ast.Return, ast.Pass, ast.Break, ast.Continue,
    ast.Await, ast.Call, ast.Attribute, ast.Name, ast.Load, ast.Store, ast.Constant,
    ast.JoinedStr, ast.FormattedValue, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript, ast.Slice,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.ListComp, ast.comprehension,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.keyword,
)


class SandboxError(Exception):
    """โค้ดไม่ผ่านการตรวจ / ทำงานเกินขอบเขต"""


class BudgetExceeded(BaseException):
    """ใช้ทรัพยากรเกินกำหนด — สืบทอดจาก BaseException กัน except Exception กลืน"""


# ----------------------------------------------------------------------------
# ตรวจ AST
# ----------------------------------------------------------------------------

def validate(source: str, api_methods: Iterable[str]) -> ast.Module:
    api_methods = frozenset(api_methods)
    if not isinstance(source, str) or not source.strip():
        raise SandboxError("ไม่มีโค้ด")
    if len(source) > MAX_SOURCE_CHARS:
        raise SandboxError("โค้ดยาวเกินไป")
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise SandboxError(f"syntax error: {e.msg}") from None

    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.AsyncFunctionDef) or tree.body[0].name != "run":
        raise SandboxError("ต้องมีเฉพาะ async def run(api): เพียงฟังก์ชันเดียว")
    fn = tree.body[0]
    a = fn.args
    if (len(a.args) != 1 or a.args[0].arg != "api" or a.vararg or a.kwarg or a.kwonlyargs or a.defaults
            or a.posonlyargs or fn.decorator_list or fn.returns):
        raise SandboxError("signature ต้องเป็น async def run(api) เท่านั้น")

    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise SandboxError("โค้ดซับซ้อนเกินไป")

    parents = {}
    for p in nodes:
        for c in ast.iter_child_nodes(p):
            parents[c] = p

    for n in nodes:
        if not isinstance(n, _ALLOWED_NODES):
            raise SandboxError(f"ไม่อนุญาตให้ใช้ {type(n).__name__}")

        if isinstance(n, ast.AsyncFunctionDef) and n is not fn:
            raise SandboxError("ห้ามประกาศฟังก์ชันซ้อน")

        if isinstance(n, ast.Name):
            if n.id.startswith("_"):
                raise SandboxError("ห้ามใช้ชื่อที่ขึ้นต้นด้วย _")
            if isinstance(n.ctx, ast.Store) and n.id in _RESERVED_STORE:
                raise SandboxError(f"ห้ามกำหนดค่าทับชื่อ {n.id}")

        elif isinstance(n, ast.arg):
            if n.arg != "api":
                raise SandboxError("พารามิเตอร์ไม่ถูกต้อง")

        elif isinstance(n, ast.Attribute):
            if n.attr.startswith("_"):
                raise SandboxError("ห้ามเข้าถึง attribute ที่ขึ้นต้นด้วย _")
            if isinstance(n.ctx, ast.Store):
                raise SandboxError("ห้ามกำหนดค่าให้ attribute")
            if isinstance(n.value, ast.Name) and n.value.id == "api":
                if n.attr not in api_methods:
                    raise SandboxError(f"api.{n.attr} ไม่มีให้ใช้")
            elif n.attr not in SAFE_METHODS:
                raise SandboxError(f"ไม่อนุญาต attribute .{n.attr}")
            # attribute ต้องถูกเรียกเป็นเมธอดเท่านั้น (ไม่ปล่อย bound method ลอยๆ)
            par = parents.get(n)
            if not (isinstance(par, ast.Call) and par.func is n):
                raise SandboxError("เมธอดต้องถูกเรียกใช้ทันที")

        elif isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                if f.id not in SAFE_BUILTIN_NAMES:
                    raise SandboxError(f"เรียกฟังก์ชัน {f.id} ไม่ได้")
            elif not isinstance(f, ast.Attribute):
                raise SandboxError("รูปแบบการเรียกฟังก์ชันไม่ถูกต้อง")
            for arg in n.args:
                if isinstance(arg, ast.Starred):
                    raise SandboxError("ห้ามใช้ *args")
            for kw in n.keywords:
                if kw.arg is None:
                    raise SandboxError("ห้ามใช้ **kwargs")
            # api.xxx(...) ต้องมี await ครอบเสมอ และ await ใช้กับ api.xxx เท่านั้น
            is_api = isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "api"
            par = parents.get(n)
            if is_api and not isinstance(par, ast.Await):
                raise SandboxError("เรียก api ต้องมี await")
            if isinstance(par, ast.Await) and not is_api:
                raise SandboxError("await ใช้ได้กับ api.xxx(...) เท่านั้น")

        elif isinstance(n, ast.Await):
            if not isinstance(n.value, ast.Call):
                raise SandboxError("await ผิดรูปแบบ")

        elif isinstance(n, ast.Constant):
            v = n.value
            if isinstance(v, str) and len(v) > MAX_STR_CONST:
                raise SandboxError("ข้อความคงที่ยาวเกินไป")
            if isinstance(v, (bytes, complex)) or v is Ellipsis:
                raise SandboxError("ชนิดค่าคงที่ไม่รองรับ")
            if isinstance(v, int) and not isinstance(v, bool) and abs(v) > 10**9:
                raise SandboxError("ตัวเลขใหญ่เกินไป")

        elif isinstance(n, ast.FormattedValue):
            if n.format_spec is not None:
                raise SandboxError("ห้ามใช้ format spec ใน f-string")

        elif isinstance(n, ast.ListComp):
            if len(n.generators) != 1 or n.generators[0].is_async or len(n.generators[0].ifs) > 1:
                raise SandboxError("list comprehension ต้องมี for เดียว")
            anc = parents.get(n)
            while anc is not None:
                if isinstance(anc, ast.ListComp):
                    raise SandboxError("ห้ามซ้อน list comprehension")
                anc = parents.get(anc)

        elif isinstance(n, ast.For):
            if n.orelse:
                raise SandboxError("ห้ามใช้ for-else")

        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Attribute):
                    raise SandboxError("ห้ามกำหนดค่าให้ attribute")

    return tree


# ----------------------------------------------------------------------------
# แปลง AST: นับขั้นลูป + หุ้ม + * % ให้ตรวจขนาดผลลัพธ์
# ----------------------------------------------------------------------------

class _Instrument(ast.NodeTransformer):
    def visit_For(self, node: ast.For):
        self.generic_visit(node)
        tick = ast.Expr(ast.Call(ast.Name("_tick", ast.Load()), [], []))
        node.body.insert(0, tick)
        return node

    def visit_ListComp(self, node: ast.ListComp):
        self.generic_visit(node)
        node.elt = ast.Call(ast.Name("_tickv", ast.Load()), [node.elt], [])
        return node

    def visit_BinOp(self, node: ast.BinOp):
        self.generic_visit(node)
        name = {ast.Add: "_add", ast.Mult: "_mul", ast.Mod: "_mod"}.get(type(node.op))
        if name:
            return ast.Call(ast.Name(name, ast.Load()), [node.left, node.right], [])
        return node

    def visit_AugAssign(self, node: ast.AugAssign):
        self.generic_visit(node)
        name = {ast.Add: "_add", ast.Mult: "_mul", ast.Mod: "_mod"}.get(type(node.op))
        if name and isinstance(node.target, (ast.Name, ast.Subscript)):
            target_load = _copy_as_load(node.target)
            return ast.Assign([node.target], ast.Call(ast.Name(name, ast.Load()), [target_load, node.value], []))
        return node


def _copy_as_load(node):
    import copy
    n = copy.deepcopy(node)
    for sub in ast.walk(n):
        if hasattr(sub, "ctx"):
            sub.ctx = ast.Load()
    return n


class _Runtime:
    """ตัวนับ/ตัวตรวจขนาดที่ผูกกับการรัน 1 ครั้ง"""

    def __init__(self):
        self.ticks = 0

    def tick(self, n: int = 1):
        self.ticks += n
        if self.ticks > MAX_TICKS:
            raise BudgetExceeded("ลูปเยอะเกินกำหนด")

    def tickv(self, v):
        self.tick()
        return v

    @staticmethod
    def _size_check(v):
        if isinstance(v, (str, list, tuple)) and len(v) > MAX_SEQ_LEN:
            raise BudgetExceeded("ข้อมูลใหญ่เกินกำหนด")
        return v

    def add(self, a, b):
        return self._size_check(a + b)

    def mul(self, a, b):
        num = (int, float)
        if isinstance(a, num) and isinstance(b, num):
            if abs(a) > 10**12 or abs(b) > 10**12:
                raise BudgetExceeded("ตัวเลขใหญ่เกินกำหนด")
            return a * b
        seq, k = (a, b) if isinstance(a, (str, list, tuple)) else (b, a)
        if not isinstance(seq, (str, list, tuple)) or not isinstance(k, int) or isinstance(k, bool):
            raise BudgetExceeded("การคูณไม่รองรับ")
        if k < 0 or len(seq) * k > 2000:
            raise BudgetExceeded("ผลคูณใหญ่เกินกำหนด")
        return seq * k

    @staticmethod
    def mod(a, b):
        if isinstance(a, str):
            raise BudgetExceeded("ไม่รองรับ % กับข้อความ (ใช้ f-string แทน)")
        return a % b

    def safe_range(self, *args):
        r = range(*args)
        if len(r) > MAX_RANGE:
            raise BudgetExceeded("range ยาวเกินกำหนด")
        self.tick(len(r) // 4)  # คิดค่าใช้จ่ายตามความยาว กันซ้อนหลายชั้น
        return r


def compile_tool(source: str, api_methods: Iterable[str]) -> Callable:
    """ตรวจ + คอมไพล์ แล้วคืนฟังก์ชัน run(api) (async) ที่พร้อมรัน"""
    tree = validate(source, api_methods)
    tree = ast.fix_missing_locations(_Instrument().visit(tree))
    code = compile(tree, "<ephemeral>", "exec")

    rt = _Runtime()
    builtins = {n: getattr(_py_builtins, n) for n in SAFE_BUILTIN_NAMES if n != "range"}
    builtins["range"] = rt.safe_range
    glb = {
        "__builtins__": builtins,
        "_tick": rt.tick, "_tickv": rt.tickv, "_add": rt.add, "_mul": rt.mul, "_mod": rt.mod,
    }
    ns: dict = {}
    exec(code, glb, ns)  # noqa: S102 — ผ่าน allowlist แล้ว และ builtins จำกัด
    run = ns.get("run") or glb.get("run")
    if run is None:
        raise SandboxError("ไม่พบ run")
    return run


async def run_tool(run: Callable, api, timeout: float = 8.0):
    try:
        return await asyncio.wait_for(run(api), timeout=timeout)
    except BudgetExceeded as e:
        raise SandboxError(f"ใช้ทรัพยากรเกินกำหนด: {e}") from None
