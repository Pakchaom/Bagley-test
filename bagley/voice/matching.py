"""bagley/voice/matching.py — จับ "ชื่อเรียกแบ็คลี่" และ "คำสั่งที่สอนไว้" จากข้อความที่ Google ฟังได้
(ไม่พึ่ง discord ทดสอบแยกได้) ลอจิกเดียวกับแอพ mic_to_bagley.py ที่ย้ายมาฝั่งบอท
"""
from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

# ไม้เอก/โท/ตรี/จัตวา/ไม้ไต่คู้/ทัณฑฆาต — Google สะกดวรรณยุกต์ไม่คงที่ จึงตัดทิ้งก่อนเทียบ
_DROP = set("\u0e47\u0e48\u0e49\u0e4a\u0e4b\u0e4c")
_EDGE = " ,.!?-:;、。…\"'“”‘’"
THRESHOLD = 0.85
DEFAULT_WAKE = ("แบ็คลี่", "แบคลี่", "แบ็กลี่", "แบกลี่", "bagley", "baggley", "bagly")


def norm_map(text: str):
    """คืน (ข้อความที่ปรับรูปแล้ว, ตำแหน่งตัวอักษรเดิมของแต่ละตัว) — เก็บแค่ตัวอักษร/ตัวเลข ตัดช่องว่าง/เครื่องหมาย"""
    out, idx = [], []
    for i, ch in enumerate(str(text).lower()):
        if ch in _DROP:
            continue
        if unicodedata.category(ch)[0] in "LMN":
            out.append(ch)
            idx.append(i)
    return "".join(out), idx


def norm(text: str) -> str:
    return norm_map(text)[0]


def _after(text: str, idx: list, n_chars: int) -> str:
    """ข้อความเดิมส่วนที่เหลือหลังตัวอักษรปรับรูปตัวที่ n_chars"""
    if n_chars <= 0 or n_chars > len(idx):
        return ""
    t = str(text)
    start = idx[n_chars - 1] + 1
    while start < len(t) and t[start] in _DROP:      # วรรณยุกต์ที่ติดท้ายตัวสุดท้ายของชื่อ
        start += 1
    return t[start:].strip(_EDGE)


def _prefix_lengths(pn: str) -> tuple:
    # วลีสั้น (<4 ตัว) ต้องตรงเป๊ะ / วลียาวยอมคลาดเคลื่อน ±1 ตัว
    return (len(pn) - 1, len(pn), len(pn) + 1) if len(pn) >= 4 else (len(pn),)


def _ratio(a: str, b: str) -> float:
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def _best_prefix(n: str, pn: str):
    """ขึ้นต้นของ n ตรงกับ pn ที่สุดที่ความยาวเท่าไร -> (คะแนน, ความยาว) หรือ None (ต้องเหลือคำต่อท้ายด้วย)"""
    best = None
    for L in _prefix_lengths(pn):
        if 2 <= L < len(n):
            sc = _ratio(n[:L], pn)
            if sc >= THRESHOLD and (best is None or (sc, L) > best):
                best = (sc, L)
    return best


def check_wake(alts: list, phrases: list):
    """ได้ยินชื่อเรียกไหม?  คืน None / ("alone", []) = พูดแต่ชื่อ / ("with", [คำสั่งที่ตามหลังชื่อ,...])"""
    best = None   # (score, kind, remainders)
    for p in phrases:
        pn = norm(p)
        if len(pn) < 2:
            continue
        rems = []
        top = 0.0
        alone = False
        for alt in alts:
            n, idx = norm_map(alt)
            if not n:
                continue
            r = _ratio(n, pn)
            if r >= THRESHOLD and abs(len(n) - len(pn)) <= 2:
                alone = True
                top = max(top, r)
                continue
            bp = _best_prefix(n, pn)
            if bp:
                rem = _after(alt, idx, bp[1])
                if rem and rem not in rems:
                    rems.append(rem)
                top = max(top, bp[0])
        if rems:
            cand = (top, "with", rems)
        elif alone:
            cand = (top, "alone", [])
        else:
            continue
        if best is None or cand[0] > best[0]:
            best = cand
    return None if best is None else (best[1], best[2])


def match_command(alts: list, commands: list):
    """จับคำสั่งที่สอนไว้ (ทั้งประโยคตรงกับวลี หรือคำสั่งที่ติ๊ก 'มีชื่อต่อท้าย' ขึ้นต้นด้วยวลี)
    คืน {"text": "/kick สมชาย", "send": "/kick", "arg": "สมชาย"|"", "phrase", "score"} หรือ None"""
    best = None
    for cmd in commands:
        send = str(cmd.get("send", "")).strip()
        if not send:
            continue
        for p in cmd.get("phrases", []):
            pn = norm(p)
            if len(pn) < 2:
                continue
            for alt in alts:
                n, idx = norm_map(alt)
                if not n:
                    continue
                r = _ratio(n, pn)
                if r >= THRESHOLD and (best is None or r > best[0]):
                    best = (r, cmd, p, "")
                if cmd.get("args"):
                    bp = _best_prefix(n, pn)
                    if bp:
                        arg = _after(alt, idx, bp[1])
                        if arg and (best is None or bp[0] > best[0]):
                            best = (bp[0], cmd, p, arg)
    if best is None:
        return None
    score, cmd, phrase, arg = best
    send = str(cmd["send"]).strip()
    return {"text": f"{send} {arg}".strip(), "send": send, "arg": arg, "phrase": phrase, "score": score}
