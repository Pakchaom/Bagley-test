"""bagley/music/spotify.py — แปลงลิงก์ Spotify เป็นคำค้นเพลง"""
import aiohttp
import re as regex_lib
import time
import urllib.parse

from bagley.core import state
from bagley.core.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from bagley.core.logutil import print


# --- ระบบรองรับลิงก์ Spotify (แปลงเป็นชื่อเพลง+ศิลปิน แล้วให้ yt_dlp ไปหาไฟล์เสียงจาก YouTube มาเล่นแทน) ---
# หมายเหตุ: Spotify API ไม่อนุญาตให้ดึงไฟล์เสียงจริงออกมาเล่นได้ (ผิด ToS ของ Spotify)
# ดังนั้นบอทจะใช้ Spotify API แค่ "อ่านชื่อเพลง/ชื่อศิลปิน" จากลิงก์ แล้วเอาไปค้นหาบน YouTube ต่อ

SPOTIFY_HTTP_RE = regex_lib.compile(
    r"open\.spotify\.com/(?:intl-\w+/)?(?P<type>track|album|playlist|artist)/(?P<id>[a-zA-Z0-9]+)"
)


SPOTIFY_URI_RE = regex_lib.compile(
    r"^spotify:(?P<type>track|album|playlist|artist):(?P<id>[a-zA-Z0-9]+)$"
)


def parse_spotify_link(text: str):
    """แยกประเภท (track/album) และ id ออกจากลิงก์/URI ของ Spotify คืน (None, None) ถ้าไม่ใช่ลิงก์ Spotify"""
    text = text.strip()
    m = SPOTIFY_HTTP_RE.search(text)
    if not m:
        m = SPOTIFY_URI_RE.match(text)
    if not m:
        return None, None
    return m.group("type"), m.group("id")


async def get_spotify_access_token():
    """ขอ Access Token จาก Spotify ด้วย Client Credentials Flow (แคชไว้จนกว่าจะหมดอายุ)"""
    now_ts = time.time()

    if state._spotify_token_cache["access_token"] and now_ts < state._spotify_token_cache["expires_at"] - 30:
        return state._spotify_token_cache["access_token"]

    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        print("⚠️ [Spotify] ไม่พบ SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET ใน .env")
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                auth=aiohttp.BasicAuth(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
            ) as resp:
                if resp.status != 200:
                    print(f"⚠️ [Spotify] ขอ Token ไม่สำเร็จ: HTTP {resp.status}")
                    return None
                data = await resp.json()
                state._spotify_token_cache["access_token"] = data.get("access_token")
                state._spotify_token_cache["expires_at"] = now_ts + data.get("expires_in", 3600)
                return state._spotify_token_cache["access_token"]
    except Exception as e:
        print(f"⚠️ [Spotify] ขอ Token พลาด: {e}")
        return None


async def get_spotify_track_query(token, track_id):
    """ดึงชื่อเพลง+ศิลปินของ track เดี่ยว คืนเป็นข้อความสำหรับใช้ค้นหาบน YouTube"""
    try:
        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.spotify.com/v1/tracks/{track_id}", headers=headers) as resp:
                if resp.status != 200:
                    print(f"⚠️ [Spotify] ดึงข้อมูลเพลงไม่สำเร็จ: HTTP {resp.status}")
                    return None
                data = await resp.json()
                title = data.get("name", "")
                artists = ", ".join(a.get("name", "") for a in data.get("artists", []))
                query = f"{title} {artists}".strip()
                return query or None
    except Exception as e:
        print(f"⚠️ [Spotify] ดึงข้อมูลเพลงพลาด: {e}")
        return None


async def get_spotify_album_queries(token, album_id):
    """ดึงรายชื่อเพลงทั้งหมดในอัลบั้ม คืนเป็นลิสต์ข้อความสำหรับใช้ค้นหาบน YouTube (เรียงตามลำดับเพลงในอัลบั้ม)"""
    queries = []
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api.spotify.com/v1/albums/{album_id}/tracks?limit=50"

    try:
        async with aiohttp.ClientSession() as session:
            while url:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        print(f"⚠️ [Spotify] ดึงรายเพลงในอัลบั้มไม่สำเร็จ: HTTP {resp.status}")
                        break
                    data = await resp.json()
                    for item in data.get("items", []):
                        title = item.get("name", "")
                        artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
                        q = f"{title} {artists}".strip()
                        if q:
                            queries.append(q)
                    url = data.get("next")  # Spotify คืนหน้าถัดไปมาให้เลย ถ้ามีเพลงเกิน 50 เพลง
    except Exception as e:
        print(f"⚠️ [Spotify] ดึงรายเพลงในอัลบั้มพลาด: {e}")

    return queries


async def get_spotify_playlist_queries(token, playlist_id):
    """ดึงรายชื่อเพลงทั้งหมดใน playlist คืนเป็นลิสต์ข้อความสำหรับใช้ค้นหาบน YouTube (เรียงตามลำดับเพลงใน playlist)"""
    queries = []
    headers = {"Authorization": f"Bearer {token}"}
    # ขอแค่ฟิลด์ที่ต้องใช้เพื่อลด response ให้เบาลง
    url = (
        f"https://api.spotify.com/v1/playlists/{playlist_id}/items"
        f"?limit=100&fields=next,items(track(name,artists(name)))"
    )

    try:
        async with aiohttp.ClientSession() as session:
            while url:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        print(f"⚠️ [Spotify] ดึงรายเพลงใน playlist ไม่สำเร็จ: HTTP {resp.status}")
                        break
                    data = await resp.json()
                    for item in data.get("items", []):
                        track = item.get("track")
                        if not track:  # เพลงที่ถูกลบ/เพลงเฉพาะบางประเทศ อาจเป็น None
                            continue
                        title = track.get("name", "")
                        artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
                        q = f"{title} {artists}".strip()
                        if q:
                            queries.append(q)
                    url = data.get("next")  # Spotify คืนหน้าถัดไปมาให้เลย ถ้ามีเพลงเกิน 100 เพลง
    except Exception as e:
        print(f"⚠️ [Spotify] ดึงรายเพลงใน playlist พลาด: {e}")

    return queries


async def get_spotify_artist_top_tracks(token, artist_id):
    """ดึงเพลงฮิตของศิลปิน คืนเป็นลิสต์ข้อความสำหรับใช้ค้นหาบน YouTube
    หมายเหตุ: Spotify ยกเลิก endpoint /artists/{id}/top-tracks ไปแล้วตั้งแต่การอัปเดต API เดือนกุมภาพันธ์ 2026
    (ไม่มี endpoint ทดแทนโดยตรง) จึงต้องดึงชื่อศิลปินมาก่อน แล้วใช้ /search แทนเพื่อหาเพลงของศิลปินคนนั้น"""
    queries = []
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with aiohttp.ClientSession() as session:
            # 1) ดึงชื่อศิลปินจาก artist_id ก่อน (endpoint เดี่ยวนี้ยังใช้ได้ปกติ)
            async with session.get(f"https://api.spotify.com/v1/artists/{artist_id}", headers=headers) as resp:
                if resp.status != 200:
                    print(f"⚠️ [Spotify] ดึงข้อมูลศิลปินไม่สำเร็จ: HTTP {resp.status}")
                    return queries
                artist_data = await resp.json()
                artist_name = artist_data.get("name", "")

            if not artist_name:
                return queries

            # 2) ใช้ /search ค้นเพลงของศิลปินคนนี้แทน (limit สูงสุดตอนนี้คือ 10 ต่อ 1 คำขอ)
            search_url = (
                "https://api.spotify.com/v1/search"
                f"?q={urllib.parse.quote(f'artist:{artist_name}')}&type=track&limit=10"
            )
            async with session.get(search_url, headers=headers) as resp:
                if resp.status != 200:
                    print(f"⚠️ [Spotify] ค้นหาเพลงของศิลปินไม่สำเร็จ: HTTP {resp.status}")
                    return queries
                data = await resp.json()
                for track in data.get("tracks", {}).get("items", []):
                    title = track.get("name", "")
                    artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
                    q = f"{title} {artists}".strip()
                    if q:
                        queries.append(q)
    except Exception as e:
        print(f"⚠️ [Spotify] ดึงเพลงฮิตของศิลปินพลาด: {e}")

    return queries


async def resolve_spotify_link(text: str):
    """
    ถ้า text เป็นลิงก์/URI ของ Spotify (track หรือ album) จะคืนลิสต์ข้อความค้นหา (title + artist)
    ถ้าไม่ใช่ลิงก์ Spotify คืนค่า None (ให้ผู้เรียกไปประมวลผลแบบข้อความค้นหาปกติ)
    ถ้าเป็นลิงก์ Spotify แต่ดึงข้อมูลไม่สำเร็จ คืนลิสต์เปล่า []
    """
    kind, spotify_id = parse_spotify_link(text)
    if not kind:
        return None

    token = await get_spotify_access_token()
    if not token:
        return []

    if kind == "track":
        query = await get_spotify_track_query(token, spotify_id)
        return [query] if query else []
    elif kind == "album":
        return await get_spotify_album_queries(token, spotify_id)
    elif kind == "playlist":
        return await get_spotify_playlist_queries(token, spotify_id)
    elif kind == "artist":
        return await get_spotify_artist_top_tracks(token, spotify_id)

    return []
