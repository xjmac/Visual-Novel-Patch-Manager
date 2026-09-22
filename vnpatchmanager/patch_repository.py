import os
import json
import re
import difflib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from .utils import find_database_file as _find_db

try:
    import smbclient
except ImportError:
    smbclient = None


class PatchRepository:
    """Handles communicating with the NAS either via standard OS mounts or raw SMB."""

    BUNDLED_DB_PATH = Path(__file__).parent.parent / "vndb_steam_database.json"

    @classmethod
    def find_database_file(cls, explicit_path: Path = None) -> Path:
        return _find_db(explicit_path)

    def __init__(self, config_manager, bundled_db_path: Path = None):
        self.cm = config_manager
        self.bundled_db_path = bundled_db_path or self.find_database_file()
        self.available_patches = {} # Map AppID -> Patch config data
        self._title_map = None

    ROMAN_NUMERAL_MAP = {
        "x": "10", "ix": "9", "viii": "8", "vii": "7", "vi": "6",
        "v": "5", "iv": "4", "iii": "3", "ii": "2", "i": "1"
    }

    def _get_number_variants(self, text: str) -> list[str]:
        """Generates variants swapping between Roman numerals and Arabic digits (e.g. 'part i' <-> 'part 1')."""
        variants = {text}
        for r, d in self.ROMAN_NUMERAL_MAP.items():
            pattern_r = rf"\b{r}\b"
            if re.search(pattern_r, text):
                variants.add(re.sub(pattern_r, d, text))
            pattern_d = rf"\b{d}\b"
            if re.search(pattern_d, text):
                variants.add(re.sub(pattern_d, r, text))
        return list(variants)

    def _normalize_title(self, text: str) -> str:
        t = text.lower()
        t = t.replace("+", " plus ")
        t = t.replace("&", " and ")
        t = re.sub(r"[\*\:\~\-\_\.\,\!\?\'\"\(/\)]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _get_title_map(self) -> dict:
        if self._title_map is not None:
            return self._title_map

        title_map = {}

        def _add_title(t_str: str, aid_val: str, v_name: str, overwrite: bool = False):
            if not t_str:
                return
            t_norm = self._normalize_title(t_str)
            for var in self._get_number_variants(t_norm):
                if overwrite or var not in title_map:
                    title_map[var] = (str(aid_val), v_name)
                # Also index clean version without edition/patch keywords
                c_var = re.sub(
                    r"(?i)\b(?:perfect edition|edition|r-?18|patch|steam|dlc|uncensored|restoration)\b|(?<!\w)18\+",
                    "",
                    var,
                )
                c_var = re.sub(r"\s+", " ", c_var).strip()
                if c_var and (overwrite or c_var not in title_map):
                    title_map[c_var] = (str(aid_val), v_name)

        # 1. Index locally installed and owned Steam games (highest priority)
        try:
            from .steam_scanner import SteamScanner
            installed = SteamScanner.get_installed_games()
            for aid, ginfo in installed.items():
                gname = ginfo.get("name")
                if gname:
                    _add_title(gname, aid, gname, overwrite=True)

            owned = SteamScanner.get_owned_games()
            for aid, ginfo in owned.items():
                gname = ginfo.get("name")
                if gname and not gname.startswith("Steam App #"):
                    _add_title(gname, aid, gname, overwrite=False)
        except Exception as e:
            logger.debug(f"Could not index Steam games for patch title map: {e}")

        # 2. Index VNDB / offline database
        db_path = self.find_database_file(self.bundled_db_path)
        if db_path and db_path.exists():
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
                for aid, data in db.items():
                    if str(aid).startswith("_") or not isinstance(data, dict):
                        continue

                    steam_title = data.get("steam_title") or data.get("title")
                    if steam_title:
                        _add_title(steam_title, aid, steam_title, overwrite=False)

                    vn_title = data.get("vn_title", "")
                    if vn_title:
                        _add_title(vn_title, aid, vn_title, overwrite=False)

                    display_title = steam_title or vn_title
                    for p in data.get("patch_releases", []):
                        p_title = p.get("title", "")
                        if p_title:
                            _add_title(p_title, aid, display_title, overwrite=False)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Error loading title map for patch repository: {e}")

        self._title_map = title_map
        # Precompute pre-cleaned word sets for fast fuzzy/word-subset matching
        self._title_tokens = [
            (aid, v_title, set(re.sub(r"\b(edition|the|a|an)\b", "", t_norm).strip().split()))
            for t_norm, (aid, v_title) in title_map.items()
        ]
        return self._title_map

    def match_title_to_app_id(self, query: str) -> tuple[str, str]:
        """Matches a folder or archive name to a Steam AppID and title."""
        title_map = self._get_title_map()
        if not title_map or not query:
            return None, None

        q_norm = self._normalize_title(query)
        q_clean = re.sub(
            r"(?i)\b(?:perfect edition|edition|r-?18|patch|steam|dlc|rar|zip|7z)\b|(?<!\w)18\+",
            "",
            q_norm,
        ).strip()
        q_clean = re.sub(r"\s+", " ", q_clean).strip()

        # 1. Exact and normalized matching (checking number variants)
        for var in self._get_number_variants(q_norm):
            if var in title_map:
                return title_map[var]

        for var in self._get_number_variants(q_clean):
            if var in title_map:
                return title_map[var]

        # 2. Word set matching using precomputed token sets
        for q_check in [q_clean, q_norm]:
            for var in self._get_number_variants(q_check):
                q_words = set(var.split())
                best_aid, best_title, best_score = None, None, 0
                for aid, v_title, t_words in getattr(self, "_title_tokens", []):
                    if q_words == t_words:
                        return aid, v_title
                    if q_words and (q_words.issubset(t_words) or t_words.issubset(q_words)):
                        score = len(q_words & t_words) / max(len(q_words | t_words), 1)
                        if score > best_score:
                            best_score = score
                            best_aid = aid
                            best_title = v_title

                if best_score >= 0.5:
                    return best_aid, best_title

        close = difflib.get_close_matches(q_clean, list(title_map.keys()), n=1, cutoff=0.6)
        if close:
            return title_map[close[0]]

        return None, None

    def refresh_patches(self):
        """Scans the repository (Local or SMB) recursively and builds a map of available patches."""
        self.available_patches = {}
        mode = self.cm.config.get("mode")

        if mode == "local":
            self._scan_local()
        elif mode == "smb":
            self._scan_smb()

    def _scan_local(self):
        base_path = Path(self.cm.config.get("local_path"))
        if not base_path.exists():
            logger.warning(f"Local patch directory not found: {base_path}")
            return

        for root, dirs, files in os.walk(base_path):
            r_path = Path(root)

            # 1. Explicit patch.json has highest priority
            patch_json = r_path / "patch.json"
            if patch_json.exists():
                try:
                    with open(patch_json, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    app_id = data.get("steam_app_id")
                    if app_id is not None:
                        app_id = str(app_id)
                        data["patch_source_dir"] = str(r_path)
                        self.available_patches[app_id] = data
                        dirs[:] = [] # Do not recurse deeper into subfolders of this patch
                        continue
                except (OSError, json.JSONDecodeError) as e:
                    logger.warning(f"Error reading {patch_json}: {e}")

            # 2. Auto-detection: Ren'Py RPA patches
            rpa_files = [f for f in files if f.endswith(".rpa")]
            if rpa_files:
                aid, title = self.match_title_to_app_id(r_path.name)
                if aid and aid not in self.available_patches:
                    actions = [
                        {
                            "type": "copy_file",
                            "source": rpa,
                            "destination": "{game_dir}/game/"
                        }
                        for rpa in rpa_files
                    ]
                    self.available_patches[aid] = {
                        "steam_app_id": aid,
                        "game_name": title or r_path.name,
                        "actions": actions,
                        "patch_source_dir": str(r_path)
                    }
                    dirs[:] = []
                    continue

            # 3. Auto-detection: Extracted engine payloads (.pfs, .xp3, .arc, movie)
            payload_files = [
                f for f in files
                if any(f.endswith(ext) for ext in [".pfs.010", ".pfs.040", ".pfs.011", ".pfs.041", ".pfs.020", ".pfs.050", ".xp3", ".arc"])
            ]
            has_movie_dir = "movie" in dirs
            if payload_files or has_movie_dir:
                name_candidate = (
                    r_path.parent.name
                    if r_path.name.lower().startswith(("patch", "r18", "amanatsu_patch", "amanatsu_plus", "senrenbanka"))
                    else r_path.name
                )
                aid, title = self.match_title_to_app_id(name_candidate)
                if aid:
                    self.available_patches[aid] = {
                        "steam_app_id": aid,
                        "game_name": title or name_candidate,
                        "actions": [
                            {
                                "type": "copy_file",
                                "source": ".",
                                "destination": "{game_dir}/"
                            }
                        ],
                        "patch_source_dir": str(r_path)
                    }
                    dirs[:] = []
                    continue

            # 4. Auto-detection: Standalone archives (.zip, .7z, .rar)
            archives = [f for f in files if any(f.lower().endswith(ext) for ext in [".zip", ".7z", ".rar"])]
            for arc in archives:
                aid, title = self.match_title_to_app_id(arc)
                if not aid:
                    aid, title = self.match_title_to_app_id(r_path.name)
                if aid and aid not in self.available_patches:
                    self.available_patches[aid] = {
                        "steam_app_id": aid,
                        "game_name": title or r_path.name,
                        "actions": [
                            {
                                "type": "extract_archive",
                                "source": arc,
                                "destination": "{game_dir}/"
                            }
                        ],
                        "patch_source_dir": str(r_path)
                    }

    def _scan_smb(self):
        if smbclient is None:
            logger.error("SMB mode requires 'smbprotocol' package. Install with: pip install smbprotocol")
            return

        server = self.cm.config.get("smb_server")
        share = self.cm.config.get("smb_share")
        subpath = self.cm.config.get("smb_path")
        username = self.cm.config.get("smb_username")
        password = self.cm.config.get("smb_password")

        if not server or not share:
            return

        try:
            smbclient.register_session(server, username=username, password=password)
            base_unc = rf"\\{server}\{share}\{subpath.strip('/')}"

            # Recursive SMB walk
            def _walk_smb(current_unc):
                try:
                    entries = smbclient.listdir(current_unc)
                except OSError as e:
                    logger.debug(f"Error listing SMB directory {current_unc}: {e}")
                    return

                # Check for patch.json
                patch_json_unc = rf"{current_unc}\patch.json"
                try:
                    with smbclient.open_file(patch_json_unc, mode="r") as f:
                        data = json.load(f)
                    app_id = data.get("steam_app_id")
                    if app_id is not None:
                        app_id = str(app_id)
                        data["patch_source_dir"] = current_unc
                        self.available_patches[app_id] = data
                        return
                except (OSError, json.JSONDecodeError) as e:
                    logger.debug(f"Error reading patch.json at {patch_json_unc}: {e}")

                # Check directory entries
                files = []
                subdirs = []
                for entry in entries:
                    entry_unc = rf"{current_unc}\{entry}"
                    try:
                        stat = smbclient.stat(entry_unc)
                        if stat.st_mode & 0o040000:
                            subdirs.append((entry, entry_unc))
                        else:
                            files.append(entry)
                    except OSError as e:
                        logger.debug(f"Error statting SMB entry {entry_unc}: {e}")

                # RPA auto-detection
                rpa_files = [f for f in files if f.endswith(".rpa")]
                current_folder_name = current_unc.split("\\")[-1]
                if rpa_files:
                    aid, title = self.match_title_to_app_id(current_folder_name)
                    if aid and aid not in self.available_patches:
                        actions = [
                            {"type": "copy_file", "source": rpa, "destination": "{game_dir}/game/"}
                            for rpa in rpa_files
                        ]
                        self.available_patches[aid] = {
                            "steam_app_id": aid,
                            "game_name": title or current_folder_name,
                            "actions": actions,
                            "patch_source_dir": current_unc
                        }
                        return

                for _, subdir_unc in subdirs:
                    _walk_smb(subdir_unc)

            _walk_smb(base_unc)

        except Exception as e:
            logger.error(f"SMB Connection Error: {e}")
