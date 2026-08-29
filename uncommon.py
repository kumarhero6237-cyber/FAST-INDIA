import asyncio
import io
import os
import time
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, Tuple

import httpx
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# ============================================================
# FAST BANNER API
# Change only INFO_API_URL / INFO_API_KEY for your new UID API.
# ============================================================

INFO_API_URL = "https://india-dun-two.vercel.app/uc-info?uid="
INFO_API_KEY = "RAM-SAGAR"

AVATAR_ZOOM = 1.26
AVATAR_SHIFT_Y = 0
AVATAR_SHIFT_X = 0

BANNER_START_X = 0.25
BANNER_START_Y = 0.29
BANNER_END_X = 0.81
BANNER_END_Y = 0.65

BANNER_COLOR_FACTOR = 1.6
BANNER_BRIGHTNESS_FACTOR = 0.65
BANNER_CONTRAST_FACTOR = 1.8
BANNER_SHARPNESS_FACTOR = 3.0
AVATAR_SHARPNESS_FACTOR = 2.5

STROKE_NAME = 3
STROKE_GUILD = 2
STROKE_LEVEL = 3

TARGET_HEIGHT = 400

# Cache makes repeated UID requests dramatically faster.
BANNER_CACHE_TTL = 300          # 5 min
PLAYER_CACHE_TTL = 120          # 2 min
ASSET_CACHE_TTL = 1800          # 30 min
MAX_BANNER_CACHE = 256
MAX_PLAYER_CACHE = 512
MAX_ASSET_CACHE = 1024

FONT_FILE = "arial_unicode_bold.otf"
FONT_CHEROKEE = "NotoSansCherokee.ttf"

# Keep connections alive and reuse TCP/TLS connections.
HTTP_LIMITS = httpx.Limits(
    max_connections=80,
    max_keepalive_connections=40,
    keepalive_expiry=30.0,
)

uncommon_client: Optional[httpx.AsyncClient] = None
process_pool = ThreadPoolExecutor(max_workers=max(4, min(8, (os.cpu_count() or 4))))

# key -> (expires_at, value)
banner_cache: Dict[str, Tuple[float, bytes]] = {}
player_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
asset_cache: Dict[str, Tuple[float, Optional[bytes]]] = {}

# Prevent duplicate work when many requests for the same UID arrive together.
inflight: Dict[str, asyncio.Task] = {}
inflight_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global uncommon_client
    uncommon_client = httpx.AsyncClient(
        headers={
            "User-Agent": "BannerAPI/2.0",
            "Accept": "application/json,image/*,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
        },
        timeout=httpx.Timeout(5.0, connect=2.0),
        limits=HTTP_LIMITS,
        follow_redirects=True,
        http2=True,
    )
    yield
    await uncommon_client.aclose()
    process_pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def cache_get(cache, key):
    item = cache.get(key)
    if not item:
        return None
    expires, value = item
    if expires <= time.monotonic():
        cache.pop(key, None)
        return None
    return value


def cache_put(cache, key, value, ttl, max_size):
    if len(cache) >= max_size:
        # Cheap bounded-cache eviction.
        oldest = min(cache, key=lambda k: cache[k][0])
        cache.pop(oldest, None)
    cache[key] = (time.monotonic() + ttl, value)


def load_font(size: int, filename: str = FONT_FILE):
    try:
        path = os.path.join(os.path.dirname(__file__), filename)
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    return ImageFont.load_default()


async def fetch_bytes(url: str) -> Optional[bytes]:
    global uncommon_client
    if uncommon_client is None:
        return None
    try:
        r = await uncommon_client.get(url)
        if r.status_code == 200 and r.content:
            return r.content
    except (httpx.HTTPError, asyncio.TimeoutError):
        pass
    return None


async def fetch_asset(item_id: Optional[str]) -> Optional[bytes]:
    if not item_id or str(item_id) in ("0", "None", ""):
        return None

    key = str(item_id)
    cached = cache_get(asset_cache, key)
    if cached is not None:
        return cached

    # Keep your existing CDN here if needed.
    cdn_url = "https://cdn.jsdelivr.net/gh/ShahGCreator/icon@main/PNG"
    data = await fetch_bytes(f"{cdn_url}/{key}.png")

    # Cache misses too, but only briefly, to avoid hammering the CDN.
    cache_put(asset_cache, key, data, ASSET_CACHE_TTL if data else 20, MAX_ASSET_CACHE)
    return data


def bytes_to_image(data: Optional[bytes]) -> Image.Image:
    if not data:
        return Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.convert("RGBA")
    except Exception:
        return Image.new("RGBA", (100, 100), (0, 0, 0, 0))


def process_banner(data: Dict[str, Any],
                   avatar_bytes: Optional[bytes],
                   banner_bytes: Optional[bytes]) -> bytes:
    avatar_img = bytes_to_image(avatar_bytes)
    banner_img = bytes_to_image(banner_bytes)

    level = str(data.get("level") or "0")
    name = str(data.get("name") or "Unknown")
    guild = str(data.get("guild") or "")

    # Avatar
    zoom_size = int(TARGET_HEIGHT * AVATAR_ZOOM)
    avatar_img = avatar_img.resize((zoom_size, zoom_size), Image.Resampling.LANCZOS)
    center = zoom_size // 2
    half = TARGET_HEIGHT // 2
    avatar_img = avatar_img.crop((
        center - half - AVATAR_SHIFT_X,
        center - half - AVATAR_SHIFT_Y,
        center + half - AVATAR_SHIFT_X,
        center + half - AVATAR_SHIFT_Y,
    ))
    avatar_img = ImageEnhance.Sharpness(avatar_img).enhance(AVATAR_SHARPNESS_FACTOR)

    # Banner
    banner_img = ImageEnhance.Color(banner_img).enhance(BANNER_COLOR_FACTOR)
    banner_img = ImageEnhance.Contrast(banner_img).enhance(BANNER_CONTRAST_FACTOR)
    banner_img = ImageEnhance.Brightness(banner_img).enhance(BANNER_BRIGHTNESS_FACTOR)
    banner_img = banner_img.rotate(3, expand=True, resample=Image.Resampling.BICUBIC)

    bw, bh = banner_img.size
    banner_img = banner_img.crop((
        int(bw * BANNER_START_X),
        int(bh * BANNER_START_Y),
        int(bw * BANNER_END_X),
        int(bh * BANNER_END_Y),
    ))

    bw, bh = banner_img.size
    if bh <= 0:
        bh = 1
    banner_img = banner_img.resize(
        (max(1, int(TARGET_HEIGHT * (bw / bh) * 2)), TARGET_HEIGHT),
        Image.Resampling.LANCZOS,
    )
    banner_img = ImageEnhance.Sharpness(banner_img).enhance(BANNER_SHARPNESS_FACTOR)

    final = Image.new("RGBA", (avatar_img.width + banner_img.width, TARGET_HEIGHT))
    final.paste(avatar_img, (0, 0), avatar_img)
    final.paste(banner_img, (avatar_img.width, 0), banner_img)

    draw = ImageDraw.Draw(final)
    font_big = load_font(125)
    font_big_c = load_font(125, FONT_CHEROKEE)
    font_small = load_font(95)
    font_small_c = load_font(95, FONT_CHEROKEE)
    font_lvl = load_font(50)

    def is_cherokee(ch: str) -> bool:
        n = ord(ch)
        return 0x13A0 <= n <= 0x13FF or 0xAB70 <= n <= 0xABBF

    # Name
    cx = avatar_img.width + 65
    for ch in name:
        f = font_big_c if is_cherokee(ch) else font_big
        draw.text((cx, 40), ch, font=f, fill="white",
                  stroke_width=STROKE_NAME, stroke_fill="black")
        cx += f.getlength(ch)

    # Guild
    cx = avatar_img.width + 65
    for ch in guild:
        f = font_small_c if is_cherokee(ch) else font_small
        draw.text((cx, 220), ch, font=f, fill="white",
                  stroke_width=STROKE_GUILD, stroke_fill="black")
        cx += f.getlength(ch)

    # Level
    lvl = f"Lvl.{level}"
    bbox = draw.textbbox((0, 0), lvl, font=font_lvl)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        (final.width - tw - 30, TARGET_HEIGHT - th - 40),
        lvl,
        font=font_lvl,
        fill="white",
        stroke_width=STROKE_LEVEL,
        stroke_fill="black",
    )

    out = io.BytesIO()
    # Low compression level greatly reduces CPU time while preserving PNG output.
    final.save(out, format="PNG", compress_level=1, optimize=False)
    return out.getvalue()


async def fetch_player(uid: str) -> Dict[str, Any]:
    cached = cache_get(player_cache, uid)
    if cached is not None:
        return cached

    # EASY UPDATE: change INFO_API_URL and INFO_API_KEY above.
    # If your new API does not use a key, remove the key parameter here.
    params = {"uid": uid}
    if INFO_API_KEY and not INFO_API_KEY.startswith("YOUR_"):
        params["key"] = INFO_API_KEY

    global uncommon_client
    try:
        r = await uncommon_client.get(INFO_API_URL, params=params)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as exc:
        raise HTTPException(502, "Player information API is unavailable") from exc

    if not isinstance(data, dict):
        raise HTTPException(502, "Invalid player API response")

    cache_put(player_cache, uid, data, PLAYER_CACHE_TTL, MAX_PLAYER_CACHE)
    return data


async def generate_banner(uid: str) -> bytes:
    cached = cache_get(banner_cache, uid)
    if cached is not None:
        return cached

    data = await fetch_player(uid)

    # Supports the current response shape:
    # { basicInfo: { nickname, level, headPic, bannerId }, clanBasicInfo: { clanName } }
    basic = data.get("basicInfo") or {}
    clan = data.get("clanBasicInfo") or {}

    if not basic:
        raise HTTPException(404, "Player not found")

    player = {
        "name": basic.get("nickname", "Unknown"),
        "level": basic.get("level", "0"),
        "guild": clan.get("clanName", ""),
    }

    avatar_id = basic.get("headPic")
    banner_id = basic.get("bannerId")

    # Only two network calls; pin request was removed because it was unused.
    avatar_bytes, banner_bytes = await asyncio.gather(
        fetch_asset(avatar_id),
        fetch_asset(banner_id),
    )

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        process_pool,
        process_banner,
        player,
        avatar_bytes,
        banner_bytes,
    )

    cache_put(banner_cache, uid, result, BANNER_CACHE_TTL, MAX_BANNER_CACHE)
    return result


async def generate_deduplicated(uid: str) -> bytes:
    # If 20 users request the same UID at once, generate it only once.
    async with inflight_lock:
        task = inflight.get(uid)
        if task is None:
            task = asyncio.create_task(generate_banner(uid))
            inflight[uid] = task

    try:
        return await task
    finally:
        async with inflight_lock:
            if inflight.get(uid) is task:
                inflight.pop(uid, None)


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse("""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fast Banner API</title>
<style>
body{margin:0;background:#080808;color:#eee;font-family:system-ui;display:grid;place-items:center;min-height:100vh}
main{width:min(700px,90%);padding:30px;border:1px solid #333;border-radius:24px;text-align:center}
input,button{padding:14px 18px;border-radius:12px;border:1px solid #444;background:#111;color:#fff}
button{cursor:pointer} img{max-width:100%;margin-top:20px;border-radius:12px}
</style></head><body><main>
<h1>Fast Banner API</h1>
<p>Enter a UID to test.</p>
<input id="uid" value="11111111" inputmode="numeric">
<button onclick="go()">Generate</button>
<div id="out"></div>
<script>
function go(){
 const uid=document.getElementById('uid').value.trim();
 if(!/^\\d+$/.test(uid)) return;
 const img=new Image();
 img.loading='eager';
 img.src='/uc-banner?uid='+encodeURIComponent(uid);
 img.onerror=()=>document.getElementById('out').textContent='Banner generation failed';
 document.getElementById('out').replaceChildren(img);
}
window.addEventListener('load',go);
</script></main></body></html>""")


@app.get("/uc-banner")
async def get_banner(uid: str):
    uid = uid.strip()
    # Free Fire UIDs are numeric; this also prevents malformed URLs.
    if not uid.isdigit() or len(uid) < 5 or len(uid) > 20:
        raise HTTPException(400, "Invalid UID")

    image = await generate_deduplicated(uid)

    return Response(
        content=image,
        media_type="image/png",
        headers={
            # Browser/CDN can reuse the generated image.
            "Cache-Control": "public, max-age=300, stale-while-revalidate=60",
            "X-Content-Type-Options": "nosniff",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
