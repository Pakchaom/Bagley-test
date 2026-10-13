"""bagley/core/http.py — HTTP แบบ async ใช้ session เดียว (keep-alive)
แทน requests.get() เดิมที่ "บล็อกทั้งบอท" ระหว่างรอเว็บตอบ (ทุกคนในทุกเซิร์ฟเวอร์ค้างไปด้วย)"""
import asyncio
from typing import Optional

import aiohttp

_session: Optional[aiohttp.ClientSession] = None


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=30, ttl_dns_cache=300))
    return _session


async def get_json(url: str, timeout: float = 10.0) -> dict:
    s = await _get_session()
    async with s.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
        return await r.json(content_type=None)


async def get_bytes(url: str, timeout: float = 15.0) -> bytes:
    s = await _get_session()
    async with s.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
        r.raise_for_status()
        return await r.read()


async def close():
    if _session and not _session.closed:
        await _session.close()
