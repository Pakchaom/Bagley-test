"""
bagley/ai/provider.py — ชั้นเชื่อมต่อ AI ของแบ็คลี่ (แทนที่ Gemini ทั้งหมด)

ใช้ API แบบ OpenAI-compatible (chat/completions) ผ่าน aiohttp ที่บอทมีอยู่แล้ว
จึง "ไม่ต้องลงไลบรารีเพิ่ม" รองรับหลายเจ้าพร้อมสลับสำรองอัตโนมัติ:

  gemini      gemini-3.1-flash-lite       (โมเดลเดิมของแบ็คลี่ ใช้ GEMINI_API_KEY เดิม อ่านรูปได้)
  groq        openai/gpt-oss-20b / 120b   (เร็วสุด, ฟรี ~1,000 req/วัน)
  cerebras    gpt-oss-120b                (เร็วมาก, ฟรี ~1M token/วัน)
  github      openai/gpt-4.1-mini         (GPT จริง + อ่านรูปได้, ฟรี ~150 req/วัน)
  openrouter  openai/gpt-oss-*:free       (ตัวสำรอง)
  openai      gpt-4.1 / gpt-4.1-mini      (ถ้ามี OPENAI_API_KEY ของจริง — ไม่ฟรี)
  custom      AI_BASE_URL / AI_API_KEY / AI_MODEL (เจ้าอื่นที่ใช้ฟอร์แมตเดียวกัน)

ระดับโมเดล (tier):
  fast    งานจัดหมวด/ตรวจคำหยาบ/แกะ JSON — ต้องไว ใช้โมเดลเล็ก
  chat    คุยจริง/เล่าเรื่อง/เขียนข้อความแจ้งเตือน — ใช้โมเดลใหญ่
  vision  อ่านรูปภาพ

คุณสมบัติ: keep-alive session เดียว, จำกัด RPM/TPM/RPD ต่อเจ้า, ตกไปเจ้าถัดไปทันทีเมื่อ
429/timeout/5xx, cooldown ตาม retry-after, แคชคำตอบงานจัดหมวด และมี
`client.aio.models.generate_content(...)` แบบเดียวกับ Gemini เดิม โค้ดเก่าจึงใช้ต่อได้ทันที
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import re
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Optional

TIERS = ("fast", "chat", "vision")


# ----------------------------------------------------------------------------
# ข้อผิดพลาด
# ----------------------------------------------------------------------------
class AIError(Exception):
    """AI ใช้ไม่ได้ทุกเจ้าในตอนนี้"""


class _Retryable(Exception):
    def __init__(self, msg, cooldown=15.0):
        super().__init__(msg)
        self.cooldown = cooldown


class _BadParam(Exception):
    """เจ้านี้ไม่รองรับพารามิเตอร์บางตัว (400) -> ลองใหม่แบบเรียบง่าย"""


# ----------------------------------------------------------------------------
# ข้อมูลเจ้าบริการ
# ----------------------------------------------------------------------------
@dataclass
class ProviderSpec:
    name: str
    base_url: str
    key_envs: tuple
    models: dict                      # tier -> model id (None = ไม่รองรับ tier นี้)
    rpm: int = 30
    tpm: int = 0                      # 0 = ไม่จำกัด
    rpd: int = 0                      # 0 = ไม่จำกัด
    max_prompt_chars: int = 0         # 0 = ไม่ตัด (GitHub Models จำกัด input ~8K token)
    reasoning: str = ""               # "effort" | "openrouter" | ""
    headers: dict = field(default_factory=dict)
    concurrency: int = 4


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _builtin_specs() -> dict:
    g = lambda k, d: os.getenv(k, d)  # noqa: E731
    gem = g("GEMINI_MODEL", "gemini-3.1-flash-lite")
    return {
        # Gemini ผ่าน endpoint แบบ OpenAI-compatible ของ Google (ใช้ key เดิมใน .env ได้เลย)
        "gemini": ProviderSpec(
            "gemini", "https://generativelanguage.googleapis.com/v1beta/openai", ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            {"fast": g("GEMINI_MODEL_FAST", gem), "chat": g("GEMINI_MODEL_CHAT", gem),
             "vision": g("GEMINI_MODEL_VISION", gem)},
            rpm=_env_int("GEMINI_RPM", 14), tpm=0, rpd=_env_int("GEMINI_RPD", 0), reasoning=""),
        "groq": ProviderSpec(
            "groq", "https://api.groq.com/openai/v1", ("GROQ_API_KEY",),
            {"fast": g("GROQ_MODEL_FAST", "openai/gpt-oss-20b"),
             "chat": g("GROQ_MODEL_CHAT", "openai/gpt-oss-120b"),
             "vision": os.getenv("GROQ_MODEL_VISION") or None},
            rpm=_env_int("GROQ_RPM", 28), tpm=_env_int("GROQ_TPM", 7500), rpd=_env_int("GROQ_RPD", 950),
            reasoning="effort"),
        "cerebras": ProviderSpec(
            "cerebras", "https://api.cerebras.ai/v1", ("CEREBRAS_API_KEY",),
            {"fast": g("CEREBRAS_MODEL_FAST", "gpt-oss-120b"),
             "chat": g("CEREBRAS_MODEL_CHAT", "gpt-oss-120b"),
             "vision": os.getenv("CEREBRAS_MODEL_VISION") or None},
            rpm=_env_int("CEREBRAS_RPM", 28), tpm=_env_int("CEREBRAS_TPM", 55000), rpd=_env_int("CEREBRAS_RPD", 0),
            reasoning="effort"),
        "github": ProviderSpec(
            "github", "https://models.github.ai/inference", ("GITHUB_TOKEN", "GITHUB_MODELS_TOKEN"),
            {"fast": g("GITHUB_MODEL_FAST", "openai/gpt-4.1-mini"),
             "chat": g("GITHUB_MODEL_CHAT", "openai/gpt-4.1-mini"),
             "vision": g("GITHUB_MODEL_VISION", "openai/gpt-4.1-mini")},
            rpm=_env_int("GITHUB_RPM", 14), tpm=0, rpd=_env_int("GITHUB_RPD", 140),
            max_prompt_chars=_env_int("GITHUB_MAX_PROMPT_CHARS", 15000),
            headers={"X-GitHub-Api-Version": "2022-11-28"}),
        "openrouter": ProviderSpec(
            "openrouter", "https://openrouter.ai/api/v1", ("OPENROUTER_API_KEY",),
            {"fast": g("OPENROUTER_MODEL_FAST", "openai/gpt-oss-20b:free"),
             "chat": g("OPENROUTER_MODEL_CHAT", "openai/gpt-oss-120b:free"),
             "vision": os.getenv("OPENROUTER_MODEL_VISION") or None},
            rpm=_env_int("OPENROUTER_RPM", 18), tpm=0, rpd=_env_int("OPENROUTER_RPD", 48),
            reasoning="openrouter",
            headers={"HTTP-Referer": "https://github.com/bagley-bot", "X-Title": "Bagley Discord Bot"}),
        "openai": ProviderSpec(
            "openai", "https://api.openai.com/v1", ("OPENAI_API_KEY",),
            {"fast": g("OPENAI_MODEL_FAST", "gpt-4.1-mini"),
             "chat": g("OPENAI_MODEL_CHAT", "gpt-4.1-mini"),
             "vision": g("OPENAI_MODEL_VISION", "gpt-4.1-mini")},
            rpm=_env_int("OPENAI_RPM", 300), tpm=0, rpd=0),
        "custom": ProviderSpec(
            "custom", (os.getenv("AI_BASE_URL") or "").rstrip("/"), ("AI_API_KEY",),
            {"fast": os.getenv("AI_MODEL_FAST") or os.getenv("AI_MODEL"),
             "chat": os.getenv("AI_MODEL_CHAT") or os.getenv("AI_MODEL"),
             "vision": os.getenv("AI_MODEL_VISION") or None},
            rpm=_env_int("AI_RPM", 30)),
    }


# ลำดับความสำคัญเริ่มต้นของแต่ละ tier (ตัวที่ไม่มี key จะถูกข้ามเอง)
_DEFAULT_ORDER = {
    "fast":   "custom,gemini,groq,cerebras,openrouter,github,openai",
    "chat":   "custom,gemini,cerebras,groq,github,openrouter,openai",
    "vision": "custom,gemini,github,openai,openrouter,groq,cerebras",
}


# ----------------------------------------------------------------------------
# ตัวนับโควต้าต่อเจ้า
# ----------------------------------------------------------------------------
class _Limiter:
    def __init__(self, spec: ProviderSpec):
        self.spec = spec
        self._req = deque()          # timestamp ของ request ใน 60 วิล่าสุด
        self._tok = deque()          # (timestamp, tokens)
        self._day_key = None
        self._day_count = 0
        self.cooldown_until = 0.0
        self.sem = asyncio.Semaphore(spec.concurrency)

    def _roll(self, now: float):
        while self._req and now - self._req[0] > 60:
            self._req.popleft()
        while self._tok and now - self._tok[0][0] > 60:
            self._tok.popleft()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        if day != self._day_key:
            self._day_key, self._day_count = day, 0

    def wait_needed(self, est_tokens: int, now: Optional[float] = None) -> float:
        """วินาทีที่ต้องรอก่อนใช้เจ้านี้ได้ (0 = ใช้ได้เลย, inf = วันนี้หมดโควต้า/ใหญ่เกินไป)"""
        now = now or time.time()
        self._roll(now)
        s = self.spec
        if now < self.cooldown_until:
            return self.cooldown_until - now
        if s.rpd and self._day_count >= s.rpd:
            return float("inf")
        if s.tpm and est_tokens > s.tpm:
            return float("inf")
        wait = 0.0
        if s.rpm and len(self._req) >= s.rpm:
            wait = max(wait, 60 - (now - self._req[0]) + 0.05)
        if s.tpm:
            used = sum(t for _, t in self._tok)
            if used + est_tokens > s.tpm and self._tok:
                # รอจน request เก่าที่สุดหลุดหน้าต่าง 60 วิ
                wait = max(wait, 60 - (now - self._tok[0][0]) + 0.05)
        return wait

    def consume(self, est_tokens: int, now: Optional[float] = None):
        now = now or time.time()
        self._roll(now)
        self._req.append(now)
        self._tok.append((now, est_tokens))
        self._day_count += 1

    def cool(self, seconds: float):
        self.cooldown_until = max(self.cooldown_until, time.time() + seconds)


# ----------------------------------------------------------------------------
# ผลลัพธ์
# ----------------------------------------------------------------------------
@dataclass
class ToolCall:
    name: str
    args: dict


class AIResponse:
    def __init__(self, text: str = "", tool_calls: Optional[list] = None,
                 provider: str = "", model: str = "", latency: float = 0.0):
        self.text = text or ""
        self.tool_calls = tool_calls or []
        self.provider = provider
        self.model = model
        self.latency = latency

    def __bool__(self):
        return bool(self.text or self.tool_calls)

    def __repr__(self):
        return f"<AIResponse {self.provider}/{self.model} {self.latency:.2f}s text={self.text[:40]!r}>"


# ----------------------------------------------------------------------------
# ตัวแปลงเนื้อหา (ข้อความ / รูป PIL) -> ฟอร์แมต OpenAI
# ----------------------------------------------------------------------------
def _pil_to_data_url(img, max_side: int = 1024) -> str:
    try:
        im = img.convert("RGB")
        w, h = im.size
        scale = max(w, h) / float(max_side)
        if scale > 1:
            im = im.resize((max(1, int(w / scale)), max(1, int(h / scale))))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:  # pragma: no cover
        raise AIError(f"แปลงรูปไม่สำเร็จ: {e}")


def split_contents(contents) -> tuple:
    """รับ str | list[str | PIL.Image | bytes] -> (prompt_text, [data_url,...])"""
    if isinstance(contents, str):
        return contents, []
    texts, images = [], []
    for part in (contents or []):
        if isinstance(part, str):
            texts.append(part)
        elif isinstance(part, (bytes, bytearray)):
            images.append("data:image/jpeg;base64," + base64.b64encode(bytes(part)).decode())
        elif hasattr(part, "convert") and hasattr(part, "size"):
            images.append(_pil_to_data_url(part))
        elif isinstance(part, dict) and "text" in part:
            texts.append(str(part["text"]))
        else:
            texts.append(str(part))
    return "\n".join(texts), images


_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def strip_json_fence(text: str) -> str:
    return _JSON_FENCE.sub("", (text or "").strip()).strip()


def _estimate_tokens(*chunks) -> int:
    n = 0
    for c in chunks:
        if not c:
            continue
        n += len(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))
    # ไทยกินโทเคนหนัก ประมาณ 1 โทเคน ~ 2 ตัวอักษร (เผื่อไว้ไม่ให้ชนลิมิต)
    return n // 2 + 40


# ----------------------------------------------------------------------------
# ตัวไคลเอนต์หลัก
# ----------------------------------------------------------------------------
class AIClient:
    def __init__(self):
        self.specs = _builtin_specs()
        self._limiters: dict = {}
        self._session = None
        self._cache: "OrderedDict[str, tuple]" = OrderedDict()
        self._cache_max = 200
        self._bad_params: set = set()     # (provider, param) ที่เจ้านั้นไม่รองรับ
        self.stats: dict = {}
        self.debug = os.getenv("AI_DEBUG", "").lower() in ("1", "true", "yes")
        self.orders = {t: self._parse_order(t) for t in TIERS}
        self.aio = _Aio(self)             # ให้ client.aio.models.generate_content(...) ใช้ได้เหมือน Gemini

    # ---------- การตั้งค่า ----------
    def _key(self, spec: ProviderSpec) -> str:
        for env in spec.key_envs:
            v = (os.getenv(env) or "").strip()
            if v:
                return v
        return ""

    def _parse_order(self, tier: str) -> list:
        raw = os.getenv(f"AI_ORDER_{tier.upper()}") or os.getenv("AI_PROVIDER_ORDER") or _DEFAULT_ORDER[tier]
        out = []
        for name in [x.strip().lower() for x in raw.split(",") if x.strip()]:
            spec = self.specs.get(name)
            if not spec or not self._key(spec) or not spec.base_url:
                continue
            if not spec.models.get(tier):
                continue
            out.append(name)
        return out

    def reload(self):
        """อ่าน .env ใหม่ (เรียกหลัง load_dotenv)"""
        self.specs = _builtin_specs()
        self.orders = {t: self._parse_order(t) for t in TIERS}

    def available(self, tier: str = "chat") -> list:
        return list(self.orders.get(tier, []))

    def _limiter(self, name: str) -> _Limiter:
        lim = self._limiters.get(name)
        if lim is None:
            lim = self._limiters[name] = _Limiter(self.specs[name])
        return lim

    # ---------- HTTP ----------
    async def _get_session(self):
        import aiohttp
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=40, ttl_dns_cache=300, keepalive_timeout=60),
                headers={"User-Agent": "BagleyBot/2.0"},
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _post_json(self, spec: ProviderSpec, payload: dict, timeout: float) -> dict:
        """ยิงจริง (ทดสอบแทนที่เมธอดนี้ได้) — คืน dict ของ JSON หรือโยน _Retryable/_BadParam"""
        import aiohttp
        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self._key(spec)}", "Content-Type": "application/json", **spec.headers}
        url = f"{spec.base_url}/chat/completions"
        try:
            async with session.post(url, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                body = await r.text()
                if r.status == 200:
                    return json.loads(body)
                low = body.lower()
                if r.status == 429:
                    ra = r.headers.get("retry-after") or r.headers.get("x-ratelimit-reset-requests")
                    try:
                        cd = float(re.findall(r"[\d.]+", str(ra))[0]) if ra else 20.0
                    except Exception:
                        cd = 20.0
                    m = re.search(r'retrydelay"\s*:\s*"(\d+(?:\.\d+)?)s', low)
                    if m:
                        cd = float(m.group(1))
                    if "per day" in low or "perday" in low or "tpd" in low or "daily" in low:
                        cd = max(cd, 1800.0)
                    raise _Retryable(f"429 {body[:160]}", cooldown=min(max(cd, 3.0), 3600.0))
                if r.status in (500, 502, 503, 504, 408, 529):
                    raise _Retryable(f"{r.status} {body[:120]}", cooldown=10.0)
                if r.status in (401, 403):
                    raise _Retryable(f"{r.status} key/สิทธิ์ใช้ไม่ได้: {body[:120]}", cooldown=900.0)
                if r.status in (400, 404, 422):
                    raise _BadParam(f"{r.status} {body[:300]}")
                raise _Retryable(f"{r.status} {body[:120]}", cooldown=10.0)
        except asyncio.TimeoutError:
            raise _Retryable("timeout", cooldown=8.0)
        except aiohttp.ClientError as e:
            raise _Retryable(f"network: {e}", cooldown=8.0)

    # ---------- สร้าง payload ----------
    def _build_payload(self, spec: ProviderSpec, tier: str, messages: list, *, temperature, max_tokens,
                       tools, effort, json_mode, use_extras: bool) -> dict:
        p: dict = {"model": spec.models[tier], "messages": messages}
        if temperature is not None:
            p["temperature"] = temperature
        if max_tokens:
            key = "max_completion_tokens" if (spec.name, "max_tokens") in self._bad_params else "max_tokens"
            p[key] = max_tokens
        if tools:
            p["tools"] = tools
            p["tool_choice"] = "auto"
        if use_extras:
            if effort and spec.reasoning == "effort" and (spec.name, "reasoning_effort") not in self._bad_params:
                p["reasoning_effort"] = effort
            elif effort and spec.reasoning == "openrouter" and (spec.name, "reasoning") not in self._bad_params:
                p["reasoning"] = {"effort": effort}
            if json_mode and (spec.name, "response_format") not in self._bad_params:
                p["response_format"] = {"type": "json_object"}
        return p

    @staticmethod
    def _parse_response(data: dict, spec: ProviderSpec, tier: str, t0: float) -> AIResponse:
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise _Retryable(f"รูปแบบคำตอบแปลก: {str(data)[:120]}", cooldown=5.0)
        text = msg.get("content") or ""
        if isinstance(text, list):  # บางเจ้าส่งเป็นชิ้นๆ
            text = "".join(c.get("text", "") for c in text if isinstance(c, dict))
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if fn.get("name"):
                calls.append(ToolCall(fn["name"], args if isinstance(args, dict) else {}))
        # กันโมเดลเผลอพ่นแท็กความคิดออกมา
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        return AIResponse(text, calls, spec.name, spec.models[tier], time.time() - t0)

    # ---------- เรียกหลัก ----------
    async def ask(self, prompt: str = "", *, system: Optional[str] = None, tier: str = "chat",
                  images: Optional[list] = None, messages: Optional[list] = None,
                  temperature: Optional[float] = None, max_tokens: Optional[int] = None,
                  tools: Optional[list] = None, effort: Optional[str] = None, json_mode: bool = False,
                  timeout: Optional[float] = None, cache_ttl: int = 0, wait_budget: float = 6.0) -> AIResponse:
        """ถามโมเดล 1 ครั้ง (ตกสำรองให้เองถ้าเจ้าหลักเต็ม/ล่ม)

        tier        fast | chat | vision   (ถ้าแนบ images จะบังคับเป็น vision)
        effort      low|medium|high  ความลึกในการคิดของ gpt-oss (ค่าเริ่มต้น: fast=low, chat=low)
        cache_ttl   วินาที ถ้า >0 จะแคชคำตอบของ prompt เดิม (เหมาะกับงานจัดหมวด temperature=0)
        """
        if images:
            tier = "vision"
        if tier not in TIERS:
            tier = "chat"
        if effort is None:
            effort = "low"
        if temperature is None and tier == "chat":
            temperature = 0.85  # คุยเล่น/แต่งประโยค: ให้หลากหลายขึ้น ไม่ซ้ำเดิม
        if timeout is None:
            timeout = 12.0 if tier == "fast" else 30.0
        if max_tokens is None:
            max_tokens = 700 if tier == "fast" else 1400

        # --- แคช ---
        ckey = None
        if cache_ttl > 0 and not images and not tools:
            ckey = hashlib.sha1(f"{tier}|{system}|{prompt}|{temperature}".encode()).hexdigest()
            hit = self._cache.get(ckey)
            if hit and hit[0] > time.time():
                self._cache.move_to_end(ckey)
                return hit[1]

        # --- ประกอบ messages ---
        if messages is None:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            if images:
                content = [{"type": "text", "text": prompt}]
                for url in images:
                    content.append({"type": "image_url", "image_url": {"url": url, "detail": "low"}})
                messages.append({"role": "user", "content": content})
            else:
                messages.append({"role": "user", "content": prompt})

        order = self.orders.get(tier) or []
        if not order:
            self.reload()  # .env อาจเพิ่งถูกโหลดหลังสร้างตัวไคลเอนต์
            order = self.orders.get(tier) or []
        if not order:
            raise AIError(
                "ยังไม่ได้ตั้งค่า API key ของ AI เลย — ใส่ GROQ_API_KEY หรือ CEREBRAS_API_KEY ใน .env "
                "(ดูตัวอย่างใน .env.example)")

        est = _estimate_tokens(system, prompt, tools) + (400 if images else 0) + max_tokens // 4
        deadline = time.time() + wait_budget + timeout
        last_err: Optional[Exception] = None
        waited = False

        while True:
            soonest = None
            for name in order:
                spec = self.specs[name]
                lim = self._limiter(name)
                w = lim.wait_needed(est)
                if w > 0:
                    if w != float("inf") and (soonest is None or w < soonest):
                        soonest = w
                    continue
                msgs = self._maybe_trim(spec, messages)
                try:
                    async with lim.sem:
                        lim.consume(est)
                        resp = await self._call_one(spec, tier, msgs, temperature=temperature, max_tokens=max_tokens,
                                                    tools=tools, effort=effort, json_mode=json_mode, timeout=timeout)
                    self._stat(name, ok=True, latency=resp.latency)
                    if self.debug:
                        print(f"🧠 [AI] {resp.provider}/{resp.model} {resp.latency:.2f}s")
                    if ckey and resp.text:
                        self._cache[ckey] = (time.time() + cache_ttl, resp)
                        if len(self._cache) > self._cache_max:
                            self._cache.popitem(last=False)
                    return resp
                except _Retryable as e:
                    last_err = e
                    lim.cool(e.cooldown)
                    self._stat(name, ok=False)
                    if self.debug:
                        print(f"⚠️ [AI] {name} ล้มเหลว ({e}) -> สลับเจ้าถัดไป")
                except _BadParam as e:
                    last_err = e
                    self._stat(name, ok=False)
                    if self.debug:
                        print(f"⚠️ [AI] {name} 400: {e}")
                    lim.cool(5.0)
            # ทุกเจ้าใช้ไม่ได้ในตอนนี้ — ถ้าพอรอได้ก็รอเจ้าที่ว่างเร็วสุดแล้ววนใหม่
            if soonest is not None and not waited and time.time() + soonest < deadline and soonest <= wait_budget:
                waited = True
                await asyncio.sleep(soonest + 0.05)
                continue
            raise AIError(f"AI ทุกเจ้าใช้ไม่ได้ชั่วคราว (โควต้าเต็ม/ล่ม): {last_err}")

    async def _call_one(self, spec, tier, messages, *, temperature, max_tokens, tools, effort, json_mode, timeout):
        t0 = time.time()
        use_extras = True
        for attempt in range(3):
            payload = self._build_payload(spec, tier, messages, temperature=temperature, max_tokens=max_tokens,
                                          tools=tools, effort=effort, json_mode=json_mode, use_extras=use_extras)
            try:
                data = await self._post_json(spec, payload, timeout)
                return self._parse_response(data, spec, tier, t0)
            except _BadParam as e:
                msg = str(e).lower()
                # เรียนรู้ว่าเจ้านี้ไม่รองรับพารามิเตอร์ไหน แล้วลองใหม่แบบตัดออก
                changed = False
                for param, key in (("reasoning_effort", "reasoning_effort"), ("reasoning", "reasoning"),
                                   ("response_format", "response_format")):
                    if param in msg and (spec.name, key) not in self._bad_params:
                        self._bad_params.add((spec.name, key))
                        changed = True
                if "max_completion_tokens" in msg and "max_tokens" in payload:
                    self._bad_params.add((spec.name, "max_tokens"))
                    changed = True
                if not changed and use_extras:
                    use_extras, changed = False, True
                if not changed:
                    raise
        raise _BadParam("พารามิเตอร์ไม่เข้ากัน")

    @staticmethod
    def _maybe_trim(spec: ProviderSpec, messages: list) -> list:
        lim = spec.max_prompt_chars
        if not lim:
            return messages
        out = []
        for m in messages:
            c = m.get("content")
            if isinstance(c, str) and len(c) > lim:
                keep_head = int(lim * 0.35)
                c = c[:keep_head] + "\n...[ตัดบางส่วนเพื่อให้พอดีโควต้า]...\n" + c[-(lim - keep_head):]
                m = {**m, "content": c}
            out.append(m)
        return out

    def _stat(self, name: str, ok: bool, latency: float = 0.0):
        s = self.stats.setdefault(name, {"ok": 0, "fail": 0, "lat": 0.0})
        if ok:
            s["ok"] += 1
            s["lat"] += latency
        else:
            s["fail"] += 1

    # ---------- ค้นเว็บจริงด้วย Google Search (เฉพาะ Gemini) ----------
    async def ask_with_search(self, prompt: str, *, fallback_prompt: Optional[str] = None,
                              timeout: float = 45.0) -> AIResponse:
        """ถาม Gemini พร้อมเปิด Google Search grounding (ใช้ REST ตรงของ Google ไม่ต้องลง google-genai)
        ใช้กับงานที่ต้องหาข้อมูลจริงจากเว็บ เช่น /tell_story
        ถ้าไม่มี GEMINI_API_KEY / โควต้าเต็ม / พัง -> ตกไปถามโมเดลปกติด้วย fallback_prompt (ไม่ค้นเว็บ) แทน"""
        spec = self.specs.get("gemini")
        key = self._key(spec) if spec else ""
        if key:
            lim = self._limiter("gemini")
            est = _estimate_tokens(prompt) + 800
            if lim.wait_needed(est) == 0:
                t0 = time.time()
                try:
                    import aiohttp
                    lim.consume(est)
                    model = spec.models["chat"]
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                            "tools": [{"google_search": {}}],
                            "generationConfig": {"temperature": 0.9}}
                    session = await self._get_session()
                    async with session.post(url, json=body, headers={"x-goog-api-key": key},
                                            timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                        raw = await r.text()
                        if r.status == 200:
                            data = json.loads(raw)
                            parts = data["candidates"][0]["content"]["parts"]
                            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                            if text:
                                self._stat("gemini", ok=True, latency=time.time() - t0)
                                return AIResponse(text, [], "gemini", model, time.time() - t0)
                        elif r.status == 429:
                            lim.cool(30.0)
                        if self.debug:
                            print(f"⚠️ [AI] search grounding {r.status}: {raw[:160]}")
                except Exception as e:  # noqa: BLE001
                    lim.cool(8.0)
                    if self.debug:
                        print(f"⚠️ [AI] search grounding พลาด: {e}")
        return await self.ask(fallback_prompt or prompt, tier="chat", timeout=timeout)

    # ---------- ทางลัดที่ใช้บ่อย ----------
    async def text(self, prompt: str, **kw) -> str:
        return (await self.ask(prompt, **kw)).text.strip()

    async def classify_json(self, prompt: str, *, cache_ttl: int = 300, **kw) -> Optional[dict]:
        """งานจัดหมวดที่ตอบเป็น JSON — ใช้โมเดลเร็ว, temperature 0, แคชไว้ และไม่โยน error (คืน None ถ้าพัง)"""
        try:
            r = await self.ask(prompt, tier="fast", temperature=0, json_mode=True, cache_ttl=cache_ttl, **kw)
            return json.loads(strip_json_fence(r.text))
        except Exception as e:
            if self.debug:
                print(f"⚠️ [AI] classify_json พลาด: {e}")
            return None

    def stats_text(self) -> str:
        if not self.stats:
            return "ยังไม่มีการเรียก AI"
        rows = []
        for n, s in self.stats.items():
            avg = (s["lat"] / s["ok"]) if s["ok"] else 0
            rows.append(f"{n}: ok {s['ok']} / fail {s['fail']} / เฉลี่ย {avg:.2f}s")
        return " | ".join(rows)


# ----------------------------------------------------------------------------
# ชั้นเข้ากันได้กับ google-genai (โค้ดเดิม: client.aio.models.generate_content(...))
# ----------------------------------------------------------------------------
class _Models:
    def __init__(self, ai: AIClient):
        self._ai = ai

    async def generate_content(self, model: Optional[str] = None, contents: Any = "", config: Any = None, **_):
        prompt, images = split_contents(contents)
        tier = model if model in TIERS else "chat"
        temperature = getattr(config, "temperature", None) if config is not None else None
        if isinstance(config, dict):
            temperature = config.get("temperature")
        return await self._ai.ask(prompt, tier=tier, images=images or None, temperature=temperature)


class _Aio:
    def __init__(self, ai: AIClient):
        self.models = _Models(ai)


# ----------------------------------------------------------------------------
# อินสแตนซ์กลาง
# ----------------------------------------------------------------------------
ai = AIClient()

# ชื่อ tier สำหรับใช้แทนสตริงชื่อโมเดลเดิมทั่วโค้ด
AI_FAST = "fast"
AI_CHAT = "chat"
AI_VISION = "vision"
