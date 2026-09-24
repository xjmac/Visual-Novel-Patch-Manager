import requests
import logging
from pathlib import Path
from typing import Optional, Any
from PIL import Image, ImageDraw, ImageOps
from .utils import is_mocked

logger = logging.getLogger(__name__)

class CoverArtManager:
    """Handles fetching, caching, and generating Steam game cover art banners."""

    CACHE_DIR = Path.home() / ".cache" / "vnpatchmanager" / "covers"
    STEAM_CAPSULE_URL = "https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg"
    STEAM_HEADER_URL = "https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg"
    MAX_CACHE_SIZE = 250

    def __init__(
        self,
        cache_dir: Path = None,
        session: Optional[requests.Session] = None,
        steamgriddb_client: Optional[Any] = None,
    ):
        self.cache_dir = cache_dir or self.CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._image_cache = {}
        self._fallback_cache = {}
        self._session = session or requests.Session()
        self.steamgriddb_client = steamgriddb_client

    def _get(self, url: str, headers: Optional[dict] = None, timeout: int = 5):
        client = requests if is_mocked(requests.get) else self._session
        return client.get(url, headers=headers, timeout=timeout)

    def _post(self, url: str, json: Optional[dict] = None, headers: Optional[dict] = None, timeout: int = 5):
        client = requests if is_mocked(requests.post) else self._session
        return client.post(url, json=json, headers=headers, timeout=timeout)

    def download_image_bytes(self, url: str, timeout: int = 12) -> Optional[bytes]:
        """Downloads raw image bytes from URL using connection pool."""
        if not url:
            return None
        try:
            headers = {"User-Agent": "VNPM/2.0 (Linux; SteamDeck; github.com/user/VNPM)"}
            resp = self._get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200 and len(resp.content) > 0:
                return resp.content
        except Exception as e:
            logger.warning(f"Failed to download image from {url}: {e}")
        return None

    def download_and_set_specific_asset(
        self,
        app_id: str,
        asset_type: str,
        url: str,
        steamgriddb_client: Optional[Any] = None,
        steam_root: Optional[Path] = None,
        timeout: int = 12
    ) -> bool:
        """Downloads artwork from URL and saves as a specific grid asset."""
        image_bytes = None
        if steamgriddb_client and hasattr(steamgriddb_client, "download_image_bytes"):
            image_bytes = steamgriddb_client.download_image_bytes(url, timeout=timeout)
        if not image_bytes:
            image_bytes = self.download_image_bytes(url, timeout=timeout)

        if not image_bytes:
            return False

        return self.set_specific_grid_asset(
            app_id=str(app_id),
            asset_type=asset_type,
            image_bytes=image_bytes,
            steam_root=steam_root
        )

    def get_cached_path(self, app_id: str) -> Path:
        return self.cache_dir / f"{app_id}.jpg"

    def get_cached_hero_path(self, app_id: str) -> Path:
        return self.cache_dir / f"{app_id}_hero.jpg"

    def check_steam_grid(self, app_id: str, steam_root: Path = None, portrait_only: bool = False) -> bool:
        """Checks if cover artwork already exists in Steam userdata grid directories."""
        if not steam_root:
            from .steam_scanner import SteamScanner
            steam_root = SteamScanner.get_steam_root()

        if not steam_root:
            return False

        userdata_dir = steam_root / "userdata"
        if not userdata_dir.exists():
            return False

        cache_path = self.get_cached_path(str(app_id))
        patterns = (f"{app_id}p.jpg", f"{app_id}p.png") if portrait_only else (
            f"{app_id}p.jpg", f"{app_id}p.png", f"{app_id}.jpg", f"{app_id}.png", f"{app_id}_hero.jpg"
        )
        for udir in userdata_dir.iterdir():
            if udir.is_dir() and udir.name.isdigit():
                grid_dir = udir / "config" / "grid"
                if not grid_dir.exists():
                    continue

                for pattern in patterns:
                    cand = grid_dir / pattern
                    if cand.exists() and cand.stat().st_size > 0:
                        try:
                            import shutil
                            shutil.copy2(cand, cache_path)
                            self.invalidate_memory_cache(str(app_id))
                            return True
                        except Exception as e:
                            logger.warning(f"Error copying grid image {cand}: {e}")
        return False

    def check_steam_library_hero(self, app_id: str, steam_root: Path = None) -> bool:
        """Checks if landscape hero/header artwork already exists in Steam librarycache or userdata grid."""
        if not steam_root:
            from .steam_scanner import SteamScanner
            steam_root = SteamScanner.get_steam_root()

        if not steam_root:
            return False

        hero_cache_path = self.get_cached_hero_path(str(app_id))

        # 1. Search Steam librarycache folders
        app_cache_dirs = [
            steam_root / "appcache" / "librarycache",
        ]
        userdata_dir = steam_root / "userdata"
        if userdata_dir.exists():
            for udir in userdata_dir.iterdir():
                if udir.is_dir() and udir.name.isdigit():
                    app_cache_dirs.append(udir / "config" / "librarycache")

        for c_dir in app_cache_dirs:
            if not c_dir.exists():
                continue
            # Subdirectory check: {app_id}/library_hero.jpg, {app_id}/header.jpg, etc.
            app_sub = c_dir / str(app_id)
            if app_sub.is_dir():
                for name in ("library_hero.jpg", "header.jpg", "library_header.jpg"):
                    cand = app_sub / name
                    if cand.exists() and cand.stat().st_size > 0:
                        try:
                            import shutil
                            shutil.copy2(cand, hero_cache_path)
                            self.invalidate_memory_cache(str(app_id))
                            return True
                        except Exception as e:
                            logger.warning(f"Error copying librarycache hero {cand}: {e}")

            # Flat file check: {app_id}_library_hero.jpg, {app_id}_header.jpg, etc.
            for pat in (f"{app_id}_library_hero.jpg", f"{app_id}_header.jpg", f"{app_id}_library_header.jpg"):
                cand = c_dir / pat
                if cand.exists() and cand.stat().st_size > 0:
                    try:
                        import shutil
                        shutil.copy2(cand, hero_cache_path)
                        self.invalidate_memory_cache(str(app_id))
                        return True
                    except Exception as e:
                        logger.warning(f"Error copying librarycache flat hero {cand}: {e}")

        # 2. Search Steam userdata grid directories: {app_id}_hero.jpg, {app_id}.jpg (if landscape)
        if userdata_dir.exists():
            for udir in userdata_dir.iterdir():
                if udir.is_dir() and udir.name.isdigit():
                    grid_dir = udir / "config" / "grid"
                    if not grid_dir.exists():
                        continue
                    # Prefer explicit hero files first
                    for pat in (f"{app_id}_hero.jpg", f"{app_id}_hero.png"):
                        cand = grid_dir / pat
                        if cand.exists() and cand.stat().st_size > 0:
                            try:
                                import shutil
                                shutil.copy2(cand, hero_cache_path)
                                self.invalidate_memory_cache(str(app_id))
                                return True
                            except Exception as e:
                                logger.warning(f"Error copying grid hero {cand}: {e}")

                    # Wide header files in grid: {app_id}.jpg, {app_id}.png
                    for pat in (f"{app_id}.jpg", f"{app_id}.png", f"{app_id}_header.jpg"):
                        cand = grid_dir / pat
                        if cand.exists() and cand.stat().st_size > 0:
                            try:
                                with Image.open(cand) as im:
                                    w, h = im.size
                                    if w >= h:
                                        import shutil
                                        shutil.copy2(cand, hero_cache_path)
                                        self.invalidate_memory_cache(str(app_id))
                                        return True
                            except Exception:
                                pass

        return False

    def fetch_vndb_cover(self, vn_id: str = None, title: str = None) -> Optional[str]:
        """Queries VNDB Kana API for a Visual Novel's cover artwork URL."""
        if not vn_id and not title:
            return None

        url = "https://api.vndb.org/kana/vn"
        headers = {"User-Agent": "VNPM/2.0 (Linux; SteamDeck; github.com/user/VNPM)"}
        payload = {"fields": "id, title, image.url"}

        if vn_id:
            payload["filters"] = ["id", "=", vn_id]
        else:
            payload["filters"] = ["search", "=", title]

        try:
            resp = self._post(url, json=payload, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    img_info = results[0].get("image")
                    if img_info and isinstance(img_info, dict) and img_info.get("url"):
                        return img_info["url"]
        except Exception as e:
            logger.warning(f"Failed fetching VNDB cover for {vn_id or title}: {e}")
        return None

    def download_cover(
        self,
        app_id: str,
        game_data: Optional[dict] = None,
        steamgriddb_client: Optional[Any] = None,
    ) -> bool:
        """Attempts to download game cover artwork (prioritizing 2:3 portrait capsules) from Steam Grid, Steam CDN, or VNDB Kana API."""
        cache_path = self.get_cached_path(str(app_id))
        if cache_path.exists() and cache_path.stat().st_size > 0:
            is_legacy_wide = False
            try:
                with Image.open(cache_path) as im:
                    w, h = im.size
                    if w > h * 1.15:
                        is_legacy_wide = True
            except Exception:
                pass
            if not is_legacy_wide:
                return True

        # 1. Check local Steam userdata grid files (prioritizing portrait {app_id}p.jpg)
        if self.check_steam_grid(str(app_id), portrait_only=True):
            return True

        headers = {"User-Agent": "Mozilla/5.0 (Linux; SteamDeck; VNPM)"}

        # 2. Try Steam Library Capsule URLs (600x900 / 300x450 portrait)
        cdn_urls = [
            self.STEAM_CAPSULE_URL.format(appid=app_id),
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg",
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_600x900_2x.jpg",
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg",
        ]
        for url in cdn_urls:
            try:
                resp = self._get(url, headers=headers, timeout=4)
                if resp.status_code == 200 and len(resp.content) > 0:
                    with open(cache_path, "wb") as f:
                        f.write(resp.content)
                    self.invalidate_memory_cache(str(app_id))
                    return True
            except Exception as e:
                logger.warning(f"Failed downloading {url} for app {app_id}: {e}")

        # 3. Try SteamGridDB for high-res 600x900 capsule artwork
        sgdb = steamgriddb_client or self.steamgriddb_client
        if sgdb and hasattr(sgdb, "has_api_key") and sgdb.has_api_key():
            try:
                gid = sgdb.get_game_by_steam_appid(str(app_id))
                if not gid and game_data and game_data.get("name"):
                    results = sgdb.search_games(game_data["name"])
                    if results:
                        gid = results[0].get("id")
                if gid:
                    assets = sgdb.get_assets(gid, "capsule")
                    if assets and assets[0].get("url"):
                        sgdb_bytes = self.download_image_bytes(assets[0]["url"], timeout=8)
                        if sgdb_bytes and len(sgdb_bytes) > 0:
                            with open(cache_path, "wb") as f:
                                f.write(sgdb_bytes)
                            self.invalidate_memory_cache(str(app_id))
                            if game_data and game_data.get("is_non_steam"):
                                self.set_custom_artwork(str(app_id), cache_path)
                            return True
            except Exception as e:
                logger.debug(f"SteamGridDB capsule fetch error for {app_id}: {e}")

        # 4. Try VNDB Kana API for Visual Novel cover art (authentic vertical package artwork)
        if game_data:
            vndb_meta = game_data.get("vndb", {})
            vn_id = vndb_meta.get("vn_id")
            game_name = game_data.get("name")
            vndb_cover_url = self.fetch_vndb_cover(vn_id=vn_id, title=game_name)
            if vndb_cover_url:
                try:
                    resp = self._get(vndb_cover_url, headers=headers, timeout=6)
                    if resp.status_code == 200 and len(resp.content) > 0:
                        with open(cache_path, "wb") as f:
                            f.write(resp.content)
                        self.invalidate_memory_cache(str(app_id))
                        if game_data.get("is_non_steam"):
                            self.set_custom_artwork(str(app_id), cache_path)
                        return True
                except Exception as e:
                    logger.warning(f"Failed downloading VNDB cover {vndb_cover_url}: {e}")

            matched_aid = vndb_meta.get("matched_app_id")
            if matched_aid and str(matched_aid) != str(app_id):
                matched_urls = [
                    self.STEAM_CAPSULE_URL.format(appid=matched_aid),
                    f"https://cdn.akamai.steamstatic.com/steam/apps/{matched_aid}/library_600x900.jpg",
                    f"https://cdn.cloudflare.steamstatic.com/steam/apps/{matched_aid}/library_600x900_2x.jpg",
                    f"https://cdn.cloudflare.steamstatic.com/steam/apps/{matched_aid}/library_600x900.jpg",
                ]
                for m_url in matched_urls:
                    try:
                        resp = self._get(m_url, headers=headers, timeout=4)
                        if resp.status_code == 200 and len(resp.content) > 0:
                            with open(cache_path, "wb") as f:
                                f.write(resp.content)
                            self.invalidate_memory_cache(str(app_id))
                            if game_data.get("is_non_steam"):
                                self.set_custom_artwork(str(app_id), cache_path)
                            return True
                    except Exception:
                        pass

        # 4. Try Steam Store API for capsule or fallback
        try:
            api_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&filters=basic"
            resp = self._get(api_url, headers=headers, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                app_data = data.get(str(app_id), {}).get("data", {})
                img_url = app_data.get("capsule_imagev5") or app_data.get("capsule_image") or app_data.get("header_image")
                if img_url:
                    img_resp = self._get(img_url, headers=headers, timeout=4)
                    if img_resp.status_code == 200 and len(img_resp.content) > 0:
                        with open(cache_path, "wb") as f:
                            f.write(img_resp.content)
                        self.invalidate_memory_cache(str(app_id))
                        return True
        except Exception as e:
            logger.warning(f"Failed fallback download for app {app_id}: {e}")

        # 5. Check local Steam userdata grid for any artwork format before downloading wide headers
        if self.check_steam_grid(str(app_id), portrait_only=False):
            return True

        # 6. Last resort fallback to wide Steam header if no capsule or VNDB artwork found
        fallback_headers = [
            self.STEAM_HEADER_URL.format(appid=app_id),
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg",
        ]
        for h_url in fallback_headers:
            try:
                resp = self._get(h_url, headers=headers, timeout=4)
                if resp.status_code == 200 and len(resp.content) > 0:
                    with open(cache_path, "wb") as f:
                        f.write(resp.content)
                    self.invalidate_memory_cache(str(app_id))
                    return True
            except Exception:
                pass

        return False

    def download_hero(
        self,
        app_id: str,
        game_data: Optional[dict] = None,
        steamgriddb_client: Optional[Any] = None,
    ) -> bool:
        """Attempts to obtain a landscape hero banner for the visual novel detail view."""
        hero_path = self.get_cached_hero_path(str(app_id))
        if hero_path.exists() and hero_path.stat().st_size > 0:
            is_valid = True
            try:
                with Image.open(hero_path) as im:
                    w, h = im.size
                    if w < h:
                        is_valid = False
            except Exception:
                is_valid = False
            if is_valid:
                return True
            else:
                try:
                    hero_path.unlink(missing_ok=True)
                except Exception:
                    pass

        # 1. Check local Steam librarycache and grid
        if self.check_steam_library_hero(str(app_id)):
            return True

        headers = {"User-Agent": "Mozilla/5.0 (Linux; SteamDeck; VNPM)"}

        # 2. Try Steam CDN landscape URLs (hero and header)
        cdn_urls = [
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_hero.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg",
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_hero.jpg",
            f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg",
        ]
        for url in cdn_urls:
            try:
                resp = self._get(url, headers=headers, timeout=4)
                if resp.status_code == 200 and len(resp.content) > 0:
                    with open(hero_path, "wb") as f:
                        f.write(resp.content)
                    self.invalidate_memory_cache(str(app_id))
                    return True
            except Exception as e:
                logger.debug(f"Failed downloading hero {url} for app {app_id}: {e}")

        # 3. Try SteamGridDB for hero / wide assets
        sgdb = steamgriddb_client or self.steamgriddb_client
        if sgdb and hasattr(sgdb, "has_api_key") and sgdb.has_api_key():
            try:
                gid = sgdb.get_game_by_steam_appid(str(app_id))
                if not gid and game_data and game_data.get("name"):
                    results = sgdb.search_games(game_data["name"])
                    if results:
                        gid = results[0].get("id")
                if gid:
                    for asset_type in ("hero", "wide"):
                        assets = sgdb.get_assets(gid, asset_type)
                        if assets and assets[0].get("url"):
                            sgdb_bytes = self.download_image_bytes(assets[0]["url"], timeout=8)
                            if sgdb_bytes and len(sgdb_bytes) > 0:
                                with open(hero_path, "wb") as f:
                                    f.write(sgdb_bytes)
                                self.invalidate_memory_cache(str(app_id))
                                return True
            except Exception as e:
                logger.debug(f"SteamGridDB hero fetch error for {app_id}: {e}")

        # 4. Fallback for non-Steam or matched app id
        if game_data:
            vndb_meta = game_data.get("vndb", {})
            matched_aid = vndb_meta.get("matched_app_id")
            if matched_aid and str(matched_aid) != str(app_id):
                matched_urls = [
                    f"https://cdn.akamai.steamstatic.com/steam/apps/{matched_aid}/library_hero.jpg",
                    f"https://cdn.akamai.steamstatic.com/steam/apps/{matched_aid}/header.jpg",
                    f"https://cdn.cloudflare.steamstatic.com/steam/apps/{matched_aid}/library_hero.jpg",
                    f"https://cdn.cloudflare.steamstatic.com/steam/apps/{matched_aid}/header.jpg",
                ]
                for m_url in matched_urls:
                    try:
                        resp = self._get(m_url, headers=headers, timeout=4)
                        if resp.status_code == 200 and len(resp.content) > 0:
                            with open(hero_path, "wb") as f:
                                f.write(resp.content)
                            self.invalidate_memory_cache(str(app_id))
                            return True
                    except Exception:
                        pass

        return False

    def invalidate_memory_cache(self, app_id: str = None):
        """Clears memory cache for a given app_id or all app_ids."""
        if app_id is None:
            self._image_cache.clear()
            self._fallback_cache.clear()
        else:
            aid_str = str(app_id)
            hero_aid_str = f"{aid_str}_hero"
            for k in list(self._image_cache.keys()):
                if k[0] in (aid_str, hero_aid_str):
                    del self._image_cache[k]
            for k in list(self._fallback_cache.keys()):
                if k[0] in (aid_str, hero_aid_str):
                    del self._fallback_cache[k]

    def set_custom_artwork(self, app_id: str, image_path: Path, steam_root: Path = None) -> bool:
        """
        Sets a custom cover artwork for an app, updating the local cache and Steam grid files.
        """
        if not image_path or not image_path.exists():
            return False

        try:
            pil_img = Image.open(image_path).convert("RGB")
            # 1. Save to local VNPM cache
            cache_path = self.get_cached_path(str(app_id))
            pil_img.save(cache_path, quality=95)

            # 2. Deploy to Steam userdata grid directories if steam_root exists
            if not steam_root:
                from .steam_scanner import SteamScanner
                steam_root = SteamScanner.get_steam_root()

            if steam_root:
                userdata_dir = steam_root / "userdata"
                if userdata_dir.exists():
                    for udir in userdata_dir.iterdir():
                        if udir.is_dir() and udir.name.isdigit():
                            grid_dir = udir / "config" / "grid"
                            grid_dir.mkdir(parents=True, exist_ok=True)

                            # Landscape (920x430)
                            landscape = ImageOps.fit(pil_img, (920, 430), method=Image.Resampling.BICUBIC)
                            landscape.save(grid_dir / f"{app_id}.jpg", quality=95)

                            # Portrait (600x900)
                            portrait = ImageOps.fit(pil_img, (600, 900), method=Image.Resampling.BICUBIC)
                            portrait.save(grid_dir / f"{app_id}p.jpg", quality=95)

                            # Hero (1920x620)
                            hero = ImageOps.fit(pil_img, (1920, 620), method=Image.Resampling.BICUBIC)
                            hero.save(grid_dir / f"{app_id}_hero.jpg", quality=95)

                            # Icon (32x32)
                            icon = ImageOps.fit(pil_img, (32, 32), method=Image.Resampling.BICUBIC)
                            icon.save(grid_dir / f"{app_id}_icon.jpg", quality=95)

            self.invalidate_memory_cache(str(app_id))
            return True
        except Exception as e:
            logger.error(f"Failed to apply custom artwork for app {app_id}: {e}")
            return False

    def set_specific_grid_asset(
        self,
        app_id: str,
        asset_type: str,
        image_bytes: bytes,
        steam_root: Path = None
    ) -> bool:
        """
        Sets a specific Steam grid asset (capsule, wide, hero, logo, or icon) from raw image bytes.
        """
        if not image_bytes:
            return False

        import io
        try:
            pil_img = Image.open(io.BytesIO(image_bytes))
        except Exception as e:
            logger.error(f"Failed to decode image bytes for {asset_type}: {e}")
            return False

        try:
            # 1. If capsule or hero/wide, update local VNPM cache
            if asset_type == "capsule":
                cache_path = self.get_cached_path(str(app_id))
                pil_img.convert("RGB").save(cache_path, quality=95)
                self.invalidate_memory_cache(str(app_id))
            elif asset_type in ("hero", "wide"):
                hero_path = self.get_cached_hero_path(str(app_id))
                pil_img.convert("RGB").save(hero_path, quality=95)
                self.invalidate_memory_cache(str(app_id))

            # 2. Save into Steam userdata grid directories
            if not steam_root:
                from .steam_scanner import SteamScanner
                steam_root = SteamScanner.get_steam_root()

            # Check if image is animated (multi-frame)
            is_animated = getattr(pil_img, "is_animated", False) or getattr(pil_img, "n_frames", 1) > 1

            if steam_root:
                userdata_dir = steam_root / "userdata"
                if userdata_dir.exists():
                    for udir in userdata_dir.iterdir():
                        if udir.is_dir() and udir.name.isdigit():
                            grid_dir = udir / "config" / "grid"
                            grid_dir.mkdir(parents=True, exist_ok=True)

                            def _clean_slot(patterns):
                                for pat in patterns:
                                    for f in grid_dir.glob(pat):
                                        try:
                                            f.unlink(missing_ok=True)
                                        except Exception:
                                            pass

                            if asset_type == "capsule":
                                _clean_slot([f"{app_id}p.*"])
                                if is_animated:
                                    (grid_dir / f"{app_id}p.png").write_bytes(image_bytes)
                                else:
                                    portrait = ImageOps.fit(pil_img.convert("RGB"), (600, 900), method=Image.Resampling.BICUBIC)
                                    portrait.save(grid_dir / f"{app_id}p.jpg", quality=95)
                            elif asset_type == "wide":
                                _clean_slot([f"{app_id}.jpg", f"{app_id}.png", f"{app_id}.jpeg", f"{app_id}.webp"])
                                if is_animated:
                                    (grid_dir / f"{app_id}.png").write_bytes(image_bytes)
                                else:
                                    landscape = ImageOps.fit(pil_img.convert("RGB"), (920, 430), method=Image.Resampling.BICUBIC)
                                    landscape.save(grid_dir / f"{app_id}.jpg", quality=95)
                            elif asset_type == "hero":
                                _clean_slot([f"{app_id}_hero.*"])
                                if is_animated:
                                    (grid_dir / f"{app_id}_hero.png").write_bytes(image_bytes)
                                else:
                                    hero = ImageOps.fit(pil_img.convert("RGB"), (1920, 620), method=Image.Resampling.BICUBIC)
                                    hero.save(grid_dir / f"{app_id}_hero.jpg", quality=95)
                            elif asset_type == "logo":
                                _clean_slot([f"{app_id}_logo.*"])
                                if is_animated:
                                    (grid_dir / f"{app_id}_logo.png").write_bytes(image_bytes)
                                else:
                                    logo = pil_img.convert("RGBA")
                                    logo.save(grid_dir / f"{app_id}_logo.png", format="PNG")
                            elif asset_type == "icon":
                                _clean_slot([f"{app_id}_icon.*"])
                                if is_animated:
                                    (grid_dir / f"{app_id}_icon.png").write_bytes(image_bytes)
                                else:
                                    icon = ImageOps.fit(pil_img.convert("RGB"), (32, 32), method=Image.Resampling.BICUBIC)
                                    icon.save(grid_dir / f"{app_id}_icon.jpg", quality=95)

            return True
        except Exception as e:
            logger.error(f"Failed to set {asset_type} for app {app_id}: {e}")
            return False

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

    def get_cover_image(self, app_id: str, title: str = "", size: tuple[int, int] = (270, 125)):
        """Retrieves a CTkImage for the given AppID, from disk cache or procedural fallback."""
        import customtkinter as ctk

        cache_key = (str(app_id), size)
        cache_path = self.get_cached_path(str(app_id))

        # If already cached in memory from disk
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        if cache_path.exists() and cache_path.stat().st_size > 0:
            try:
                pil_img = Image.open(cache_path).convert("RGB")
                pil_img = ImageOps.fit(pil_img, size, method=Image.Resampling.BICUBIC)
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

    def get_hero_image(
        self,
        app_id: str,
        title: str = "",
        size: tuple[int, int] = (640, 220),
        game_data: Optional[dict] = None,
    ):
        """Retrieves a CTkImage hero banner for the visual novel detail view."""
        import customtkinter as ctk

        cache_key = (f"{app_id}_hero", size)
        hero_path = self.get_cached_hero_path(str(app_id))

        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        # 1. Check disk cache
        if hero_path.exists() and hero_path.stat().st_size > 0:
            try:
                pil_img = Image.open(hero_path).convert("RGB")
                pil_img = ImageOps.fit(pil_img, size, method=Image.Resampling.BICUBIC)
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
                if len(self._image_cache) >= self.MAX_CACHE_SIZE:
                    self._image_cache.pop(next(iter(self._image_cache)))
                self._image_cache[cache_key] = ctk_img
                return ctk_img
            except Exception as e:
                logger.warning(f"Failed to process cached hero image {hero_path}: {e}")

        # 2. Synchronous local Steam library discovery
        if self.check_steam_library_hero(str(app_id)):
            if hero_path.exists() and hero_path.stat().st_size > 0:
                try:
                    pil_img = Image.open(hero_path).convert("RGB")
                    pil_img = ImageOps.fit(pil_img, size, method=Image.Resampling.BICUBIC)
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
                    if len(self._image_cache) >= self.MAX_CACHE_SIZE:
                        self._image_cache.pop(next(iter(self._image_cache)))
                    self._image_cache[cache_key] = ctk_img
                    return ctk_img
                except Exception as e:
                    logger.warning(f"Failed to process local hero image {hero_path}: {e}")

        # 3. Fallback procedural banner
        fallback_key = (f"{app_id}_hero", title or "", size)
        if fallback_key in self._fallback_cache:
            return self._fallback_cache[fallback_key]

        pil_img = self.generate_fallback_image(title or str(app_id), size)
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
        if len(self._fallback_cache) >= self.MAX_CACHE_SIZE:
            self._fallback_cache.pop(next(iter(self._fallback_cache)))
        self._fallback_cache[fallback_key] = ctk_img
        return ctk_img

