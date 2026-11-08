"""Player profiles (players/): the replay API client, the charts, the public
page for players with and without a Bonkverse account, privacy switches,
and the Replays tab on My Profile."""

import pytest
import requests
from django.urls import reverse

from integrations.replays import PlayerError, get_player
from players import charts
from players.models import ProfileVisibility
from tests.factories import SkinFactory, UserFactory

REPLAYS = "http://replays.test"


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
            "last": {"cycle": 6, "id": "344124", "day": "2026-11-08"},
        },
        "days": [
            {"day": "2025-03-05", "games": 20, "level": 40},
            {"day": "2026-01-10", "games": 60, "level": 50},
            {"day": "2026-11-08", "games": 40, "level": 54},
        ],
        "weekdays": [{"weekday": 3, "games": 20}, {"weekday": 7, "games": 100}],
        "hours": {"sample": 40, "hours": [{"hour": 3, "games": 40}]},
        "modes": [{"mode": "ard", "games": 90}, {"mode": "b", "games": 30}],
        "maps": [{"mapid": "777", "name": "Snipers Spot", "games": 50}],
        "played_with": [{"username": "Friend One", "games": 30, "same_team": 12}],
        "teammates": [{"username": "Friend One", "games": 12}],
        "recent": [
            {
                "id": "344124",
                "cycle": 6,
                "mapid": "777",
                "mapname": "Snipers Spot",
                "mode": "ard",
                "fetched_at": "2026-11-08T03:00:00Z",
                "estimated_day": None,
                "players": [{"username": username}, {"username": "Friend One"}],
            }
        ],
    }


def mock_player(mocked_http, username, *, status=200, body=None):
    from urllib.parse import quote

    mocked_http.get(
        f"{REPLAYS}/api/player/{quote(username, safe='')}",
        json=body if body is not None else profile_json(username),
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


# ── Charts ─────────────────────────────────────────────────────


def test_charts_shape_the_profile():
    page = charts.build(profile_json(), REPLAYS)
    assert page["level_chart"]["low"] == 40 and page["level_chart"]["high"] == 54
    assert len(page["level_chart"]["points"].split()) == 3
    assert [w["games"] for w in page["weekdays"]] == [0, 0, 20, 0, 0, 0, 100]
    assert page["weekdays"][6]["bar"] == 100
    assert len(page["hours"]["bars"]) == 24
    assert page["modes"][0] == {"code": "ard", "label": "Death Arrows", "games": 90, "bar": 75.0}
    assert page["recent"][0]["url"] == f"{REPLAYS}/watch/6/344124"
    assert page["played_with"][0]["profile_path"] == "/player/Friend%20One/"
    assert page["all_replays_url"] == f"{REPLAYS}/search?with=Saucy+Tulip"


def test_level_chart_needs_two_days():
    assert charts.level_chart([{"day": "2026-01-01", "level": 3}]) is None


def test_no_hours_without_live_replays():
    assert charts.hour_bars({"sample": 0, "hours": []}) is None


# ── Public profile ─────────────────────────────────────────────


@pytest.mark.django_db
def test_player_without_account_gets_a_page(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    response = client.get(reverse("player_profile", args=["Saucy Tulip"]))
    html = response.content.decode()
    assert response.status_code == 200
    assert "profile built from replays" in html
    assert "Level history" in html and "Plays with most" in html
    assert "Sign in with your bonk.io account" in html


@pytest.mark.django_db
def test_unknown_player_is_404(client, mocked_http):
    mock_player(mocked_http, "nobody", status=404, body={"error": "No replays"})
    response = client.get(reverse("player_profile", args=["nobody"]))
    assert response.status_code == 404
    assert "No profile for" in response.content.decode()


@pytest.mark.django_db
def test_account_without_replays_still_has_a_page(client, mocked_http):
    UserFactory(username="newbie")
    SkinFactory(creator="newbie", name="First Skin")
    mock_player(mocked_http, "newbie", status=404, body={"error": "No replays"})
    html = client.get(reverse("player_profile", args=["newbie"])).content.decode()
    assert "First Skin" in html
    assert "No replays found" in html


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
    client.get(reverse("player_profile", args=["saucy tulip"]))
    assert len(mocked_http.calls) == 1


@pytest.mark.django_db
def test_hidden_sections_are_hidden_from_visitors(client, mocked_http):
    owner = UserFactory(username="Saucy Tulip")
    SkinFactory(creator="Saucy Tulip", name="Secret Skin")
    ProfileVisibility.objects.create(user=owner, play_partners=False, skins=False)
    mock_player(mocked_http, "Saucy Tulip")

    html = client.get(reverse("player_profile", args=["Saucy Tulip"])).content.decode()
    assert "Plays with most" not in html
    assert "Friend One" not in html
    assert "Secret Skin" not in html
    assert "Level history" in html
    assert "keeps some of their profile private" in html


@pytest.mark.django_db
def test_owner_sees_everything_and_what_is_hidden(client, mocked_http):
    owner = UserFactory(username="Saucy Tulip")
    ProfileVisibility.objects.create(user=owner, play_partners=False)
    mock_player(mocked_http, "Saucy Tulip")
    client.force_login(owner)

    html = client.get(reverse("player_profile", args=["Saucy Tulip"])).content.decode()
    assert "Plays with most" in html
    assert "Only you can see: Play partners" in html


@pytest.mark.django_db
def test_player_names_are_escaped(client, mocked_http):
    name = "<img src=x onerror=alert(1)>"
    mock_player(mocked_http, name)
    html = client.get(reverse("player_profile", args=[name])).content.decode()
    assert "<img src=x" not in html
    assert "&lt;img src=x" in html


# ── Settings ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_settings_need_login(client):
    response = client.get(reverse("profile_settings"))
    assert response.status_code == 302


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


# ── My Profile ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_my_profile_has_a_replays_tab_that_loads_later(logged_in_client, mocked_http):
    html = logged_in_client.get(reverse("my_profile")).content.decode()
    assert 'data-tab="replays"' in html
    assert len(mocked_http.calls) == 0  # the page itself never waits on the replay site


@pytest.mark.django_db
def test_my_replay_stats_partial(logged_in_client, user, mocked_http):
    mock_player(mocked_http, user.username)
    ProfileVisibility.objects.create(user=user, activity=False)
    html = logged_in_client.get(reverse("my_replay_stats_partial")).content.decode()
    assert "Activity" in html  # the owner sees hidden sections too
    assert "<html" not in html


def test_months_include_quiet_months():
    bars = charts.monthly_games(
        [
            {"day": "2025-11-02", "games": 4, "level": 1},
            {"day": "2026-02-10", "games": 2, "level": 2},
        ]
    )
    assert [(b["label"].month, b["games"]) for b in bars] == [(11, 4), (12, 0), (1, 0), (2, 2)]
