from unittest.mock import patch, MagicMock
from PIL import Image
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
    assert img1 is not None
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


def test_set_custom_artwork_aspect_ratio_preservation(tmp_path):
    cache_dir = tmp_path / "cache"
    steam_root = tmp_path / "Steam"
    grid_dir = steam_root / "userdata" / "999" / "config" / "grid"
    grid_dir.mkdir(parents=True, exist_ok=True)

    source_img_path = tmp_path / "custom_input.png"
    img = Image.new("RGB", (1000, 500), color="blue")
    img.save(source_img_path)

    mgr = CoverArtManager(cache_dir=cache_dir)
    res = mgr.set_custom_artwork("777", source_img_path, steam_root=steam_root)
    assert res is True

    landscape_file = grid_dir / "777.jpg"
    portrait_file = grid_dir / "777p.jpg"
    hero_file = grid_dir / "777_hero.jpg"
    icon_file = grid_dir / "777_icon.jpg"

    assert landscape_file.exists()
    assert portrait_file.exists()
    assert hero_file.exists()
    assert icon_file.exists()

    with Image.open(landscape_file) as im:
        assert im.size == (920, 430)
    with Image.open(portrait_file) as im:
        assert im.size == (600, 900)
    with Image.open(hero_file) as im:
        assert im.size == (1920, 620)
    with Image.open(icon_file) as im:
        assert im.size == (32, 32)


def test_check_steam_grid_portrait_precedence(tmp_path):
    """Verifies that check_steam_grid prioritizes portrait capsule {app_id}p.jpg over wide {app_id}.jpg."""
    cache_dir = tmp_path / "cache"
    steam_root = tmp_path / "Steam"
    grid_dir = steam_root / "userdata" / "12345" / "config" / "grid"
    grid_dir.mkdir(parents=True, exist_ok=True)

    # Create both wide and portrait
    (grid_dir / "9999.jpg").write_bytes(b"wide image bytes")
    (grid_dir / "9999p.jpg").write_bytes(b"portrait capsule bytes")

    mgr = CoverArtManager(cache_dir=cache_dir)
    assert mgr.check_steam_grid("9999", steam_root=steam_root) is True
    assert (cache_dir / "9999.jpg").read_bytes() == b"portrait capsule bytes"


def test_download_cover_legacy_wide_upgrade(tmp_path):
    """Verifies that download_cover detects legacy wide images and upgrades them to capsules."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    mgr = CoverArtManager(cache_dir=cache_dir)

    # Save a legacy wide image (460x215)
    legacy_wide = Image.new("RGB", (460, 215), color="blue")
    legacy_wide.save(cache_dir / "8888.jpg")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"new portrait capsule bytes"

    with patch.object(mgr, "_get", return_value=mock_resp) as mock_get:
        res = mgr.download_cover("8888")
        assert res is True
        mock_get.assert_called()
        assert "library_600x900_2x.jpg" in mock_get.call_args_list[0][0][0]
        assert (cache_dir / "8888.jpg").read_bytes() == b"new portrait capsule bytes"


def test_download_cover_capsule_priority_and_vndb_fallback(tmp_path):
    """Verifies that download_cover queries capsule first, and falls back to VNDB when capsule 404s."""
    cache_dir = tmp_path / "cache"
    mgr = CoverArtManager(cache_dir=cache_dir)

    called_urls = []

    def mock_get(url, *args, **kwargs):
        called_urls.append(url)
        resp = MagicMock()
        if "vndb.org" in url:
            resp.status_code = 200
            resp.content = b"vndb capsule bytes"
            return resp
        resp.status_code = 404
        resp.content = b""
        return resp

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "results": [{"id": "v47551", "image": {"url": "https://t.vndb.org/cv/41/107441.jpg"}}]
    }

    with patch.object(mgr, "_get", side_effect=mock_get), \
         patch.object(mgr, "_post", return_value=mock_post_resp):
        game_data = {
            "name": "Amanatsu+",
            "vndb": {"vn_id": "v47551"},
        }
        res = mgr.download_cover("3830560", game_data=game_data)
        assert res is True
        assert (cache_dir / "3830560.jpg").read_bytes() == b"vndb capsule bytes"
        # First attempt should have been Steam capsule
        assert "library_600x900_2x.jpg" in called_urls[0]
        # Then VNDB cover was fetched
        assert "https://t.vndb.org/cv/41/107441.jpg" in called_urls


def test_get_cached_hero_path(tmp_path):
    mgr = CoverArtManager(cache_dir=tmp_path)
    path = mgr.get_cached_hero_path("889700")
    assert path == tmp_path / "889700_hero.jpg"


def test_check_steam_library_hero_folder_and_flat(tmp_path):
    steam_root = tmp_path / "Steam"
    lib_dir = steam_root / "appcache" / "librarycache"
    app_dir = lib_dir / "889700"
    app_dir.mkdir(parents=True, exist_ok=True)

    hero_file = app_dir / "library_hero.jpg"
    hero_file.write_bytes(b"steam hero banner bytes")

    cache_dir = tmp_path / "cache"
    mgr = CoverArtManager(cache_dir=cache_dir)

    assert mgr.check_steam_library_hero("889700", steam_root=steam_root) is True
    assert (cache_dir / "889700_hero.jpg").read_bytes() == b"steam hero banner bytes"

    # Flat file test
    (lib_dir / "777777_header.jpg").write_bytes(b"flat header bytes")
    assert mgr.check_steam_library_hero("777777", steam_root=steam_root) is True
    assert (cache_dir / "777777_hero.jpg").read_bytes() == b"flat header bytes"


def test_check_steam_library_hero_userdata_grid(tmp_path):
    steam_root = tmp_path / "Steam"
    grid_dir = steam_root / "userdata" / "123456" / "config" / "grid"
    grid_dir.mkdir(parents=True, exist_ok=True)

    # Save a wide image
    wide_img = Image.new("RGB", (920, 430), color="purple")
    wide_img.save(grid_dir / "555555.jpg")

    cache_dir = tmp_path / "cache"
    mgr = CoverArtManager(cache_dir=cache_dir)
    assert mgr.check_steam_library_hero("555555", steam_root=steam_root) is True
    assert (cache_dir / "555555_hero.jpg").exists()


def test_download_hero_cached_and_cdn(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    mgr = CoverArtManager(cache_dir=cache_dir)

    # 1. Existing cached landscape image
    hero_file = cache_dir / "1234_hero.jpg"
    im = Image.new("RGB", (1920, 620), color="green")
    im.save(hero_file)
    assert mgr.download_hero("1234") is True

    # 2. Existing corrupt/portrait image -> unlinks and downloads from CDN
    bad_hero = cache_dir / "5678_hero.jpg"
    portrait = Image.new("RGB", (600, 900), color="red")
    portrait.save(bad_hero)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"cdn hero bytes"

    with patch.object(mgr, "_get", return_value=mock_resp):
        assert mgr.download_hero("5678") is True
        assert (cache_dir / "5678_hero.jpg").read_bytes() == b"cdn hero bytes"


def test_download_hero_steamgriddb(tmp_path):
    cache_dir = tmp_path / "cache"
    mgr = CoverArtManager(cache_dir=cache_dir)

    mock_sgdb = MagicMock()
    mock_sgdb.has_api_key.return_value = True
    mock_sgdb.get_game_by_steam_appid.return_value = 999
    mock_sgdb.get_assets.return_value = [{"url": "https://sgdb.example/hero.jpg"}]

    with patch.object(mgr, "check_steam_library_hero", return_value=False), \
         patch.object(mgr, "_get", side_effect=Exception("CDN offline")), \
         patch.object(mgr, "download_image_bytes", return_value=b"sgdb hero bytes"):
        assert mgr.download_hero("999", steamgriddb_client=mock_sgdb) is True
        assert (cache_dir / "999_hero.jpg").read_bytes() == b"sgdb hero bytes"


def test_get_hero_image_cached_and_fallback(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    mgr = CoverArtManager(cache_dir=cache_dir)

    # 1. Fallback when not cached
    fallback_hero = mgr.get_hero_image("111111", title="Cyber Novel", size=(640, 220))
    assert isinstance(fallback_hero, ctk.CTkImage)
    assert fallback_hero._size == (640, 220)

    # Memory cache hit
    assert mgr.get_hero_image("111111", title="Cyber Novel", size=(640, 220)) is fallback_hero

    # 2. Disk cache load
    im = Image.new("RGB", (1920, 620), color="blue")
    im.save(cache_dir / "222222_hero.jpg")

    cached_hero = mgr.get_hero_image("222222", size=(640, 220))
    assert isinstance(cached_hero, ctk.CTkImage)
    assert cached_hero._size == (640, 220)


def test_set_specific_grid_asset_hero_updates_cache(tmp_path):
    cache_dir = tmp_path / "cache"
    mgr = CoverArtManager(cache_dir=cache_dir)

    import io
    im = Image.new("RGB", (1920, 620), color="yellow")
    buf = io.BytesIO()
    im.save(buf, format="JPEG")
    raw_bytes = buf.getvalue()

    assert mgr.set_specific_grid_asset("333333", "hero", raw_bytes) is True
    assert (cache_dir / "333333_hero.jpg").exists()


def test_get_hero_image_local_steam_discovery(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    mgr = CoverArtManager(cache_dir=cache_dir)

    def mock_check(app_id):
        hero_p = mgr.get_cached_hero_path(app_id)
        im = Image.new("RGB", (1920, 620), color="cyan")
        im.save(hero_p)
        return True

    with patch.object(mgr, "check_steam_library_hero", side_effect=mock_check):
        hero_img = mgr.get_hero_image("444444", size=(640, 220))
        assert isinstance(hero_img, ctk.CTkImage)
        assert hero_img._size == (640, 220)


def test_download_hero_non_steam_matched_app_id(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    mgr = CoverArtManager(cache_dir=cache_dir)

    def mock_get(url, *args, **kwargs):
        resp = MagicMock()
        if "888111" in url:
            resp.status_code = 200
            resp.content = b"matched hero bytes"
        else:
            resp.status_code = 404
            resp.content = b""
        return resp

    game_data = {
        "name": "Non Steam Novel",
        "vndb": {"matched_app_id": "888111"}
    }

    with patch.object(mgr, "check_steam_library_hero", return_value=False), \
         patch.object(mgr, "_get", side_effect=mock_get):
        res = mgr.download_hero("non_steam_1", game_data=game_data)
        assert res is True
        assert (cache_dir / "non_steam_1_hero.jpg").read_bytes() == b"matched hero bytes"


def test_download_image_bytes_and_set_specific_asset(tmp_path):
    mgr = CoverArtManager(cache_dir=tmp_path)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake image bytes"

    with patch.object(mgr, "_get", return_value=mock_resp):
        data = mgr.download_image_bytes("https://example.com/art.jpg")
        assert data == b"fake image bytes"

    # None check
    assert mgr.download_image_bytes("") is None

    # Test download_and_set_specific_asset
    im = Image.new("RGB", (1920, 620), color="pink")
    import io
    buf = io.BytesIO()
    im.save(buf, format="JPEG")
    valid_bytes = buf.getvalue()

    with patch.object(mgr, "download_image_bytes", return_value=valid_bytes):
        assert mgr.download_and_set_specific_asset("121212", "hero", "https://example.com/hero.jpg") is True
        assert (tmp_path / "121212_hero.jpg").exists()







