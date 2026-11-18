"""BonxBot's read endpoints (public_api/views/bot.py): skins, players, maps."""

import json

import pytest
from django.db import OperationalError

from integrations.map_decoder import DecodeError, DecodeResult
from public_api import selectors as api_selectors
from public_api.views import bot
from tests.factories import SkinFactory

pytestmark = pytest.mark.django_db

TOKEN = "test-bot-token"
AUTH = {"HTTP_AUTHORIZATION": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _bot_token(settings):
    settings.BONXBOT_API_TOKEN = TOKEN
    settings.MEDIA_URL = "/media/"


def get(client, path, **extra):
    return client.get(f"/api/bot/{path}", **{**AUTH, **extra})


# --- access ----------------------------------------------------------------------


@pytest.mark.parametrize("path", ["skins/search/?q=x", "skins/random/", "skins/1/", "players/tulip/"])
def test_needs_the_token(client, path):
    response = client.get(f"/api/bot/{path}", HTTP_AUTHORIZATION="Bearer wrong")
    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "unauthorized"}


def test_off_when_no_token_is_set(client, settings):
    settings.BONXBOT_API_TOKEN = ""
    assert client.get("/api/bot/skins/random/", HTTP_AUTHORIZATION="Bearer ").status_code == 401


def test_wrong_method(client):
    assert client.post("/api/bot/skins/random/", **AUTH).status_code == 405
    assert get(client, "maps/decode/").status_code == 405


# --- skins -------------------------------------------------------------------------


def test_search_finds_by_name_best_first(client):
    SkinFactory(name="Hot Dog", creator="The Saucy Tulip")
    SkinFactory(name="Hot Dog Deluxe")
    SkinFactory(name="Reality.exe", creator="Somepoop")

    data = get(client, "skins/search/?q=hot%20dog&limit=5").json()["data"]

    names = [s["name"] for s in data["skins"]]
    assert names[0] == "Hot Dog"
    assert "Reality.exe" not in names
    first = data["skins"][0]
    assert first["creator"] == "The Saucy Tulip"
    assert first["url"] == f"http://testserver/skins/detail/{first['id']}"
    assert first["image_url"] == f"http://testserver/media/skins/{first['id']}.png"
    assert first["favorites"] == 0


def test_search_limits(client):
    for i in range(12):
        SkinFactory(name=f"Tulip {i}")
    assert len(get(client, "skins/search/?q=tulip&limit=50").json()["data"]["skins"]) == 10
    assert len(get(client, "skins/search/?q=tulip&limit=abc").json()["data"]["skins"]) == 5


def test_search_needs_a_query(client):
    response = get(client, "skins/search/?q=%20")
    assert (response.status_code, response.json()["error"]) == (400, "missing_query")


def test_slow_search(client, monkeypatch):
    def slow(query, limit):
        raise OperationalError("canceling statement due to statement timeout")

    monkeypatch.setattr(bot, "best_matches", slow)
    response = get(client, "skins/search/?q=tulip")
    assert (response.status_code, response.json()["error"]) == (503, "search_timeout")


def test_skin_by_id(client):
    skin = SkinFactory(name="Reality.exe", creator="Somepoop")
    assert get(client, f"skins/{skin.id}/").json()["data"]["skin"]["name"] == "Reality.exe"
    assert get(client, f"skins/{skin.id + 999}/").json()["error"] == "skin_not_found"


def test_random(client):
    assert get(client, "skins/random/").json()["error"] == "skin_not_found"
    skin = SkinFactory()
    assert get(client, "skins/random/").json()["data"]["skin"]["id"] == skin.id


# --- players -------------------------------------------------------------------------


def entry(status, username="The Saucy Tulip"):
    return {"requested": username, "username": username, "status": status, "level": 41}


def test_player_with_skin_count(client, monkeypatch):
    monkeypatch.setattr(api_selectors, "player_entries", lambda names, build: [entry("found")])
    SkinFactory(creator="the saucy tulip")
    SkinFactory(creator="The Saucy Tulip")

    data = get(client, "players/the%20saucy%20tulip/").json()["data"]
    assert (data["level"], data["skins"]) == (41, 2)


def test_unknown_player(client, monkeypatch):
    monkeypatch.setattr(api_selectors, "player_entries", lambda names, build: [entry("not_found", "nobody")])
    response = get(client, "players/nobody/")
    assert (response.status_code, response.json()["error"]) == (404, "player_not_found")


def test_creator_with_no_replays_still_shows(client, monkeypatch):
    """Skin makers who never showed up in replays (e.g. Somepoop) still get a card."""
    monkeypatch.setattr(api_selectors, "player_entries", lambda names, build: [entry("not_found", "Somepoop")])
    SkinFactory(creator="Somepoop")
    assert get(client, "players/Somepoop/").json()["data"]["skins"] == 1


def test_replays_down(client, monkeypatch):
    monkeypatch.setattr(api_selectors, "player_entries", lambda names, build: [entry("unavailable")])
    assert get(client, "players/tulip/").status_code == 503


# --- maps ----------------------------------------------------------------------------

DECODED = {
    "m": {"n": "Simple 1v1", "a": "Chaz", "mo": "b", "date": "2020-01-01", "dbid": 42, "vu": 10, "vd": 2},
    "physics": {"shapes": [1, 2, 3], "bodies": [1], "joints": []},
    "spawns": [1, 2],
    "capZones": [],
}


def post_map(client, body):
    return client.post("/api/bot/maps/decode/", json.dumps(body), content_type="application/json", **AUTH)


def test_map_summary(client, monkeypatch):
    monkeypatch.setattr(bot, "decode_map_configured", lambda code: DecodeResult(data=DECODED))
    data = post_map(client, {"code": "ILAMJAhBFBjBzA..."}).json()["data"]
    assert data["map"] == {
        "name": "Simple 1v1", "author": "Chaz", "mode": "b", "date": "2020-01-01", "map_id": 42,
        "upvotes": 10, "downvotes": 2, "shapes": 3, "bodies": 1, "joints": 0, "spawns": 2,
        "cap_zones": 0,
    }


def test_map_rejected_explains(client, monkeypatch):
    monkeypatch.setattr(
        bot, "decode_map_configured",
        lambda code: DecodeResult(error=DecodeError.REJECTED, detail="not a map string"),
    )
    response = post_map(client, {"code": "hello"})
    assert response.status_code == 422
    assert response.json() == {"ok": False, "error": "map_rejected", "detail": "not a map string"}


def test_map_needs_a_code(client):
    assert post_map(client, {}).json()["error"] == "missing_code"
    assert post_map(client, {"code": "x" * (bot.MAX_MAP_CODE + 1)}).json()["error"] == "missing_code"


def test_odd_decoder_output_doesnt_crash():
    assert bot.map_summary(["not", "a", "map"])["shapes"] == 0
    assert bot.map_summary({"m": "weird"})["name"] is None
