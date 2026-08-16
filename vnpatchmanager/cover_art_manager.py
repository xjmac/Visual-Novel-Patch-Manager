import requests
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
try:
    import customtkinter as ctk
    from PIL import Image, ImageDraw
except ImportError:
    pass

class CoverArtManager:
    """Handles fetching, caching, and generating Steam game cover art banners."""

    CACHE_DIR = Path.home() / ".cache" / "vnpatchmanager" / "covers"
    STEAM_HEADER_URL = "https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg"
    MAX_CACHE_SIZE = 250

    def __init__(self, cache_dir: Path = None):
        self.cache_dir = cache_dir or self.CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._image_cache = {}
        self._fallback_cache = {}

    def get_cached_path(self, app_id: str) -> Path:
        return self.cache_dir / f"{app_id}.jpg"

    def download_cover(self, app_id: str) -> bool:
        """Attempts to download the Steam header banner to local cache with modern store asset fallback."""
        cache_path = self.get_cached_path(str(app_id))
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return True

        headers = {"User-Agent": "Mozilla/5.0 (Linux; SteamDeck; VNPM)"}

        # 1. Try legacy CDN URLs
        cdn_urls = [
            self.STEAM_HEADER_URL.format(appid=app_id),
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"
        ]
        for url in cdn_urls:
            try:
                resp = requests.get(url, headers=headers, timeout=4)
                if resp.status_code == 200 and len(resp.content) > 0:
                    with open(cache_path, "wb") as f:
                        f.write(resp.content)
                    self.invalidate_memory_cache(str(app_id))
                    return True
            except Exception as e:
                logger.warning(f"Failed downloading {url} for app {app_id}: {e}")

        # 2. Fallback to Steam Store API for modern store_item_assets hashed URLs
        try:
            api_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&filters=basic"
            resp = requests.get(api_url, headers=headers, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                app_data = data.get(str(app_id), {}).get("data", {})
                img_url = app_data.get("header_image") or app_data.get("capsule_image")
                if img_url:
                    img_resp = requests.get(img_url, headers=headers, timeout=4)
                    if img_resp.status_code == 200 and len(img_resp.content) > 0:
                        with open(cache_path, "wb") as f:
                            f.write(img_resp.content)
                        self.invalidate_memory_cache(str(app_id))
                        return True
        except Exception as e:
            logger.warning(f"Failed fallback download for app {app_id}: {e}")

        return False

    def invalidate_memory_cache(self, app_id: str = None):
        """Clears memory cache for a given app_id or all app_ids."""
        if app_id is None:
            self._image_cache.clear()
            self._fallback_cache.clear()
        else:
            for k in list(self._image_cache.keys()):
                if k[0] == str(app_id):
                    del self._image_cache[k]
            for k in list(self._fallback_cache.keys()):
                if k[0] == str(app_id):
                    del self._fallback_cache[k]

    def generate_fallback_image(self, title: str, size: tuple[int, int]) -> 'Image.Image':
        """Generates an aesthetic dark-gradient banner for games without cover art."""
        w, h = size
        w = max(w, 10)
        h = max(h, 10)
        img = Image.new("RGB", (w, h), color=(24, 28, 38))
        draw = ImageDraw.Draw(img)

        # Subtle diagonal gradient
        for y in range(h):
            ratio = y / max(h, 1)
            r = int(22 + ratio * 16)
            g = int(27 + ratio * 20)
            b = int(37 + ratio * 30)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        # Clean border outline
        draw.rectangle([0, 0, w - 1, h - 1], outline=(51, 65, 85), width=1)

        # Decorative central badge with initials
        initials = "".join([part[0] for part in title.split() if part][:4]).upper() or "VN"
        pill_w = min(w - 16, 120)
        pill_h = min(h - 16, 36)
        px1 = (w - pill_w) // 2
        py1 = (h - pill_h) // 2
        px2 = px1 + pill_w
        py2 = py1 + pill_h

        if pill_w > 10 and pill_h > 10:
            draw.rounded_rectangle([px1, py1, px2, py2], radius=6, fill=(15, 23, 42), outline=(71, 85, 105), width=1)
            draw.text((w // 2 - (len(initials) * 4), py1 + max(2, (pill_h - 14) // 2)), initials, fill=(226, 232, 240))
        return img

    def get_cover_image(self, app_id: str, title: str = "", size: tuple[int, int] = (270, 125)) -> 'ctk.CTkImage':
        """Retrieves a CTkImage for the given AppID, from disk cache or procedural fallback."""
        cache_key = (str(app_id), size)
        cache_path = self.get_cached_path(str(app_id))

        # If already cached in memory from disk
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        if cache_path.exists() and cache_path.stat().st_size > 0:
            try:
                pil_img = Image.open(cache_path).convert("RGB")
                pil_img = pil_img.resize(size, Image.Resampling.BICUBIC)
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
                if len(self._image_cache) >= self.MAX_CACHE_SIZE:
                    self._image_cache.pop(next(iter(self._image_cache)))
                self._image_cache[cache_key] = ctk_img
                return ctk_img
            except Exception as e:
                logger.warning(f"Failed to process cached image {cache_path}: {e}")

        # Fallback image with memory caching
        fallback_key = (str(app_id), title or "", size)
        if fallback_key in self._fallback_cache:
            return self._fallback_cache[fallback_key]

        pil_img = self.generate_fallback_image(title or str(app_id), size)
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
        if len(self._fallback_cache) >= self.MAX_CACHE_SIZE:
            self._fallback_cache.pop(next(iter(self._fallback_cache)))
        self._fallback_cache[fallback_key] = ctk_img
        return ctk_img
