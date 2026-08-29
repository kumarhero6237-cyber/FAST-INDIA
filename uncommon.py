# Free Fire Banner API
# Original by Uncommon.exe — optimized for speed (font caching, asset caching,
# batched text rendering, tuned HTTP pool, faster PNG encode).

import io
import os
import time
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# ================= ADJUSTMENT SETTINGS =================
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
# ======================================================

# ================= CONSTANTS =================
# Configurable via environment variable so the info-API URL can be swapped
# without touching code. Falls back to the previous default if unset.
INFO_API_URL = os.environ.get("INFO_API_URL", "https://ramsagar.vercel.app/uc-info")
INFO_API_KEY = os.environ.get("INFO_API_KEY", "RAM-SAGAR")

CDN_URL = os.environ.get("CDN_URL", "https://cdn.jsdelivr.net/gh/ShahGCreator/icon@main/PNG")

FONT_FILE = "arial_unicode_bold.otf"
FONT_CHEROKEE = "NotoSansCherokee.ttf"

# How long fetched CDN assets (avatar/banner PNGs) stay cached in memory.
# Avatar/banner cosmetic assets rarely change, so repeated requests for the
# same item_id are served instantly instead of re-downloaded.
ASSET_CACHE_TTL = 3600  # seconds
ASSET_CACHE_MAX_ITEMS = 500

# Tuned connection pool: reuse keep-alive connections instead of
# renegotiating TLS/TCP per request, which is a major latency cost on
# serverless cold/warm paths when hitting the same CDN/info-API host.
_limits = httpx.Limits(max_connections=100, max_keepalive_connections=50)
uncommon_client = httpx.AsyncClient(
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=httpx.Timeout(8.0, connect=4.0),
    limits=_limits,
    follow_redirects=True,
)

# Sized to available CPUs (min 4) instead of a hardcoded 4 — image
# compositing is CPU bound, so this scales with the host.
_workers = max(4, (os.cpu_count() or 4))
uncommon_process_pool = ThreadPoolExecutor(max_workers=_workers)


@asynccontextmanager
async def uncommon_lifespan(app: FastAPI):
    yield
    await uncommon_client.aclose()
    uncommon_process_pool.shutdown()


app = FastAPI(lifespan=uncommon_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= FONT CACHE =================
# Previously every request re-read + re-parsed 5 font objects from disk.
# That disk I/O + TrueType parsing was one of the biggest per-request costs.
# Fonts never change at runtime, so load each (file, size) combo exactly
# once and reuse it for the life of the process.
_font_cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}


def uncommon_load_unicode_font(size: int, font_file: str = FONT_FILE) -> ImageFont.FreeTypeFont:
    key = (font_file, size)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    try:
        font_path = os.path.join(os.path.dirname(__file__), font_file)
        if os.path.exists(font_path):
            font = ImageFont.truetype(font_path, size)
        else:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    _font_cache[key] = font
    return font


# Warm the font cache once at import time (process start), not on the
# first request, so the very first banner isn't the slow one either.
_FONT_BIG = uncommon_load_unicode_font(125, FONT_FILE)
_FONT_BIG_C = uncommon_load_unicode_font(125, FONT_CHEROKEE)
_FONT_SMALL = uncommon_load_unicode_font(95, FONT_FILE)
_FONT_SMALL_C = uncommon_load_unicode_font(95, FONT_CHEROKEE)
_FONT_LVL = uncommon_load_unicode_font(50, FONT_FILE)


# ================= ASSET (CDN IMAGE) CACHE =================
# item_id -> (bytes, expiry_timestamp)
_asset_cache: Dict[str, Tuple[Optional[bytes], float]] = {}


def _asset_cache_get(item_id: str) -> Optional[bytes]:
    entry = _asset_cache.get(item_id)
    if entry is None:
        return None
    data, expiry = entry
    if expiry < time.monotonic():
        _asset_cache.pop(item_id, None)
        return None
    return data


def _asset_cache_set(item_id: str, data: Optional[bytes]) -> None:
    if len(_asset_cache) >= ASSET_CACHE_MAX_ITEMS:
        # Cheap eviction: drop an arbitrary (oldest-inserted-ish) entry
        # rather than paying for a full LRU structure.
        _asset_cache.pop(next(iter(_asset_cache)), None)
    _asset_cache[item_id] = (data, time.monotonic() + ASSET_CACHE_TTL)


async def uncommon_fetch_image_bytes(item_id: Optional[str]) -> Optional[bytes]:
    """
    Fetch image data from CDN for a given item ID, using an in-memory
    cache so repeat requests for the same avatar/banner asset skip the
    network round trip entirely.
    """
    if not item_id or str(item_id) in ("0", "None"):
        return None
    item_id = str(item_id)

    cached = _asset_cache_get(item_id)
    if cached is not None:
        return cached

    try:
        resp = await uncommon_client.get(f"{CDN_URL}/{item_id}.png")
        if resp.status_code == 200:
            _asset_cache_set(item_id, resp.content)
            return resp.content
    except Exception:
        pass
    return None


def uncommon_bytes_to_image(img_bytes: Optional[bytes]) -> Image.Image:
    if img_bytes:
        try:
            return Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        except Exception:
            pass
    return Image.new("RGBA", (100, 100), (0, 0, 0, 0))


def _draw_text_runs(draw: ImageDraw.ImageDraw, x: int, y: int, text: str,
                     font_default: ImageFont.FreeTypeFont, font_cherokee: ImageFont.FreeTypeFont,
                     stroke_width: int) -> None:
    """
    Draw a string that may mix two fonts (default + Cherokee), batching
    consecutive characters that use the same font into a single draw call
    instead of one draw.text() call per character. Big win for long
    names/guild tags since draw.text() has fixed per-call overhead.
    """
    def is_cherokee(ch: str) -> bool:
        return 0x13A0 <= ord(ch) <= 0x13FF or 0xAB70 <= ord(ch) <= 0xABBF

    cx = x
    run = ""
    run_font = None
    for ch in text:
        f = font_cherokee if is_cherokee(ch) else font_default
        if run_font is None:
            run_font = f
        if f is not run_font:
            draw.text((cx, y), run, font=run_font, fill="white",
                       stroke_width=stroke_width, stroke_fill="black")
            cx += run_font.getlength(run)
            run = ch
            run_font = f
        else:
            run += ch
    if run:
        draw.text((cx, y), run, font=run_font, fill="white",
                   stroke_width=stroke_width, stroke_fill="black")


def uncommon_process_banner_image(
    data: Dict[str, Any],
    avatar_bytes: Optional[bytes],
    banner_bytes: Optional[bytes],
    pin_bytes: Optional[bytes],
) -> io.BytesIO:
    avatar_img = uncommon_bytes_to_image(avatar_bytes)
    banner_img = uncommon_bytes_to_image(banner_bytes)
    pin_img = uncommon_bytes_to_image(pin_bytes) if pin_bytes else None

    level = str(data.get("level") or "0")
    name = str(data.get("name") or "Unknown")
    guild = str(data.get("guild") or "")

    TARGET_HEIGHT = 400

    # ---- Avatar processing ----
    zoom_size = int(TARGET_HEIGHT * AVATAR_ZOOM)
    avatar_img = avatar_img.resize((zoom_size, zoom_size), Image.LANCZOS)

    center = zoom_size // 2
    half = TARGET_HEIGHT // 2
    avatar_img = avatar_img.crop((
        center - half - AVATAR_SHIFT_X,
        center - half - AVATAR_SHIFT_Y,
        center + half - AVATAR_SHIFT_X,
        center + half - AVATAR_SHIFT_Y,
    ))
    avatar_img = ImageEnhance.Sharpness(avatar_img).enhance(AVATAR_SHARPNESS_FACTOR)

    # ---- Banner processing ----
    banner_img = ImageEnhance.Color(banner_img).enhance(BANNER_COLOR_FACTOR)
    banner_img = ImageEnhance.Contrast(banner_img).enhance(BANNER_CONTRAST_FACTOR)
    banner_img = ImageEnhance.Brightness(banner_img).enhance(BANNER_BRIGHTNESS_FACTOR)

    banner_img = banner_img.rotate(3, expand=True)
    bw, bh = banner_img.size
    banner_img = banner_img.crop((
        bw * BANNER_START_X,
        bh * BANNER_START_Y,
        bw * BANNER_END_X,
        bh * BANNER_END_Y,
    ))

    bw, bh = banner_img.size
    banner_img = banner_img.resize(
        (int(TARGET_HEIGHT * (bw / bh) * 2), TARGET_HEIGHT),
        Image.LANCZOS,
    )
    banner_img = ImageEnhance.Sharpness(banner_img).enhance(BANNER_SHARPNESS_FACTOR)

    # ---- Composite ----
    final = Image.new("RGBA", (avatar_img.width + banner_img.width, TARGET_HEIGHT))
    final.paste(avatar_img, (0, 0))
    final.paste(banner_img, (avatar_img.width, 0))

    draw = ImageDraw.Draw(final)

    # ---- Draw name (batched per font-run instead of per character) ----
    _draw_text_runs(draw, avatar_img.width + 65, 40, name, _FONT_BIG, _FONT_BIG_C, STROKE_NAME)

    # ---- Draw guild ----
    _draw_text_runs(draw, avatar_img.width + 65, 220, guild, _FONT_SMALL, _FONT_SMALL_C, STROKE_GUILD)

    # ---- Pin (if available) ----
    if pin_img is not None and pin_img.size != (100, 100):
        pin_img = pin_img.resize((130, 130))
        final.paste(pin_img, (0, TARGET_HEIGHT - 130), pin_img)

    # ---- Level label ----
    lvl = f"Lvl.{level}"
    bbox = draw.textbbox((0, 0), lvl, font=_FONT_LVL)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    text_x = final.width - tw - 30
    text_y = TARGET_HEIGHT - th - 40

    draw.text(
        (text_x, text_y),
        lvl,
        font=_FONT_LVL,
        fill="white",
        stroke_width=STROKE_LEVEL,
        stroke_fill="black",
    )

    out = io.BytesIO()
    # compress_level=1 trades a slightly larger PNG for a much faster
    # encode; at compress_level 6 (PIL default) PNG encoding of a ~700px
    # RGBA image is one of the more expensive steps in the whole request.
    final.save(out, "PNG", compress_level=1)
    out.seek(0)
    return out


# ================= ROUTES =================
@app.get("/", response_class=HTMLResponse)
async def uncommon_home() -> HTMLResponse:
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Free Fire Banner API</title>
        <style>
            body { font-family: system-ui, sans-serif; background:#0b0b0b; color:#e8e0d0;
                   display:flex; justify-content:center; align-items:center; min-height:100vh; margin:0; padding:20px; }
            .card { max-width:700px; width:100%; background:rgba(20,20,20,0.9); border-radius:20px;
                    padding:30px; border:1px solid rgba(212,175,55,0.25); text-align:center; }
            h1 { color:#d4af37; margin-bottom:20px; }
            input { padding:10px 16px; border-radius:30px; border:1px solid #444; background:#111; color:#eee; width:220px; }
            button { padding:10px 20px; border-radius:30px; border:1px solid #d4af37; background:rgba(212,175,55,0.15);
                     color:#f5e6b0; cursor:pointer; margin-left:8px; }
            .preview { margin-top:20px; min-height:120px; display:flex; justify-content:center; align-items:center; }
            .preview img { max-width:100%; border-radius:10px; }
            code { color:#f5d06a; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Free Fire Banner API</h1>
            <div>
                <input type="text" id="uidInput" placeholder="Enter UID" value="11111111">
                <button id="fetchBtn">Generate</button>
            </div>
            <div class="preview" id="preview"><span>Enter a UID and click Generate</span></div>
            <p>Endpoint: <code>/uc-banner?uid=YOUR_UID</code></p>
        </div>
        <script>
            const uidInput = document.getElementById('uidInput');
            const fetchBtn = document.getElementById('fetchBtn');
            const preview = document.getElementById('preview');

            function showImage(uid) {
                const img = document.createElement('img');
                img.src = `/uc-banner?uid=${encodeURIComponent(uid)}`;
                img.onerror = () => { preview.innerHTML = '<span>Failed to load banner. Check UID.</span>'; };
                preview.innerHTML = '';
                preview.appendChild(img);
            }

            fetchBtn.addEventListener('click', () => {
                const uid = uidInput.value.trim();
                if (uid) showImage(uid);
            });

            window.addEventListener('load', () => {
                const uid = uidInput.value.trim();
                if (uid) showImage(uid);
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/uc-banner")
async def uncommon_get_banner(uid: str) -> Response:
    """
    Generate and return a banner image for the given Free Fire UID.
    """
    url = f"{INFO_API_URL}?uid={uid}&key={INFO_API_KEY}"
    try:
        resp = await uncommon_client.get(url)
        if resp.status_code != 200:
            raise HTTPException(502, f"Info API returned {resp.status_code}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch player info: {str(e)}")

    data = resp.json()

    if "basicInfo" not in data:
        raise HTTPException(404, "Invalid response: missing basicInfo")

    basic_info = data.get("basicInfo", {})
    clan_info = data.get("clanBasicInfo", {})

    name = basic_info.get("nickname", "Unknown")
    level = basic_info.get("level", "0")
    guild = clan_info.get("clanName", "")

    avatar_id = basic_info.get("headPic")
    banner_id = basic_info.get("bannerId")

    avatar_bytes, banner_bytes = await asyncio.gather(
        uncommon_fetch_image_bytes(avatar_id),
        uncommon_fetch_image_bytes(banner_id),
    )

    img_buffer = await asyncio.get_event_loop().run_in_executor(
        uncommon_process_pool,
        uncommon_process_banner_image,
        {"level": level, "name": name, "guild": guild},
        avatar_bytes,
        banner_bytes,
        None,
    )

    return Response(
        img_buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


# ================= MAIN ENTRY POINT =================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5000)
