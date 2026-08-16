import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from vnpatchmanager import VNDBScanner


def test_vndb_scanner_init_and_cache(tmp_path):
    cache_file = tmp_path / "vndb_cache.json"
    scanner = VNDBScanner(cache_file=cache_file)
    assert scanner.cache.get("_schema_version") == 3
    assert cache_file.parent.exists()

    # Test saving and re-loading cache
    scanner.cache["900001"] = {"is_vn": True, "vn_id": "v90001", "cached_at": time.time()}
    scanner._save_cache()
    assert cache_file.exists()

    new_scanner = VNDBScanner(cache_file=cache_file)
    assert "900001" in new_scanner.cache
    assert new_scanner.cache["900001"]["vn_id"] == "v90001"


def test_check_app_ids_cached_valid(tmp_path):
    cache_file = tmp_path / "vndb_cache.json"
    now = time.time()
    initial_cache = {
        "_schema_version": 3,
        "900050": {
            "is_vn": True,
            "vn_id": "v90050",
            "vn_title": "Synthetic Romance VN",
            "vndb_url": "https://vndb.org/v90050",
            "rating": 7.7,
            "votecount": 5000,
            "has_18plus_en_patch": True,
            "patch_releases": [{"id": "r90051", "title": "18+ Patch", "url": "https://vndb.org/r90051", "minage": 18}],
            "cached_at": now
        },
        "900070": {
            "is_vn": False,
            "cached_at": now
        }
    }
    cache_file.write_text(json.dumps(initial_cache))

    scanner = VNDBScanner(cache_file=cache_file)
    with patch.object(scanner, "_post_query") as mock_query:
        results = scanner.check_app_ids(["900050", "900070"])
        assert len(results) == 1
        assert "900050" in results
        assert results["900050"]["has_18plus_en_patch"] is True
        mock_query.assert_not_called()


def test_check_app_ids_queries_missing_and_expired(tmp_path):
    cache_file = tmp_path / "vndb_cache.json"
    empty_bundled = tmp_path / "empty_bundled.json"
    old_time = time.time() - (VNDBScanner.CACHE_TTL_SECONDS + 100)
    initial_cache = {
        "900001": {
            "is_vn": True,
            "vn_id": "v90001",
            "cached_at": old_time
        }
    }
    cache_file.write_text(json.dumps(initial_cache))

    scanner = VNDBScanner(cache_file=cache_file, bundled_db_path=empty_bundled)

    # Mock VNDB Kana API release response
    mock_release_response = {
        "results": [
            {
                "id": "r90500",
                "title": "Synthetic VN Alpha",
                "extlinks": [{"name": "steam", "id": 900001}],
                "vns": [{"id": "v90001", "title": "Synthetic Visual Novel: Blue Moon"}]
            }
        ]
    }

    # Mock VNDB Kana API patch releases response
    mock_patch_response = {
        "results": [
            {
                "id": "r90501",
                "title": "Synthetic VN English Patch",
                "minage": 0,
                "uncensored": False,
                "languages": [{"lang": "en"}],
                "vns": [{"id": "v90001"}]
            },
            {
                "id": "r90502",
                "title": "Synthetic VN 18+ Patch",
                "minage": 18,
                "uncensored": False,
                "languages": [{"lang": "en"}],
                "vns": [{"id": "v90001"}]
            }
        ]
    }

    def mock_post(payload):
        if "patch" in str(payload.get("filters", [])):
            return mock_patch_response
        return mock_release_response

    with patch.object(scanner, "_post_query", side_effect=mock_post):
        results = scanner.check_app_ids(["900001", "999999"])
        assert "900001" in results
        assert results["900001"]["vn_id"] == "v90001"
        assert results["900001"]["has_18plus_en_patch"] is True
        assert len(results["900001"]["patch_releases"]) == 1
        assert results["900001"]["patch_releases"][0]["id"] == "r90502"

        # 999999 was not in release response, should be marked non-VN in cache
        assert scanner.cache["999999"]["is_vn"] is False


def test_check_app_ids_non_18_patches_ignored(tmp_path):
    cache_file = tmp_path / "vndb_cache.json"
    scanner = VNDBScanner(cache_file=cache_file)

    mock_release_response = {
        "results": [
            {
                "id": "r90010",
                "title": "Synthetic All Ages VN",
                "extlinks": [{"name": "steam", "id": 905000}],
                "vns": [{"id": "v90050", "title": "Synthetic All Ages VN"}]
            }
        ]
    }

    # Patch in Spanish (not English) and patch with minage 0
    mock_patch_response = {
        "results": [
            {
                "id": "r90011",
                "title": "Spanish Patch",
                "minage": 18,
                "uncensored": False,
                "languages": [{"lang": "es"}],
                "vns": [{"id": "v90050"}]
            },
            {
                "id": "r90012",
                "title": "English All Ages Patch",
                "minage": 0,
                "uncensored": False,
                "languages": [{"lang": "en"}],
                "vns": [{"id": "v90050"}]
            }
        ]
    }

    def mock_post(payload):
        if "patch" in str(payload.get("filters", [])):
            return mock_patch_response
        return mock_release_response

    with patch.object(scanner, "_post_query", side_effect=mock_post):
        results = scanner.check_app_ids(["905000"])
        assert "905000" in results
        assert results["905000"]["has_18plus_en_patch"] is False
        assert len(results["905000"]["patch_releases"]) == 0


def test_check_app_ids_api_error_handling(tmp_path):
    cache_file = tmp_path / "vndb_cache.json"
    scanner = VNDBScanner(cache_file=cache_file)

    with patch.object(scanner, "_post_query", return_value=None):
        results = scanner.check_app_ids(["907000"])
        assert results == {}


def test_post_query_requests_success(tmp_path):
    scanner = VNDBScanner(cache_file=tmp_path / "cache.json")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": [{"id": "v1"}]}

    with patch("requests.post", return_value=mock_resp):
        res = scanner._post_query({"test": 123})
        assert res == {"results": [{"id": "v1"}]}


def test_post_query_requests_http_error(tmp_path):
    scanner = VNDBScanner(cache_file=tmp_path / "cache.json")

    with patch("requests.post", side_effect=Exception("Network error")):
        res = scanner._post_query({"test": 123})
        assert res is None


def test_post_query_requests_429_retry(tmp_path):
    import requests
    scanner = VNDBScanner(cache_file=tmp_path / "cache.json")

    mock_429 = MagicMock()
    mock_429.status_code = 429

    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.json.return_value = {"results": [{"id": "v1"}]}

    # First call 429, second call success
    with patch("requests.post", side_effect=[mock_429, mock_200]), \
         patch("time.sleep") as mock_sleep:
        res = scanner._post_query({"test": 123}, max_retries=2)
        assert res == {"results": [{"id": "v1"}]}
        assert mock_sleep.called


def test_check_app_ids_multi_vn_patch_and_ratings(tmp_path):
    cache_file = tmp_path / "vndb_cache.json"
    empty_bundled = tmp_path / "empty_bundled.json"
    scanner = VNDBScanner(cache_file=cache_file, bundled_db_path=empty_bundled)

    # Mock release queries for 2 separate games
    mock_release_response = {
        "results": [
            {
                "id": "r90101",
                "title": "Synthetic Game 1",
                "extlinks": [{"name": "steam", "id": 900021}],
                "vns": [{"id": "v90792", "title": "Synthetic Sequel 1", "rating": 78, "votecount": 250}]
            },
            {
                "id": "r90102",
                "title": "Synthetic Game 2",
                "extlinks": [{"name": "steam", "id": 900022}],
                "vns": [{"id": "v90793", "title": "Synthetic Sequel 2", "rating": 81, "votecount": 310}]
            }
        ]
    }

    # Single patch release that links to BOTH visual novels in its vns array
    mock_patch_response = {
        "results": [
            {
                "id": "r90999",
                "title": "Multi-Game Uncensored Patch Pack",
                "minage": 18,
                "uncensored": True,
                "languages": [{"lang": "en"}],
                "vns": [
                    {"id": "v99999", "title": "Other VN"},
                    {"id": "v90792", "title": "Synthetic Sequel 1"},
                    {"id": "v90793", "title": "Synthetic Sequel 2"}
                ]
            }
        ]
    }

    def mock_post(payload):
        if "patch" in str(payload.get("filters", [])):
            return mock_patch_response
        return mock_release_response

    with patch.object(scanner, "_post_query", side_effect=mock_post):
        results = scanner.check_app_ids(["900021", "900022"])
        assert len(results) == 2
        assert "900021" in results
        assert "900022" in results

        # Check ratings
        assert results["900021"]["rating"] == 7.8
        assert results["900021"]["votecount"] == 250
        assert results["900022"]["rating"] == 8.1
        assert results["900022"]["votecount"] == 310

        # Check both got matched to the multi-VN patch
        assert results["900021"]["has_18plus_en_patch"] is True
        assert results["900022"]["has_18plus_en_patch"] is True
        assert results["900021"]["patch_releases"][0]["id"] == "r90999"
        assert results["900022"]["patch_releases"][0]["id"] == "r90999"


def test_vndb_scanner_bundled_db_instant_lookup(tmp_path):
    cache_file = tmp_path / "vndb_cache.json"
    bundled_file = tmp_path / "bundled_test.json"
    bundled_file.write_text(json.dumps({
        "900021": {
            "vn_id": "v90792",
            "vn_title": "Synthetic Sequel 1",
            "rating": 5.7,
            "votecount": 121,
            "is_vn": True,
            "has_18plus_en_patch": True,
            "patch_releases": [{"id": "r90724", "title": "Uncensored Patch", "url": "https://vndb.org/r90724", "minage": 18}]
        }
    }))

    scanner = VNDBScanner(cache_file=cache_file, bundled_db_path=bundled_file)
    assert "900021" in scanner.bundled_db
    
    # Instant lookup without network
    cached = scanner.get_cached_vns()
    assert "900021" in cached
    assert cached["900021"]["has_18plus_en_patch"] is True

    # check_app_ids should resolve from bundled DB without network
    with patch.object(scanner, "_post_query") as mock_post:
        res = scanner.check_app_ids(["900021"])
        assert "900021" in res
        assert res["900021"]["rating"] == 5.7
        mock_post.assert_not_called()


def test_sync_vndb_snapshot_success(tmp_path):
    cache_file = tmp_path / "vndb_cache.json"
    scanner = VNDBScanner(cache_file=cache_file)

    mock_rows = [
        {
            "steam_appid": "900022",
            "vn_id": "v90793",
            "vn_title": "Synthetic Sequel 2",
            "c_rating": 563,
            "c_votecount": 95,
            "patch_release_id": "r90754",
            "patch_title": "Synthetic Sequel 2 - Uncensored Patch",
            "minage": 18,
            "patch_released": 20200801,
            "steam_released": 20200720,
            "steam_minage": None,
            "steam_uncensored": False
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_rows

    with patch("requests.get", return_value=mock_resp):
        success = scanner.sync_vndb_snapshot(timeout_sec=5)
        assert success is True
        assert "900022" in scanner.cache
        assert scanner.cache["900022"]["rating"] == 5.6
        assert scanner.cache["900022"]["has_18plus_en_patch"] is True
        assert "_last_snapshot_sync" in scanner.cache


def test_sync_vndb_snapshot_cooldown(tmp_path):
    cache_file = tmp_path / "vndb_cache.json"
    scanner = VNDBScanner(cache_file=cache_file)
    scanner.cache["_last_snapshot_sync"] = int(time.time()) # Just synced

    with patch("requests.get") as mock_get:
        # Without force: should skip network request
        success = scanner.sync_vndb_snapshot(timeout_sec=5, force=False)
        assert success is False
        mock_get.assert_not_called()

        # With force=True: should query network
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_get.return_value = mock_resp

        success_force = scanner.sync_vndb_snapshot(timeout_sec=5, force=True)
        assert success_force is True
        mock_get.assert_called_once()


def test_sync_vndb_snapshot_outlier_filtering(tmp_path):
    cache_file = tmp_path / "vndb_cache.json"
    scanner = VNDBScanner(cache_file=cache_file)

    mock_rows = [
        # Native 18+ game -> Should NOT have 18+ patch
        {
            "steam_appid": "900071",
            "vn_id": "v90824",
            "vn_title": "Synthetic Native Adult Game",
            "c_rating": 800,
            "c_votecount": 200,
            "patch_release_id": "r90768",
            "patch_title": "Synthetic Native Adult Game Episode 2",
            "minage": 18,
            "steam_minage": 18,
            "steam_uncensored": True,
            "patch_released": 20220601,
            "steam_released": 20220501
        },
        # Legacy pre-Steam fan patch -> Should NOT have 18+ patch
        {
            "steam_appid": "900072",
            "vn_id": "v90005",
            "vn_title": "Synthetic Legacy Fan Game",
            "c_rating": 850,
            "c_votecount": 3000,
            "patch_release_id": "r90213",
            "patch_title": "Synthetic Legacy Fan Game Ecstasy",
            "minage": 18,
            "steam_minage": 0,
            "steam_uncensored": False,
            "patch_released": 20130518,
            "steam_released": 20171101
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_rows

    with patch("requests.get", return_value=mock_resp):
        success = scanner.sync_vndb_snapshot(timeout_sec=5, force=True)
        assert success is True
        assert "900071" in scanner.cache
        assert scanner.cache["900071"]["has_18plus_en_patch"] is False
        assert "900072" in scanner.cache
        assert scanner.cache["900072"]["has_18plus_en_patch"] is False


def test_sync_vndb_snapshot_network_failure(tmp_path):
    cache_file = tmp_path / "vndb_cache.json"
    scanner = VNDBScanner(cache_file=cache_file)

    with patch("requests.get", side_effect=Exception("Connection timed out")):
        success = scanner.sync_vndb_snapshot(timeout_sec=1, force=True)
        assert success is False
