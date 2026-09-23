import json
import logging
import os
import re
import time
from pathlib import Path
import requests
from .utils import extract_part_numbers, find_database_file as _find_db, is_mocked

logger = logging.getLogger(__name__)

VNDB_SNAPSHOT_SQL = '''
WITH steam_releases AS (
    SELECT DISTINCT
        e.value AS steam_appid,
        rel.id AS steam_rel_id,
        rel.title AS steam_rel_title,
        rel.minage AS steam_minage,
        rel.uncensored AS steam_uncensored,
        COALESCE(rel.released, 20100101) AS steam_released,
        v.id AS vn_id,
        v.title AS vn_title,
        v.c_rating,
        v.c_votecount
    FROM extlinks e
    JOIN releases_extlinks re ON re.link = e.id
    JOIN releases rel ON rel.id = re.id
    JOIN releases_vn rv ON rv.id = rel.id
    JOIN vn v ON v.id = rv.vid
    WHERE e.site = 'steam'
),
patch_releases AS (
    SELECT DISTINCT
        sr.steam_appid,
        rel.id AS patch_release_id,
        rel.title AS patch_title,
        rel.minage,
        COALESCE(rel.released, 20300101) AS patch_released
    FROM steam_releases sr
    JOIN releases_vn rv ON rv.vid = sr.vn_id
    JOIN releases rel ON rel.id = rv.id
    JOIN releases_lang rl ON rl.id = rel.id
    WHERE rel.patch = true
      AND (rel.minage = 18 OR rel.uncensored = true)
      AND rl.lang = 'en'
)
SELECT
    sr.steam_appid,
    sr.steam_rel_id,
    sr.steam_rel_title,
    sr.steam_minage,
    sr.steam_uncensored,
    sr.steam_released,
    sr.vn_id,
    sr.vn_title,
    sr.c_rating,
    sr.c_votecount,
    pr.patch_release_id,
    pr.patch_title,
    pr.minage,
    pr.patch_released
FROM steam_releases sr
LEFT JOIN patch_releases pr ON pr.steam_appid = sr.steam_appid;
'''

class VNDBScanner:
    """Scans Steam AppIDs against VNDB (Visual Novel Database) to identify Visual Novels and 18+ English patches."""

    API_URL = "https://api.vndb.org/kana/release"
    SNAPSHOT_URL = "https://query.vndb.org/"
    CACHE_FILE = Path.home() / ".cache" / "vnpatchmanager" / "vndb_cache.json"
    BUNDLED_DB_PATH = Path(__file__).parent.parent / "vndb_steam_database.json"
    CACHE_TTL_SECONDS = 86400 * 7 # 7 days (bundled DB provides instant offline baseline)

    SCHEMA_VERSION = 3

    @classmethod
    def find_database_file(cls, explicit_path: Path = None) -> Path:
        return _find_db(explicit_path)

    def __init__(self, cache_file: Path = None, bundled_db_path: Path = None, session: requests.Session = None):
        self.cache_file = cache_file or self.CACHE_FILE
        self.bundled_db_path = bundled_db_path or self.find_database_file()
        self._session = session or requests.Session()
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.bundled_db = self._load_bundled_db()
        self.cache = self._load_cache()

    def _load_bundled_db(self) -> dict:
        db_path = self.find_database_file(self.bundled_db_path)
        if db_path and db_path.exists():
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading bundled VNDB database: {e}")
        return {}

    def _load_cache(self) -> dict:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("_schema_version") == self.SCHEMA_VERSION:
                        return data
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load cache: {e}")
        return {"_schema_version": self.SCHEMA_VERSION}

    def _save_cache(self):
        try:
            self.cache["_schema_version"] = self.SCHEMA_VERSION
            temp_file = self.cache_file.with_suffix('.tmp')
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2)
            os.replace(temp_file, self.cache_file)
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

    def get_cached_vns(self) -> dict[str, dict]:
        """Returns all known visual novels currently in bundled database or cache without making network requests."""
        cached_vns = {}
        # 1. Baseline from bundled snapshot
        for aid_str, entry in self.bundled_db.items():
            if isinstance(entry, dict) and entry.get("is_vn"):
                cached_vns[aid_str] = entry
        # 2. User cache overrides and updates
        for aid_str, entry in self.cache.items():
            if isinstance(entry, dict) and entry.get("is_vn"):
                cached_vns[aid_str] = entry
        return cached_vns

    def check_app_ids(self, app_ids: list[str], on_batch_complete=None) -> dict[str, dict]:
        """
        Takes a list of Steam AppIDs, resolves against bundled DB and local cache instantly (<0.01s).
        Returns a dict of {app_id: vn_info}.
        """
        results = {}
        to_query = []

        for aid in app_ids:
            aid_str = str(aid)
            # Check user cache first
            cached_entry = self.cache.get(aid_str)
            if cached_entry and isinstance(cached_entry, dict):
                if cached_entry.get("is_vn"):
                    results[aid_str] = cached_entry
                continue

            # Check bundled database
            bundled_entry = self.bundled_db.get(aid_str)
            if bundled_entry and isinstance(bundled_entry, dict):
                if bundled_entry.get("is_vn"):
                    results[aid_str] = bundled_entry
                continue

            to_query.append(aid_str)

        if on_batch_complete:
            on_batch_complete(results.copy(), len(app_ids) - len(to_query), len(app_ids))

        if not to_query:
            return results

        # For remaining truly uncached AppIDs, do a quick batch query if online (limited to max 15 to prevent 429)
        try:
            batch = to_query[:15]
            filters = ["or"] + [["extlink", "=", ["steam", int(a)]] for a in batch if a.isdigit()]
            if len(filters) > 1:
                payload = {
                    "filters": filters,
                    "fields": "id, title, extlinks.id, extlinks.name, vns.id, vns.title, vns.rating, vns.votecount",
                    "results": 50
                }
                data = self._post_query(payload)
                if data and "results" in data:
                    found_app_to_vn = {}
                    vn_ids_to_fetch = set()
                    for release in data.get("results", []):
                        steam_aid = None
                        for ext in release.get("extlinks", []):
                            if ext.get("name") == "steam" and ext.get("id"):
                                steam_aid = str(ext["id"])
                                break
                        if not steam_aid:
                            continue
                        vns = release.get("vns", [])
                        if vns:
                            p_vn = vns[0]
                            vn_id = p_vn.get("id")
                            raw_rating = p_vn.get("rating")
                            found_app_to_vn[steam_aid] = {
                                "vn_id": vn_id,
                                "vn_title": p_vn.get("title"),
                                "vndb_url": f"https://vndb.org/{vn_id}",
                                "rating": round(raw_rating / 10.0, 1) if raw_rating else None,
                                "votecount": p_vn.get("votecount", 0),
                                "is_vn": True,
                                "has_18plus_en_patch": False,
                                "patch_releases": [],
                                "cached_at": time.time()
                            }
                            if vn_id:
                                vn_ids_to_fetch.add(vn_id)

                    if vn_ids_to_fetch:
                        vn_filter_list = ["or"] + [["vn", "=", ["id", "=", vid]] for vid in vn_ids_to_fetch]
                        patch_payload = {
                            "filters": ["and", ["patch", "=", True], vn_filter_list],
                            "fields": "id, title, minage, uncensored, languages.lang, vns.id, vns.title",
                            "results": 50
                        }
                        patch_data = self._post_query(patch_payload)
                        if patch_data and "results" in patch_data:
                            for p_rel in patch_data.get("results", []):
                                p_vns = p_rel.get("vns", [])
                                langs = [lang_item.get("lang") for lang_item in p_rel.get("languages", [])]
                                is_en = "en" in langs
                                is_18 = (p_rel.get("minage") == 18) or (p_rel.get("uncensored") is True)
                                if is_en and is_18:
                                    for p_vn in p_vns:
                                        p_vn_id = p_vn.get("id")
                                        if not p_vn_id:
                                            continue
                                        for aid_key, vn_entry in found_app_to_vn.items():
                                            if vn_entry.get("vn_id") == p_vn_id:
                                                vn_entry["has_18plus_en_patch"] = True
                                                vn_entry["patch_releases"].append({
                                                    "id": p_rel.get("id"),
                                                    "title": p_rel.get("title"),
                                                    "url": f"https://vndb.org/{p_rel.get('id')}",
                                                    "minage": p_rel.get("minage")
                                                })

                    for aid_k in batch:
                        if aid_k not in found_app_to_vn:
                            self.cache[aid_k] = {"is_vn": False, "cached_at": time.time()}
                        else:
                            self.cache[aid_k] = found_app_to_vn[aid_k]
                            results[aid_k] = found_app_to_vn[aid_k]
                    self._save_cache()
        except Exception as e:
            logger.warning(f"Batch query failed: {e}")

        return results

    def sync_vndb_snapshot(self, timeout_sec=15, force=False) -> bool:
        """
        Fetches the complete Steam VN mapping from query.vndb.org in a single bulk request (~3s)
        and updates the local cache.
        Enforces a 24-hour cooldown unless force=True to respect VNDB server load.
        """
        now = int(time.time())
        last_sync = self.cache.get("_last_snapshot_sync", 0)
        if not force and (now - last_sync < 86400):
            # Already synced within the last 24 hours; make 0 network requests
            return False

        try:
            url = self.SNAPSHOT_URL
            params = {"sql": VNDB_SNAPSHOT_SQL, "export": "json"}
            headers = {"User-Agent": "VNPM/2.0 (Linux; SteamDeck; github.com/user/VNPM)"}

            client = requests if is_mocked(requests.get) else self._session
            response = client.get(url, params=params, headers=headers, timeout=timeout_sec)
            response.raise_for_status()
            raw_data = response.json()

            for row in raw_data:
                aid = str(row.get("steam_appid", "")).strip()
                if not aid or not aid.isdigit():
                    continue

                steam_minage = row.get("steam_minage")
                steam_uncensored = row.get("steam_uncensored")
                is_natively_18 = (steam_minage == 18) or (steam_uncensored is True)

                vn_id = row.get("vn_id")
                vn_title = row.get("vn_title")
                raw_rating = row.get("c_rating")
                rating_score = round(raw_rating / 100.0, 1) if raw_rating else None
                votes = row.get("c_votecount") or 0
                patch_id = row.get("patch_release_id")
                patch_title = row.get("patch_title") or ""
                minage = row.get("minage")
                patch_released = row.get("patch_released") or 20300101
                steam_released = row.get("steam_released") or 20100101

                steam_rel_title = row.get("steam_rel_title") or ""
                clean_steam_title = None
                if steam_rel_title:
                    clean_steam_title = re.sub(
                        r"(?i)\s*[-~–—]\s*(?:censored|all-ages|steam|download|package|english)?\s*(?:edition|version|ver\.?|release)\b.*$",
                        "",
                        steam_rel_title,
                    ).strip() or steam_rel_title.strip()

                if aid not in self.cache:
                    self.cache[aid] = {
                        "vn_id": vn_id,
                        "vn_title": vn_title,
                        "steam_title": clean_steam_title or row.get("steam_title"),
                        "vndb_url": f"https://vndb.org/{vn_id}",
                        "rating": rating_score,
                        "votecount": votes,
                        "is_vn": True,
                        "is_natively_18": is_natively_18,
                        "has_18plus_en_patch": False,
                        "patch_releases": [],
                        "cached_at": now,
                    }
                elif clean_steam_title and not self.cache[aid].get("steam_title"):
                    self.cache[aid]["steam_title"] = clean_steam_title

                if patch_id and not is_natively_18:
                    title_for_part_check = clean_steam_title or self.cache[aid].get("steam_title") or ""
                    parts_app = extract_part_numbers(title_for_part_check)
                    parts_patch = extract_part_numbers(patch_title)
                    is_part_conflict = bool(parts_app and parts_patch and not (parts_app & parts_patch))

                    is_relevant_patch = (
                        not is_part_conflict
                        and (
                            (patch_released >= steam_released)
                            or any(
                                kw in patch_title.lower()
                                for kw in [
                                    "steam",
                                    "uncensor",
                                    "restoration",
                                    "r-18",
                                    "adult patch",
                                    "18+ patch",
                                    "18+ dlc",
                                    "director",
                                ]
                            )
                        )
                    )
                    if is_relevant_patch:
                        entry = self.cache[aid]
                        entry["has_18plus_en_patch"] = True
                        if not any(p.get("id") == patch_id for p in entry.get("patch_releases", [])):
                            entry.setdefault("patch_releases", []).append({
                                "id": patch_id,
                                "title": patch_title,
                                "url": f"https://vndb.org/{patch_id}",
                                "minage": minage,
                            })

            self.cache["_last_snapshot_sync"] = now
            self._save_cache()
            return True
        except Exception as e:
            logger.error(f"Error syncing VNDB snapshot: {e}")
            return False

    def _post_query(self, payload: dict, max_retries: int = 3) -> dict:
        """Sends a JSON POST query to the VNDB Kana API with rate-limiting backoff."""
        for attempt in range(max_retries):
            try:
                time.sleep(0.35)
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": "VNPM/2.0 (Linux; SteamDeck; github.com/user/VNPM)"
                }
                client = requests if is_mocked(requests.post) else self._session
                response = client.post(self.API_URL, json=payload, headers=headers, timeout=8)
                if response.status_code == 429:
                    wait_seconds = 2 ** (attempt + 1)
                    time.sleep(wait_seconds)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError as e:
                logger.error(f"VNDB API HTTP Error: {e}")
                break
            except Exception as e:
                logger.error(f"VNDB API Request failed: {e}")
                break
        return None
