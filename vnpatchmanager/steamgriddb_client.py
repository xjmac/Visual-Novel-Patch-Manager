import logging
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class SteamGridDBClient:
    """
    Client for querying SteamGridDB API v2 and resolving artwork across
    SteamGridDB, VNDB, and Steam CDN.
    """

    API_BASE = "https://www.steamgriddb.com/api/v2"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key.strip()

    def set_api_key(self, api_key: str):
        self.api_key = api_key.strip()

    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def _get_headers(self) -> Dict[str, str]:
        headers = {"User-Agent": "VNPM/2.0 (Linux; SteamDeck; github.com/user/VNPM)"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def search_games(self, query: str) -> List[Dict[str, Any]]:
        """Searches SteamGridDB for games matching query string."""
        if not self.has_api_key() or not query.strip():
            return []
        url = f"{self.API_BASE}/search/autocomplete/{requests.utils.quote(query)}"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return data.get("data", [])
        except Exception as e:
            logger.warning(f"SteamGridDB search error: {e}")
        return []

    def get_game_by_steam_appid(self, app_id: str) -> Optional[int]:
        """Resolves SteamGridDB game ID from a Steam AppID."""
        if not self.has_api_key() or not app_id:
            return None
        url = f"{self.API_BASE}/games/steam/{app_id}"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and data.get("data"):
                    return data["data"].get("id")
        except Exception as e:
            logger.warning(f"SteamGridDB appid resolution error: {e}")
        return None

    def get_assets(
        self,
        game_id: int,
        asset_type: str,
        nsfw: bool = True,
        animated: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Fetches artwork entries from SteamGridDB for a given game ID and asset type.
        asset_type: 'capsule' (600x900), 'wide' (920x430,460x215), 'hero', 'logo', 'icon'
        nsfw: If True, fetches both safe and NSFW artwork (nsfw=any); otherwise safe only (nsfw=false).
        animated: If True, allows animated artwork (types=static,animated); otherwise static only (types=static).
        """
        if not self.has_api_key() or not game_id:
            return []

        nsfw_param = "any" if nsfw else "false"
        types_param = "static,animated" if animated else "static"

        endpoints = {
            "capsule": f"{self.API_BASE}/grids/game/{game_id}?dimensions=600x900&types={types_param}&nsfw={nsfw_param}&humor=any&epilepsy=any",
            "wide": f"{self.API_BASE}/grids/game/{game_id}?dimensions=920x430,460x215&types={types_param}&nsfw={nsfw_param}&humor=any&epilepsy=any",
            "hero": f"{self.API_BASE}/heroes/game/{game_id}?types={types_param}&nsfw={nsfw_param}&humor=any&epilepsy=any",
            "logo": f"{self.API_BASE}/logos/game/{game_id}?types={types_param}&nsfw={nsfw_param}&humor=any&epilepsy=any",
            "icon": f"{self.API_BASE}/icons/game/{game_id}?types={types_param}&nsfw={nsfw_param}&humor=any&epilepsy=any"
        }

        url = endpoints.get(asset_type)
        if not url:
            return []

        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    results = []
                    for item in data.get("data", []):
                        # Detect if asset is animated from API response
                        item_types = item.get("types", "")
                        item_mime = item.get("mime", "image/jpeg")
                        is_item_anim = (
                            item_types == "animated"
                            or item.get("animated") is True
                            or item_mime in ("image/png", "image/webp", "image/gif")
                        )
                        results.append({
                            "id": item.get("id"),
                            "url": item.get("url"),
                            "thumb": item.get("thumb") or item.get("url"),
                            "width": item.get("width"),
                            "height": item.get("height"),
                            "author": item.get("author", {}).get("name", "Community"),
                            "mime": item_mime,
                            "types": item_types,
                            "is_animated": is_item_anim,
                            "source": "SteamGridDB"
                        })
                    return results
        except Exception as e:
            logger.warning(f"SteamGridDB fetch error for {asset_type}: {e}")
        return []

    def get_fallback_assets(
        self,
        app_id: str,
        game_name: str,
        asset_type: str,
        vndb_meta: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Provides fallback visual assets directly from VNDB and Steam CDN
        when SteamGridDB API key is missing or yields no results.
        """
        assets = []
        vndb_meta = vndb_meta or {}
        matched_aid = vndb_meta.get("matched_app_id") or app_id

        # 1. Steam CDN official assets if Steam AppID available
        if matched_aid and str(matched_aid).isdigit() and int(matched_aid) < 2147483647:
            if asset_type in ("wide", "capsule"):
                assets.append({
                    "id": f"steam_header_{matched_aid}",
                    "url": f"https://cdn.akamai.steamstatic.com/steam/apps/{matched_aid}/header.jpg",
                    "thumb": f"https://cdn.akamai.steamstatic.com/steam/apps/{matched_aid}/header.jpg",
                    "width": 460,
                    "height": 215,
                    "author": "Official Steam Store Header",
                    "source": "Steam CDN"
                })
                assets.append({
                    "id": f"steam_library_capsule_{matched_aid}",
                    "url": f"https://cdn.akamai.steamstatic.com/steam/apps/{matched_aid}/library_600x900_2x.jpg",
                    "thumb": f"https://cdn.akamai.steamstatic.com/steam/apps/{matched_aid}/library_600x900_2x.jpg",
                    "width": 600,
                    "height": 900,
                    "author": "Official Steam Library Capsule",
                    "source": "Steam CDN"
                })
            elif asset_type == "hero":
                assets.append({
                    "id": f"steam_hero_{matched_aid}",
                    "url": f"https://cdn.akamai.steamstatic.com/steam/apps/{matched_aid}/library_hero.jpg",
                    "thumb": f"https://cdn.akamai.steamstatic.com/steam/apps/{matched_aid}/library_hero.jpg",
                    "width": 1920,
                    "height": 620,
                    "author": "Official Steam Hero Banner",
                    "source": "Steam CDN"
                })
            elif asset_type == "logo":
                assets.append({
                    "id": f"steam_logo_{matched_aid}",
                    "url": f"https://cdn.akamai.steamstatic.com/steam/apps/{matched_aid}/logo.png",
                    "thumb": f"https://cdn.akamai.steamstatic.com/steam/apps/{matched_aid}/logo.png",
                    "width": 640,
                    "height": 360,
                    "author": "Official Steam Logo Overlay",
                    "source": "Steam CDN"
                })

        # 2. VNDB official cover
        vn_id = vndb_meta.get("vn_id")
        if (asset_type in ("capsule", "wide")) and (vn_id or game_name):
            try:
                from .cover_art_manager import CoverArtManager
                cam = CoverArtManager()
                vndb_url = cam.fetch_vndb_cover(vn_id=vn_id, title=game_name)
                if vndb_url:
                    assets.append({
                        "id": f"vndb_cover_{vn_id or 'title'}",
                        "url": vndb_url,
                        "thumb": vndb_url,
                        "width": 600,
                        "height": 800,
                        "author": "Official VNDB Cover Art",
                        "source": "VNDB"
                    })
            except Exception as e:
                logger.warning(f"Error fetching VNDB fallback: {e}")

        return assets
