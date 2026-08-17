from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image
import pytest
import customtkinter as ctk
from vnpatchmanager import CoverArtManager


def test_cover_art_manager_init(tmp_path):
    cache_dir = tmp_path / "custom_covers"
    mgr = CoverArtManager(cache_dir=cache_dir)
    assert cache_dir.exists()
    assert mgr.cache_dir == cache_dir


def test_generate_fallback_image(tmp_path):
    mgr = CoverArtManager(cache_dir=tmp_path)
    img = mgr.generate_fallback_image("Synthetic VN Alpha", size=(280, 130))
    assert isinstance(img, Image.Image)
    assert img.size == (280, 130)
    assert img.mode == "RGB"


def test_get_cached_path(tmp_path):
    mgr = CoverArtManager(cache_dir=tmp_path)
    path = mgr.get_cached_path("900001")
    assert path == tmp_path / "900001.jpg"


def test_download_cover_already_cached(tmp_path):
    mgr = CoverArtManager(cache_dir=tmp_path)
    cache_file = tmp_path / "900001.jpg"
    cache_file.write_bytes(b"dummy image data")

    with patch("requests.get") as mock_get:
        result = mgr.download_cover("900001")
        assert result is True
        mock_get.assert_not_called()


def test_download_cover_success_remote(tmp_path):
    mgr = CoverArtManager(cache_dir=tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake jpeg bytes from steam"

    with patch("requests.get", return_value=mock_resp):
        result = mgr.download_cover("900002")
        assert result is True
        assert (tmp_path / "900002.jpg").read_bytes() == b"fake jpeg bytes from steam"


def test_download_cover_http_error_graceful(tmp_path):
    mgr = CoverArtManager(cache_dir=tmp_path)
    with patch("requests.get", side_effect=Exception("HTTP 404 Not Found")):
        result = mgr.download_cover("999999")
        assert result is False
        assert not (tmp_path / "999999.jpg").exists()


def test_get_cover_image_returns_ctk_image_cached_and_fallback(tmp_path):
    mgr = CoverArtManager(cache_dir=tmp_path)

    # 1. Fallback generation when no cache file exists
    ctk_img_fallback = mgr.get_cover_image("999999", title="Synthetic VN Starlight", size=(280, 130))
    assert isinstance(ctk_img_fallback, ctk.CTkImage)
    assert ctk_img_fallback._size == (280, 130)

    # Fallback memory caching check
    ctk_img_fallback_again = mgr.get_cover_image("999999", title="Synthetic VN Starlight", size=(280, 130))
    assert ctk_img_fallback_again is ctk_img_fallback

    # 2. Disk cache load
    real_img = Image.new("RGB", (300, 150), color=(100, 150, 200))
    real_img.save(tmp_path / "900001.jpg")

    ctk_img_cached = mgr.get_cover_image("900001", size=(280, 130))
    assert isinstance(ctk_img_cached, ctk.CTkImage)
    assert ctk_img_cached._size == (280, 130)

    # 3. Memory cache check
    ctk_img_cached_again = mgr.get_cover_image("900001", size=(280, 130))
    assert ctk_img_cached_again is ctk_img_cached


def test_download_cover_store_item_assets_fallback(tmp_path):
    mgr = CoverArtManager(cache_dir=tmp_path)

    # Store API payload
    store_api_data = {
        "900099": {
            "data": {
                "header_image": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/900099/hash/header.jpg"
            }
        }
    }

    mock_store_resp = MagicMock()
    mock_store_resp.status_code = 200
    mock_store_resp.json.return_value = store_api_data

    mock_img_resp = MagicMock()
    mock_img_resp.status_code = 200
    mock_img_resp.content = b"modern header bytes"

    mock_404 = MagicMock()
    mock_404.status_code = 404
    mock_404.content = b""

    def mock_requests_get(url, *args, **kwargs):
        if "appdetails" in url:
            return mock_store_resp
        elif "store_item_assets" in url:
            return mock_img_resp
        else:
            return mock_404

    with patch("requests.get", side_effect=mock_requests_get):
        result = mgr.download_cover("900099")
        assert result is True
        assert (tmp_path / "900099.jpg").read_bytes() == b"modern header bytes"


def test_invalidate_memory_cache_and_corrupt_disk_image(tmp_path):
    mgr = CoverArtManager(cache_dir=tmp_path)

    # 1. Populate memory cache
    real_img = Image.new("RGB", (300, 150), color=(100, 150, 200))
    real_img.save(tmp_path / "900001.jpg")
    img1 = mgr.get_cover_image("900001", size=(280, 130))
    assert ("900001", (280, 130)) in mgr._image_cache

    # Invalidate specific app_id
    mgr.invalidate_memory_cache("900001")
    assert ("900001", (280, 130)) not in mgr._image_cache

    # Repopulate and invalidate all
    mgr.get_cover_image("900001", size=(280, 130))
    mgr.invalidate_memory_cache(None)
    assert len(mgr._image_cache) == 0

    # 2. Corrupt disk image handling -> falls back to generator
    (tmp_path / "900002.jpg").write_bytes(b"corrupted not an image")
    fallback_img = mgr.get_cover_image("900002", title="Corrupt Game", size=(280, 130))
    assert isinstance(fallback_img, ctk.CTkImage)


def test_memory_cache_eviction_on_max_size(tmp_path):
    mgr = CoverArtManager(cache_dir=tmp_path)
    mgr.MAX_CACHE_SIZE = 2

    real_img = Image.new("RGB", (100, 50), color=(50, 50, 50))
    (tmp_path / "1.jpg").write_bytes(b"")
    real_img.save(tmp_path / "1.jpg")
    assert len(mgr._image_cache) <= 2


def test_cover_art_check_steam_grid(tmp_path):
    cache_dir = tmp_path / "cache"
    steam_root = tmp_path / "Steam"
    grid_dir = steam_root / "userdata" / "12345" / "config" / "grid"
    grid_dir.mkdir(parents=True, exist_ok=True)
    grid_img = grid_dir / "2348572834.jpg"
    grid_img.write_bytes(b"steam grid artwork bytes")

    mgr = CoverArtManager(cache_dir=cache_dir)
    assert mgr.check_steam_grid("2348572834", steam_root=steam_root) is True
    assert (cache_dir / "2348572834.jpg").exists()
    assert (cache_dir / "2348572834.jpg").read_bytes() == b"steam grid artwork bytes"


def test_cover_art_vndb_kana_fetch_and_game_data_download(tmp_path):
    cache_dir = tmp_path / "cache"
    mgr = CoverArtManager(cache_dir=cache_dir)

    # 1. Test fetch_vndb_cover API
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "results": [
            {
                "id": "v14887",
                "title": "Synthetic Novel",
                "image": {"url": "https://t.vndb.org/cv/87/27187.jpg"}
            }
        ]
    }

    with patch("requests.post", return_value=mock_post_resp):
        url = mgr.fetch_vndb_cover(vn_id="v14887")
        assert url == "https://t.vndb.org/cv/87/27187.jpg"

    # 2. Test download_cover with game_data fallback
    mock_get_img_resp = MagicMock()
    mock_get_img_resp.status_code = 200
    mock_get_img_resp.content = b"vndb cover image bytes"

    def mock_get(url, *args, **kwargs):
        if "vndb.org" in url:
            return mock_get_img_resp
        m404 = MagicMock()
        m404.status_code = 404
        return m404

    with patch("requests.post", return_value=mock_post_resp), \
         patch("requests.get", side_effect=mock_get):
        game_data = {
            "name": "Synthetic Novel",
            "is_non_steam": True,
            "vndb": {"vn_id": "v14887"}
        }
        success = mgr.download_cover("2348572834", game_data=game_data)
        assert success is True
        assert (cache_dir / "2348572834.jpg").exists()
        assert (cache_dir / "2348572834.jpg").read_bytes() == b"vndb cover image bytes"


def test_set_specific_grid_asset(tmp_path):
    cache_dir = tmp_path / "cache"
    steam_root = tmp_path / "Steam"
    grid_dir = steam_root / "userdata" / "999" / "config" / "grid"
    grid_dir.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGBA", (200, 200), color="purple")
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw_png = buf.getvalue()

    mgr = CoverArtManager(cache_dir=cache_dir)
    assert mgr.set_specific_grid_asset("123", "capsule", raw_png, steam_root=steam_root) is True
    assert (grid_dir / "123p.jpg").exists()

    assert mgr.set_specific_grid_asset("123", "wide", raw_png, steam_root=steam_root) is True
    assert (grid_dir / "123.jpg").exists()

    assert mgr.set_specific_grid_asset("123", "hero", raw_png, steam_root=steam_root) is True
    assert (grid_dir / "123_hero.jpg").exists()

    assert mgr.set_specific_grid_asset("123", "logo", raw_png, steam_root=steam_root) is True
    assert (grid_dir / "123_logo.png").exists()

    assert mgr.set_specific_grid_asset("123", "icon", raw_png, steam_root=steam_root) is True
    assert (grid_dir / "123_icon.jpg").exists()

    # Test animated replacement (multi-frame) removes existing .jpg files
    frame1 = Image.new("RGBA", (100, 100), color="blue")
    frame2 = Image.new("RGBA", (100, 100), color="red")
    anim_buf = io.BytesIO()
    frame1.save(anim_buf, format="PNG", save_all=True, append_images=[frame2], duration=100, loop=0)
    raw_anim_png = anim_buf.getvalue()

    assert mgr.set_specific_grid_asset("123", "hero", raw_anim_png, steam_root=steam_root) is True
    assert (grid_dir / "123_hero.png").exists()
    assert not (grid_dir / "123_hero.jpg").exists()

    assert mgr.set_specific_grid_asset("123", "capsule", raw_anim_png, steam_root=steam_root) is True
    assert (grid_dir / "123p.png").exists()
    assert not (grid_dir / "123p.jpg").exists()


