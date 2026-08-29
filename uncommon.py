# Made by Uncommon.exe | Optimized & Fixed by RAMSAGAR
# Fast & Reliable Free Fire Banner API - India Compatible
# OB54 LEAK - FIXED FOR INDIA INFO API FORMAT

import io
import os
import asyncio
import base64
import time
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from cachetools import TTLCache

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

# Speed vs Quality: BICUBIC is ~3x faster than LANCZOS with minimal quality loss
RESIZE_METHOD = Image.BICUBIC
TARGET_HEIGHT = 400
# ======================================================

# ================= GLOBAL CACHES =================
# Cache final banners for 5 minutes (player data doesnt change that fast)
BANNER_CACHE = TTLCache(maxsize=500, ttl=300)

# Cache CDN images for 30 minutes (game assets are static)
IMAGE_CACHE = TTLCache(maxsize=200, ttl=1800)

# Preloaded fonts (loaded once at startup)
FONT_CACHE = {}

# ================= API CONFIG =================
# UPDATE THIS URL TO YOUR INDIA-ONLY API
INFO_API_URL = "https://ramsagar.vercel.app/uc-info"

BASE64_CDN = "aHR0cHM6Ly9jZG4uanNkZWxpdnIubmV0L2doL1NoYWhHQ3JlYXRvci9pY29uQG1haW4vUE5H"
CDN_URL = base64.b64decode(BASE64_CDN).decode("utf-8")

FONT_FILE = "arial_unicode_bold.otf"
FONT_CHEROKEE = "NotoSansCherokee.ttf"

# ================= HTTP CLIENT =================
uncommon_client = httpx.AsyncClient(
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=8.0,
    follow_redirects=True,
    limits=httpx.Limits(max_keepalive_connections=20, max_connections=50)
)

# CPU-bound image processing pool
import multiprocessing
WORKERS = min(4, multiprocessing.cpu_count() * 2)
uncommon_process_pool = ThreadPoolExecutor(max_workers=WORKERS)


# ================= LIFESPAN =================
@asynccontextmanager
async def uncommon_lifespan(app: FastAPI):
    """Startup: preload fonts. Shutdown: cleanup resources."""
    _preload_fonts()
    yield
    await uncommon_client.aclose()
    uncommon_process_pool.shutdown(wait=False)


app = FastAPI(lifespan=uncommon_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================= FONT PRELOADING =================
def _preload_fonts():
    """Load all fonts at startup to avoid disk I/O on every request."""
    sizes = [50, 95, 125]
    fonts_to_load = [
        (FONT_FILE, "arial"),
        (FONT_CHEROKEE, "cherokee")
    ]

    for font_file, font_key in fonts_to_load:
        for size in sizes:
            try:
                font_path = os.path.join(os.path.dirname(__file__), font_file)
                if os.path.exists(font_path):
                    FONT_CACHE[(font_key, size)] = ImageFont.truetype(font_path, size)
                else:
                    FONT_CACHE[(font_key, size)] = ImageFont.load_default()
            except Exception:
                FONT_CACHE[(font_key, size)] = ImageFont.load_default()

    print(f"✅ Preloaded {len(FONT_CACHE)} font variants")


def uncommon_load_unicode_font(size: int, font_file: str = FONT_FILE) -> ImageFont.FreeTypeFont:
    """Get preloaded font from cache (zero disk I/O)."""
    key = "cherokee" if FONT_CHEROKEE in font_file else "arial"
    return FONT_CACHE.get((key, size), ImageFont.load_default())


# ================= IMAGE FETCHING =================
async def uncommon_fetch_image_bytes(item_id: Optional[str]) -> Optional[bytes]:
    """Fetch image from CDN with memory caching."""
    if not item_id or str(item_id) in ("0", "None", ""):
        return None

    cache_key = str(item_id)
    if cache_key in IMAGE_CACHE:
        return IMAGE_CACHE[cache_key]

    try:
        resp = await uncommon_client.get(f"{CDN_URL}/{item_id}.png")
        if resp.status_code == 200:
            IMAGE_CACHE[cache_key] = resp.content
            return resp.content
    except Exception:
        pass
    return None


def uncommon_bytes_to_image(img_bytes: Optional[bytes]) -> Image.Image:
    """Convert bytes to PIL Image."""
    if img_bytes:
        try:
            return Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        except Exception:
            pass
    return Image.new("RGBA", (100, 100), (0, 0, 0, 0))


# ================= BANNER PROCESSING =================
def uncommon_process_banner_image(
    data: Dict[str, Any],
    avatar_bytes: Optional[bytes],
    banner_bytes: Optional[bytes],
    pin_bytes: Optional[bytes]
) -> io.BytesIO:
    """Generate banner image - optimized for speed."""
    avatar_img = uncommon_bytes_to_image(avatar_bytes)
    banner_img = uncommon_bytes_to_image(banner_bytes)
    pin_img = uncommon_bytes_to_image(pin_bytes)

    level = str(data.get("level") or "0")
    name = str(data.get("name") or "Unknown")
    guild = str(data.get("guild") or "")

    # ---- Avatar processing ----
    zoom_size = int(TARGET_HEIGHT * AVATAR_ZOOM)
    avatar_img = avatar_img.resize((zoom_size, zoom_size), RESIZE_METHOD)

    center = zoom_size // 2
    half = TARGET_HEIGHT // 2
    avatar_img = avatar_img.crop((
        center - half - AVATAR_SHIFT_X,
        center - half - AVATAR_SHIFT_Y,
        center + half - AVATAR_SHIFT_X,
        center + half - AVATAR_SHIFT_Y
    ))

    if AVATAR_SHARPNESS_FACTOR != 1.0:
        enhancer = ImageEnhance.Sharpness(avatar_img)
        avatar_img = enhancer.enhance(AVATAR_SHARPNESS_FACTOR)

    # ---- Banner processing ----
    if BANNER_COLOR_FACTOR != 1.0:
        enhancer = ImageEnhance.Color(banner_img)
        banner_img = enhancer.enhance(BANNER_COLOR_FACTOR)

    if BANNER_CONTRAST_FACTOR != 1.0:
        enhancer = ImageEnhance.Contrast(banner_img)
        banner_img = enhancer.enhance(BANNER_CONTRAST_FACTOR)

    if BANNER_BRIGHTNESS_FACTOR != 1.0:
        enhancer = ImageEnhance.Brightness(banner_img)
        banner_img = enhancer.enhance(BANNER_BRIGHTNESS_FACTOR)

    banner_img = banner_img.rotate(3, expand=True)
    bw, bh = banner_img.size
    banner_img = banner_img.crop((
        bw * BANNER_START_X,
        bh * BANNER_START_Y,
        bw * BANNER_END_X,
        bh * BANNER_END_Y
    ))

    bw, bh = banner_img.size
    banner_img = banner_img.resize(
        (int(TARGET_HEIGHT * (bw / bh) * 2), TARGET_HEIGHT),
        RESIZE_METHOD
    )

    if BANNER_SHARPNESS_FACTOR != 1.0:
        enhancer = ImageEnhance.Sharpness(banner_img)
        banner_img = enhancer.enhance(BANNER_SHARPNESS_FACTOR)

    # ---- Composite ----
    final = Image.new("RGBA", (avatar_img.width + banner_img.width, TARGET_HEIGHT))
    final.paste(avatar_img, (0, 0))
    final.paste(banner_img, (avatar_img.width, 0))

    draw = ImageDraw.Draw(final)

    font_big = uncommon_load_unicode_font(125)
    font_big_c = uncommon_load_unicode_font(125, FONT_CHEROKEE)
    font_small = uncommon_load_unicode_font(95)
    font_small_c = uncommon_load_unicode_font(95, FONT_CHEROKEE)
    font_lvl = uncommon_load_unicode_font(50)

    def is_cherokee(ch: str) -> bool:
        return 0x13A0 <= ord(ch) <= 0x13FF or 0xAB70 <= ord(ch) <= 0xABBF

    # ---- Draw name ----
    x_name = avatar_img.width + 65
    y_name = 40
    cx = x_name
    for ch in name:
        f = font_big_c if is_cherokee(ch) else font_big
        draw.text(
            (cx, y_name),
            ch,
            font=f,
            fill="white",
            stroke_width=STROKE_NAME,
            stroke_fill="black"
        )
        cx += f.getlength(ch)

    # ---- Draw guild ----
    x_guild = avatar_img.width + 65
    y_guild = 220
    cx = x_guild
    for ch in guild:
        f = font_small_c if is_cherokee(ch) else font_small
        draw.text(
            (cx, y_guild),
            ch,
            font=f,
            fill="white",
            stroke_width=STROKE_GUILD,
            stroke_fill="black"
        )
        cx += f.getlength(ch)

    # ---- Pin ----
    if pin_img and pin_img.size != (100, 100):
        pin_img = pin_img.resize((130, 130), RESIZE_METHOD)
        final.paste(pin_img, (0, TARGET_HEIGHT - 130), pin_img)

    # ---- Level ----
    lvl = f"Lvl.{level}"
    bbox = draw.textbbox((0, 0), lvl, font=font_lvl)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    text_x = final.width - tw - 30
    text_y = TARGET_HEIGHT - th - 40

    draw.text(
        (text_x, text_y),
        lvl,
        font=font_lvl,
        fill="white",
        stroke_width=STROKE_LEVEL,
        stroke_fill="black"
    )

    out = io.BytesIO()
    final.save(out, "PNG", optimize=True, compress_level=6)
    out.seek(0)
    return out


# ================= ROUTES =================
@app.get("/", response_class=HTMLResponse)
async def uncommon_home() -> HTMLResponse:
    """Serve the landing page with UI for generating banners."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>RAMSAGAR [HACKER] API - Fast Banner</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                font-family: 'Segoe UI', system-ui, sans-serif;
                background: #000;
                padding: 20px;
            }
            .glass {
                max-width: 820px;
                width: 100%;
                padding: 45px 40px;
                background: rgba(8, 8, 8, 0.75);
                backdrop-filter: blur(20px);
                border-radius: 40px;
                border: 1px solid rgba(210, 180, 80, 0.25);
                box-shadow: 0 40px 100px rgba(0,0,0,0.9), inset 0 1px 0 rgba(255,215,0,0.10);
                text-align: center;
                animation: floatIn 0.9s ease-out;
            }
            @keyframes floatIn {
                0% { opacity: 0; transform: scale(0.96) translateY(30px); }
                100% { opacity: 1; transform: scale(1) translateY(0); }
            }
            .title {
                font-size: 3.2rem;
                font-weight: 800;
                background: linear-gradient(135deg, #f5e6b0, #d4af37, #f5e6b0);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-bottom: 4px;
            }
            .sub-brand {
                font-size: 0.9rem;
                font-weight: 300;
                color: rgba(210, 180, 80, 0.4);
                letter-spacing: 6px;
                text-transform: uppercase;
                margin-bottom: 28px;
                border-bottom: 1px solid rgba(210, 180, 80, 0.08);
                padding-bottom: 14px;
                display: inline-block;
            }
            .form-group {
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                gap: 12px;
                margin: 10px 0 20px;
            }
            .form-group input {
                flex: 1 1 240px;
                padding: 14px 22px;
                border-radius: 60px;
                border: 1px solid rgba(210, 180, 80, 0.25);
                background: rgba(0, 0, 0, 0.5);
                color: #e8e0d0;
                font-size: 1rem;
                font-family: monospace;
                outline: none;
                transition: border-color 0.3s, box-shadow 0.3s;
            }
            .form-group input:focus {
                border-color: #d4af37;
                box-shadow: 0 0 30px rgba(212, 175, 55, 0.1);
            }
            .form-group button {
                padding: 14px 34px;
                border-radius: 60px;
                border: 1px solid #d4af37;
                background: rgba(212, 175, 55, 0.10);
                color: #f5e6b0;
                font-size: 1rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                letter-spacing: 0.5px;
            }
            .form-group button:hover {
                background: rgba(212, 175, 55, 0.25);
                transform: scale(1.02);
            }
            .banner-preview {
                margin: 20px 0 10px;
                padding: 10px;
                background: rgba(0, 0, 0, 0.3);
                border-radius: 20px;
                border: 1px solid rgba(210, 180, 80, 0.10);
                min-height: 120px;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            .banner-preview img {
                max-width: 100%;
                border-radius: 12px;
                box-shadow: 0 8px 30px rgba(0, 0, 0, 0.6);
            }
            .banner-preview .placeholder {
                color: rgba(200, 190, 170, 0.3);
                font-size: 1.1rem;
            }
            .endpoint-box {
                margin: 12px 0 8px;
                padding: 12px 20px;
                background: rgba(0, 0, 0, 0.4);
                border-radius: 60px;
                border: 1px solid rgba(210, 180, 80, 0.12);
                display: inline-block;
            }
            .endpoint-box code {
                font-family: monospace;
                color: #d4c8b0;
                font-size: 0.95rem;
            }
            .endpoint-box code span { color: #f5d06a; }
            .divider {
                border: 0;
                height: 1px;
                background: linear-gradient(90deg, transparent, rgba(210, 180, 80, 0.25), transparent);
                margin: 20px 0;
            }
            .credits {
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                gap: 12px 30px;
                font-size: 1.05rem;
                color: rgba(200, 190, 175, 0.6);
            }
            .credits a {
                color: #d4af37;
                text-decoration: none;
                font-weight: 500;
                transition: all 0.3s ease;
            }
            .credits a:hover {
                color: #f5e6b0;
                text-shadow: 0 0 30px rgba(212, 175, 55, 0.3);
            }
            .cache-info {
                font-size: 0.75rem;
                color: rgba(210, 180, 80, 0.3);
                margin-top: 8px;
            }
            .error-box {
                color: #ff6b6b;
                font-size: 0.9rem;
                margin-top: 10px;
                padding: 8px;
                background: rgba(255,0,0,0.05);
                border-radius: 10px;
            }
            @media (max-width: 600px) {
                .glass { padding: 25px 18px; }
                .title { font-size: 2.2rem; }
                .form-group input { flex: 1 1 100%; }
                .form-group button { width: 100%; }
            }
        </style>
    </head>
    <body>
        <div class="glass">
            <div class="title">RAMSAGAR [HACKER] API</div>
            <div class="sub-brand">⚡ Fast Free Fire Banner Generator ⚡</div>

            <div class="form-group">
                <input type="text" id="uidInput" placeholder="Enter UID (e.g. 11111111)" value="11111111">
                <button id="fetchBtn">✨ Generate</button>
            </div>

            <div class="banner-preview" id="preview">
                <span class="placeholder">Enter a UID and click Generate</span>
            </div>
            <div class="error-box" id="errorBox" style="display:none"></div>

            <div class="endpoint-box">
                <code>API Endpoint <span>/uc-banner?uid=<span id="endpointUid">11111111</span></span></code>
            </div>
            <div class="cache-info">⚡ Cached responses for 5 min | Images cached for 30 min</div>

            <hr class="divider">

            <div class="credits">
                <span>⚜️ Made by <a href="https://t.me/RAMSAGAR_OFC" target="_blank">©️RAMSAGAR</a></span>
                <span>📢 <a href="https://whatsapp.com/channel/0029VaEIdBk4yltWBFi0E711" target="_blank">WHATSAPP</a></span>
            </div>
        </div>

        <script>
            const uidInput = document.getElementById('uidInput');
            const fetchBtn = document.getElementById('fetchBtn');
            const preview = document.getElementById('preview');
            const errorBox = document.getElementById('errorBox');
            const endpointUid = document.getElementById('endpointUid');

            function updateEndpoint(uid) {
                endpointUid.textContent = uid || '11111111';
            }

            uidInput.addEventListener('input', (e) => updateEndpoint(e.target.value));

            fetchBtn.addEventListener('click', async () => {
                const uid = uidInput.value.trim();
                if (!uid) return;

                preview.innerHTML = '<span class="placeholder">Generating...</span>';
                errorBox.style.display = 'none';
                fetchBtn.disabled = true;

                const t0 = performance.now();
                try {
                    const resp = await fetch(`/uc-banner?uid=${encodeURIComponent(uid)}`);
                    if (!resp.ok) {
                        const err = await resp.json();
                        throw new Error(err.detail || err.error || 'Failed: ' + resp.status);
                    }
                    const blob = await resp.blob();
                    const url = URL.createObjectURL(blob);
                    preview.innerHTML = `<img src="${url}" alt="Banner">`;
                    const ms = Math.round(performance.now() - t0);
                    preview.innerHTML += `<div class="cache-info">Generated in ${ms}ms</div>`;
                } catch (err) {
                    preview.innerHTML = '<span class="placeholder">Failed to generate</span>';
                    errorBox.textContent = err.message;
                    errorBox.style.display = 'block';
                } finally {
                    fetchBtn.disabled = false;
                }
            });

            uidInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') fetchBtn.click();
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
    FIXED: Now correctly reads India Info API response format.
    """
    # Check banner cache first
    cache_key = str(uid)
    if cache_key in BANNER_CACHE:
        return Response(BANNER_CACHE[cache_key], media_type="image/png")

    # Fetch player info from India API
    url = f"{INFO_API_URL}?uid={uid}&key=RAM-SAGAR"
    try:
        resp = await uncommon_client.get(url)
        if resp.status_code != 200:
            raise HTTPException(502, f"Info API returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch player info: {str(e)}")

    data = resp.json()

    # DEBUG: Log the response structure for troubleshooting
    print(f"DEBUG: Info API response keys: {list(data.keys())}")

    # FIXED: India Info API returns protobuf JSON with camelCase field names
    # Structure: { "accountInfoBasic": {...}, "clanInfo": {...}, ... }

    # Try to find player data in the response
    basic_info = data.get("accountInfoBasic") or data.get("account_info_basic") or data.get("basicInfo") or {}
    clan_info = data.get("clanInfo") or data.get("clan_info") or data.get("clanBasicInfo") or {}

    if not basic_info:
        raise HTTPException(404, f"Invalid response: missing player data. Keys found: {list(data.keys())}")

    # Extract fields (protobuf JSON uses camelCase)
    name = basic_info.get("nickname") or basic_info.get("nickName") or "Unknown"
    level = basic_info.get("level") or "0"

    # Clan name can be in clanInfo or directly in accountInfoBasic
    guild = (
        clan_info.get("clanName") or 
        clan_info.get("clan_name") or 
        basic_info.get("clanName") or 
        basic_info.get("clan_name") or 
        ""
    )

    avatar_id = basic_info.get("headPic") or basic_info.get("head_pic")
    banner_id = basic_info.get("bannerId") or basic_info.get("banner_id")
    pin_id = basic_info.get("pinId") or basic_info.get("pin_id")

    print(f"DEBUG: name={name}, level={level}, guild={guild}, avatar={avatar_id}, banner={banner_id}")

    # Fetch images in parallel
    avatar_bytes, banner_bytes, pin_bytes = await asyncio.gather(
        uncommon_fetch_image_bytes(avatar_id),
        uncommon_fetch_image_bytes(banner_id),
        uncommon_fetch_image_bytes(pin_id),
    )

    # Process image in thread pool
    img_buffer = await asyncio.get_event_loop().run_in_executor(
        uncommon_process_pool,
        uncommon_process_banner_image,
        {"level": level, "name": name, "guild": guild},
        avatar_bytes,
        banner_bytes,
        pin_bytes,
    )

    img_data = img_buffer.getvalue()

    # Cache the final banner
    BANNER_CACHE[cache_key] = img_data

    return Response(img_data, media_type="image/png")


@app.get("/stats")
async def uncommon_stats():
    """Return API performance stats."""
    return {
        "cached_banners": len(BANNER_CACHE),
        "cached_images": len(IMAGE_CACHE),
        "font_variants_loaded": len(FONT_CACHE),
        "workers": WORKERS,
        "resize_method": "BICUBIC (fast)",
        "info_api_url": INFO_API_URL,
    }


# ================= MAIN ENTRY POINT =================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5000)
