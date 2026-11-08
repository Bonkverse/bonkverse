"""Player profiles (players/): the replay API client, the chart shaping, every
profile tab for players with and without a Bonkverse account, privacy
switches per tab, and the links from My Profile."""

from datetime import date
from urllib.parse import quote

import pytest
import requests
from django.urls import reverse

from integrations.replays import PlayerError, get_player, get_player_map
from players import charts
from players.models import ProfileVisibility
from tests.factories import SkinFactory, UserFactory

REPLAYS = "http://replays.test"
TABS = ["player_profile", "player_activity", "player_level", "player_maps", "player_people"]


@pytest.fixture(autouse=True)
def _replays_url(settings):
    settings.BONKVERSE_REPLAYS_URL = REPLAYS


def profile_json(username="Saucy Tulip"):
    return {
        "username": username,
        "summary": {
            "username": username,
            "games": 120,
            "current_level": 54,
            "peak_level": 54,
            "active_days": 3,
            "cycles": 2,
            "team_games": 40,
            "first": {"cycle": 5, "id": "10", "day": "2025-03-05"},
            "last": {"cycle": 6, "id": "344124", "day": "2026-11-07"},
        },
        "days": [
            {"day": "2025-03-05", "games": 20, "level": 40},
            {"day": "2026-01-10", "games": 60, "level": 50},
            {"day": "2026-11-06", "games": 20, "level": 53},
            {"day": "2026-11-07", "games": 20, "level": 54},
        ],
        "weekdays": [],
        "hours": {"sample": 40, "hours": []},
        "live_hours": [{"t": "2026-11-07T03:00:00Z", "games": 40}],
        "sessions": {"count": 3, "median_minutes": 96, "longest_minutes": 410},
        "modes": [{"mode": "ard", "games": 90}, {"mode": "b", "games": 30}],
        "rooms": {
            "1v1": 60,
            "ffa": 30,
            "teams": 30,
            "solo": 0,
            "quickplay": 12,
            "median_players": 2,
            "distinct_maps": 7,
        },
        "maps": [
            {"mapid": "777", "name": "Snipers Spot", "games": 50, "last_day": "2026-11-07"},
            {"mapid": "888", "name": "Volleyball", "games": 10, "last_day": "2026-11-01"},
        ],
        "level_ups": [
            {"level": 50, "cycle": 6, "id": "200", "day": "2026-01-10", "at": None, "replays": 70},
            {
                "level": 54,
                "cycle": 6,
                "id": "344000",
                "day": "2026-11-07",
                "at": "2026-11-07T03:10:00Z",
                "replays": 30,
            },
        ],
        "played_with": [{"username": "Friend One", "games": 30, "same_team": 12}],
        "teammates": [{"username": "Friend One", "games": 12}],
        "rivals": [{"username": "Rival Two", "games": 9}],
        "recent": [],
    }


def map_json(mapid="777"):
    return {
        "mapid": mapid,
        "name": "Snipers Spot",
        "games": 50,
        "first_day": "2025-03-05",
        "last_day": "2026-11-07",
        "rooms": {"1v1": 40, "ffa": 10, "teams": 0, "solo": 0},
        "modes": {"ard": 45, "b": 5},
        "played_with": [{"username": "Map Buddy", "games": 20, "same_team": 0}],
    }


def mock_player(mocked_http, username, *, status=200, body=None):
    mocked_http.get(
        f"{REPLAYS}/api/player/{quote(username, safe='')}",
        json=body if body is not None else profile_json(username),
        status=status,
    )


def mock_map(mocked_http, username, mapid="777", *, status=200):
    mocked_http.get(
        f"{REPLAYS}/api/player/{quote(username, safe='')}/map/{mapid}",
        json=map_json(mapid) if status == 200 else {"error": "x"},
        status=status,
    )


# ── Client ─────────────────────────────────────────────────────


def test_client_returns_the_profile(mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    result = get_player(REPLAYS, "Saucy Tulip")
    assert result.error is None
    assert result.data["summary"]["games"] == 120


def test_client_encodes_the_name(mocked_http):
    mock_player(mocked_http, "a/b?c")
    assert get_player(REPLAYS, "a/b?c").error is None
    assert mocked_http.calls[0].request.url == f"{REPLAYS}/api/player/a%2Fb%3Fc"


def test_client_not_found(mocked_http):
    mock_player(mocked_http, "nobody", status=404, body={"error": "No replays"})
    assert get_player(REPLAYS, "nobody").error == PlayerError.NOT_FOUND


@pytest.mark.parametrize(
    "kwargs",
    [
        {"body": requests.ConnectionError("down")},
        {"status": 500, "json": {"error": "x"}},
        {"status": 200, "body": "<html>"},
        {"status": 200, "json": {"unexpected": True}},
    ],
)
def test_client_unavailable(mocked_http, kwargs):
    mocked_http.get(f"{REPLAYS}/api/player/x", **kwargs)
    assert get_player(REPLAYS, "x").error == PlayerError.UNAVAILABLE


def test_client_not_configured():
    assert get_player("", "x").error == PlayerError.NOT_CONFIGURED


def test_map_client(mocked_http):
    mock_map(mocked_http, "Saucy Tulip")
    assert get_player_map(REPLAYS, "Saucy Tulip", "777").data["games"] == 50
    assert get_player_map(REPLAYS, "Saucy Tulip", "../x").error == PlayerError.NOT_FOUND


# ── Charts ─────────────────────────────────────────────────────


def test_sparkline_needs_two_days():
    assert charts.sparkline([{"day": "2026-01-01", "games": 1, "level": 3}]) is None
    line = charts.sparkline(profile_json()["days"])
    assert line["low"] == 40 and line["high"] == 54 and line["gained"] == 14


def test_heatmap_covers_a_year_newest_first():
    hm = charts.heatmap(profile_json()["days"], date(2026, 11, 8))
    assert len(hm["weeks"]) == 53 and all(len(w["cells"]) == 7 for w in hm["weeks"])
    assert hm["newest_first"][0]["start"] == date(2026, 11, 2)
    assert hm["days_played"] == 3  # 2025-03-05 is more than a year back


def test_streaks():
    s = charts.streaks(profile_json()["days"], date(2026, 11, 8))
    assert s["current"] == 2 and s["longest"] == 2


def test_milestones_tell_the_story():
    found = [m["what"] for m in charts.milestones(profile_json(), charts.ReplayLinks(REPLAYS))]
    assert "First replay in the archive" in found
    assert "100th replay" in found
    assert "Reached level 50" in found
    assert any(w.startswith("Back after") for w in found)


def test_milestones_respect_privacy():
    found = charts.milestones(
        profile_json(), charts.ReplayLinks(REPLAYS), show_level=False, show_activity=True
    )
    assert not any("level" in m["what"] for m in found)


def test_mode_ring_has_a_slice_per_mode():
    ring = charts.mode_ring(profile_json()["modes"])
    assert [s["label"] for s in ring["slices"]] == ["Death Arrows", "Classic"]
    assert [s["share"] for s in ring["slices"]] == [75, 25]
    assert all(s["d"].startswith("M ") for s in ring["slices"])


def test_room_split_skips_empty_kinds():
    rooms = charts.room_split(profile_json()["rooms"])
    assert [p["key"] for p in rooms["parts"]] == ["1v1", "ffa", "teams"]
    assert rooms["quickplay_share"] == 10.0


def test_level_ups_newest_first_with_days_between():
    rows = charts.level_ups(profile_json(), charts.ReplayLinks(REPLAYS))
    assert [r["level"] for r in rows] == [54, 50]
    assert rows[1]["days"] == (date(2026, 1, 10) - date(2025, 3, 5)).days


def test_minutes_label():
    assert charts.minutes_label(96) == "1 h 36 m"
    assert charts.minutes_label(45) == "45 min"
    assert charts.minutes_label(None) is None


# ── Pages ──────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("tab", TABS)
def test_every_tab_renders_for_a_player_without_an_account(client, mocked_http, tab):
    mock_player(mocked_http, "Saucy Tulip")
    mock_map(mocked_http, "Saucy Tulip")
    response = client.get(reverse(tab, args=["Saucy Tulip"]))
    html = response.content.decode()
    assert response.status_code == 200
    assert "Profile built from replays" in html
    assert 'aria-current="page"' in html


@pytest.mark.django_db
def test_overview_cards(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    html = client.get(reverse("player_profile", args=["Saucy Tulip"])).content.decode()
    for text in ["Level explorer", "Main mode", "Home map", "Plays with most", "Milestones"]:
        assert text in html
    assert "Sign in with your bonk.io account" in html


@pytest.mark.django_db
def test_maps_tab_shows_the_chosen_map(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    mock_map(mocked_http, "Saucy Tulip", "888")
    html = client.get(reverse("player_maps", args=["Saucy Tulip"]) + "?map=888").content.decode()
    assert "Map Buddy" in html
    assert f"{REPLAYS}/api/map/888/thumbnail.svg" in html


@pytest.mark.django_db
def test_maps_tab_survives_a_map_outage(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    mock_map(mocked_http, "Saucy Tulip", status=503)
    html = client.get(reverse("player_maps", args=["Saucy Tulip"])).content.decode()
    assert "can't be loaded right now" in html


@pytest.mark.django_db
def test_people_tab_has_three_lists(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    html = client.get(reverse("player_people", args=["Saucy Tulip"])).content.decode()
    assert "Plays with" in html and "Teams with" in html and "Plays against" in html
    assert "Rival Two" in html


@pytest.mark.django_db
def test_activity_and_level_hand_data_to_their_scripts(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    activity = client.get(reverse("player_activity", args=["Saucy Tulip"])).content.decode()
    level = client.get(reverse("player_level", args=["Saucy Tulip"])).content.decode()
    assert 'id="activity-data"' in activity and "js/player_activity.js" in activity
    assert 'id="level-data"' in level and "js/player_level.js" in level
    assert "1 h 36 m" in activity


@pytest.mark.django_db
def test_unknown_player_is_404(client, mocked_http):
    mock_player(mocked_http, "nobody", status=404, body={"error": "No replays"})
    response = client.get(reverse("player_profile", args=["nobody"]))
    assert response.status_code == 404
    assert "No profile for" in response.content.decode()


@pytest.mark.django_db
def test_account_without_replays_gets_overview_and_skins_only(client, mocked_http):
    UserFactory(username="newbie")
    SkinFactory(creator="newbie", name="First Skin")
    mock_player(mocked_http, "newbie", status=404, body={"error": "No replays"})
    html = client.get(reverse("player_profile", args=["newbie"])).content.decode()
    assert "No replays found" in html
    assert reverse("player_skins", args=["newbie"]) in html
    assert reverse("player_activity", args=["newbie"]) not in html
    skins = client.get(reverse("player_skins", args=["newbie"])).content.decode()
    assert "First Skin" in skins


@pytest.mark.django_db
def test_replay_outage_shows_a_notice(client, mocked_http):
    UserFactory(username="someone")
    mock_player(mocked_http, "someone", status=503, body={"error": "down"})
    response = client.get(reverse("player_profile", args=["someone"]))
    assert response.status_code == 200
    assert "can't be loaded right now" in response.content.decode()


@pytest.mark.django_db
def test_profile_is_cached(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    client.get(reverse("player_profile", args=["Saucy Tulip"]))
    client.get(reverse("player_people", args=["saucy tulip"]))
    assert len(mocked_http.calls) == 1


@pytest.mark.django_db
def test_player_names_are_escaped(client, mocked_http):
    name = "<img src=x onerror=alert(1)>"
    mock_player(mocked_http, name)
    html = client.get(reverse("player_profile", args=[name])).content.decode()
    assert "<img src=x" not in html
    assert "&lt;img src=x" in html


# ── Privacy ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_hidden_sections_lose_their_tab_and_card(client, mocked_http):
    owner = UserFactory(username="Saucy Tulip")
    ProfileVisibility.objects.create(user=owner, play_partners=False, activity=False)
    mock_player(mocked_http, "Saucy Tulip")

    html = client.get(reverse("player_profile", args=["Saucy Tulip"])).content.decode()
    assert reverse("player_people", args=["Saucy Tulip"]) not in html
    assert "Plays with most" not in html
    assert "Friend One" not in html
    assert "Level explorer" in html

    hidden = client.get(reverse("player_people", args=["Saucy Tulip"])).content.decode()
    assert "keeps this part of their profile private" in hidden
    assert "Friend One" not in hidden
    assert "Back after" not in html  # activity milestones go too


@pytest.mark.django_db
def test_owner_sees_everything_and_what_is_hidden(client, mocked_http):
    owner = UserFactory(username="Saucy Tulip")
    ProfileVisibility.objects.create(user=owner, play_partners=False)
    mock_player(mocked_http, "Saucy Tulip")
    client.force_login(owner)

    html = client.get(reverse("player_people", args=["Saucy Tulip"])).content.decode()
    assert "Friend One" in html
    assert "Only you can see: People" in html
    assert "Profile settings" in html


@pytest.mark.django_db
def test_hidden_skins_and_favorites_drop_the_skins_tab(client, mocked_http):
    owner = UserFactory(username="Saucy Tulip")
    ProfileVisibility.objects.create(user=owner, skins=False, favorites=False)
    mock_player(mocked_http, "Saucy Tulip")
    html = client.get(reverse("player_profile", args=["Saucy Tulip"])).content.decode()
    assert reverse("player_skins", args=["Saucy Tulip"]) not in html


@pytest.mark.django_db
def test_skins_tab_sorts_and_switches_to_favorites(client, mocked_http):
    owner = UserFactory(username="maker")
    SkinFactory(creator="maker", name="Alpha", upvotes=1)
    SkinFactory(creator="maker", name="Beta", upvotes=9)
    fav = SkinFactory(creator="someone else", name="Liked One")
    fav.favorited_by.add(owner)
    mock_player(mocked_http, "maker", status=404, body={"error": "No replays"})

    top = client.get(reverse("player_skins", args=["maker"])).content.decode()
    assert top.index("Beta") < top.index("Alpha")
    az = client.get(reverse("player_skins", args=["maker"]) + "?sort=az").content.decode()
    assert az.index("Alpha") < az.index("Beta")
    favs = client.get(reverse("player_skins", args=["maker"]) + "?view=favorites").content.decode()
    assert "Liked One" in favs and "Beta" not in favs


# ── Settings and My Profile ────────────────────────────────────


@pytest.mark.django_db
def test_settings_need_login(client):
    assert client.get(reverse("profile_settings")).status_code == 302


@pytest.mark.django_db
def test_settings_default_to_public(logged_in_client):
    html = logged_in_client.get(reverse("profile_settings")).content.decode()
    assert html.count("checked") == len(ProfileVisibility.SECTIONS)


@pytest.mark.django_db
def test_saving_settings(logged_in_client, user):
    response = logged_in_client.post(
        reverse("profile_settings"), {"level_history": "on", "skins": "on"}
    )
    assert response.status_code == 302
    saved = ProfileVisibility.objects.get(user=user)
    assert saved.level_history and saved.skins
    assert not saved.activity and not saved.play_partners and not saved.favorites


@pytest.mark.django_db
def test_my_profile_links_to_the_public_profile(logged_in_client, user, mocked_http):
    html = logged_in_client.get(reverse("my_profile")).content.decode()
    assert reverse("player_profile", args=[user.username]) in html
    assert reverse("profile_settings") in html
    assert 'data-tab="replays"' not in html
    assert len(mocked_http.calls) == 0  # My Profile never waits on the replay site
