"""Usernames like "." and "..": browsers read them as folders in a path
(/player/../ is /), so their profile URLs carry a "~" in front
(players/converters.py), and the replay API gets them as ?name=."""

from urllib.parse import unquote

import pytest
from django.urls import resolve, reverse

from integrations.replays import get_player, get_player_map
from players import charts, converters
from tests.test_players import REPLAYS, map_json, profile_json


@pytest.mark.parametrize(
    "name,url",
    [
        (".", "/player/~./"),
        ("..", "/player/~../"),
        ("~..", "/player/~~../"),
        ("~.", "/player/~~./"),
        ("...", "/player/.../"),
        ("a.b", "/player/a.b/"),
        ("~x", "/player/~x/"),
        ("Saucy Tulip", "/player/Saucy%20Tulip/"),
    ],
)
def test_profile_urls_round_trip(name, url):
    assert reverse("player_profile", args=[name]) == url
    assert charts.profile_path(name) == url
    assert resolve(unquote(url)).kwargs["username"] == name


def test_tab_urls_escape_too():
    assert reverse("player_level", args=[".."]) == "/player/~../level/"
    assert charts.profile_path("..", "level") == "/player/~../level/"


@pytest.mark.parametrize("name", [".", "..", "~.", "~~..", "...", "x", "~"])
def test_converter_is_reversible(name):
    assert converters.from_url(converters.to_url(name)) == name


def test_replay_api_gets_dot_names_in_the_query(mocked_http):
    mocked_http.get(f"{REPLAYS}/api/player?name=..", json=profile_json(".."))
    mocked_http.get(f"{REPLAYS}/api/player/map/777?name=.", json=map_json())
    assert get_player(REPLAYS, "..").error is None
    assert get_player_map(REPLAYS, ".", "777").error is None
    assert mocked_http.calls[0].request.url == f"{REPLAYS}/api/player?name=.."


def test_other_names_stay_in_the_path(mocked_http):
    mocked_http.get(f"{REPLAYS}/api/player/...", json=profile_json("..."))
    assert get_player(REPLAYS, "...").error is None


@pytest.mark.django_db
def test_dot_name_profile_page(client, mocked_http):
    mocked_http.get(f"{REPLAYS}/api/player?name=..", json=profile_json(".."))
    response = client.get("/player/~../")
    assert response.status_code == 200
    assert response.context["username"] == ".."
    assert 'class="pv-tab" href="/player/~../"' in response.content.decode()
