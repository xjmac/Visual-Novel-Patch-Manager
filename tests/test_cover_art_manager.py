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
