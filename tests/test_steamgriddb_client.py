from unittest.mock import patch, MagicMock
from vnpatchmanager.steamgriddb_client import SteamGridDBClient

def test_steamgriddb_client_init_and_key():
    client = SteamGridDBClient("test_token_123")
    assert client.has_api_key() is True
    assert client.api_key == "test_token_123"

    client.set_api_key("")
    assert client.has_api_key() is False


def test_steamgriddb_search_games():
    client = SteamGridDBClient("fake_token")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "data": [{"id": 1001, "name": "Synthetic Visual Novel"}]
    }

    with patch("requests.get", return_value=mock_resp):
        res = client.search_games("Synthetic Visual Novel")
        assert len(res) == 1
        assert res[0]["id"] == 1001


def test_steamgriddb_get_game_by_steam_appid():
    client = SteamGridDBClient("fake_token")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "data": {"id": 5555}
    }

    with patch("requests.get", return_value=mock_resp):
        game_id = client.get_game_by_steam_appid("900001")
        assert game_id == 5555


def test_steamgriddb_get_assets():
    client = SteamGridDBClient("fake_token")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "data": [
            {
                "id": 101,
                "url": "https://cdn.steamgriddb.com/grid/101.png",
                "thumb": "https://cdn.steamgriddb.com/thumb/101.jpg",
                "width": 600,
                "height": 900,
                "author": {"name": "ArtistAlpha"}
            }
        ]
    }

    with patch("requests.get", return_value=mock_resp) as mock_get:
        assets = client.get_assets(5555, "hero", nsfw=True, animated=True)
        assert len(assets) == 1
        assert assets[0]["id"] == 101
        assert assets[0]["author"] == "ArtistAlpha"
        assert "nsfw=any" in mock_get.call_args[0][0]
        assert "types=static,animated" in mock_get.call_args[0][0]
        assert "epilepsy=any" in mock_get.call_args[0][0]

        client.get_assets(5555, "capsule", nsfw=False, animated=False)
        assert "nsfw=false" in mock_get.call_args[0][0]
        assert "types=static" in mock_get.call_args[0][0]
        assert "epilepsy=any" in mock_get.call_args[0][0]


def test_steamgriddb_get_fallback_assets():
    client = SteamGridDBClient("") # No API key
    fallbacks = client.get_fallback_assets(
        app_id="900001",
        game_name="Synthetic Novel",
        asset_type="capsule",
        vndb_meta={"matched_app_id": "900001", "vn_id": "v123"}
    )
    assert len(fallbacks) >= 1
    assert any("Steam CDN" in f["source"] for f in fallbacks)

