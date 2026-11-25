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


def test_heatmap_labels_the_week_each_month_starts_in():
    """Design review: month names across the top of the year grid."""
    hm = charts.heatmap(profile_json()["days"], date(2026, 11, 8))
    newest = hm["newest_first"]
    # Nov 1 2026 is a Sunday: the week of Oct 26 carries "Nov".
    assert newest[1]["start"] == date(2026, 10, 26) and newest[1]["month"] == date(2026, 11, 1)
    assert newest[0]["month"] is None
    labelled = [w["month"] for w in hm["weeks"] if w["month"]]
    assert len(labelled) in (12, 13) and len({(d.year, d.month) for d in labelled}) == len(labelled)


@pytest.mark.django_db
def test_activity_year_grid_has_labels_and_a_day_readout(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    html = client.get(reverse("players:player_activity", args=["Saucy Tulip"])).content.decode()
    assert 'class="pv-heat__days' in html and "<span>Wed</span>" in html
    assert 'class="pv-heat__months' in html and "data-heat-readout" in html
    assert 'data-day-label="' in html


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


def test_mode_bars_are_sorted_with_counts():
    """A sorted bar list replaces the donut (design review)."""
    modes = [{"mode": "b", "games": 30}, {"mode": "ard", "games": 90}, {"mode": "v", "games": 0}]
    bars = charts.mode_bars(modes)
    assert [b["label"] for b in bars] == ["Death Arrows", "Classic"]
    assert [b["share"] for b in bars] == [75, 25]
    assert [b["bar"] for b in bars] == [100, 33.3]
    tiny = charts.mode_bars([{"mode": "ard", "games": 999}, {"mode": "b", "games": 1}])
    assert tiny[1]["share_label"] == "<1"


def test_sparkline_dashes_long_gaps_where_the_level_rose():
    days = [
        {"day": "2026-01-01", "games": 5, "level": 10},
        {"day": "2026-01-02", "games": 5, "level": 11},
        {"day": "2026-03-01", "games": 5, "level": 20},  # weeks away, then 9 levels up
        {"day": "2026-03-02", "games": 5, "level": 20},
    ]
    line = charts.sparkline(days)
    assert line["gaps"].count("M") == 1
    assert line["line"].count("M") == 2
    steady = charts.sparkline(days[:2])
    assert steady["gaps"] == ""


def test_one_kind_of_room_is_said_not_drawn():
    rooms = charts.room_split({"1v1": 40, "ffa": 0, "teams": 0, "solo": 0})
    assert rooms["only"] == "1v1"
    assert charts.room_split(profile_json()["rooms"])["only"] is None


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
    response = client.get(reverse(f"players:{tab}", args=["Saucy Tulip"]))
    html = response.content.decode()
    assert response.status_code == 200
    assert "Profile built from replays" in html
    assert 'aria-current="page"' in html


@pytest.mark.django_db
def test_overview_cards(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    html = client.get(reverse("players:player_profile", args=["Saucy Tulip"])).content.decode()
    for text in ["Level explorer", "Main mode", "Home map", "Plays with most", "Milestones"]:
        assert text in html
    assert "Sign in with your bonk.io account" in html
    # The level card shows the level, so the header doesn't repeat it.
    assert "Level 54</span>" not in html
    assert "Level 100 in about" in html


@pytest.mark.django_db
def test_other_tabs_keep_the_level_in_the_header(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    html = client.get(reverse("players:player_people", args=["Saucy Tulip"])).content.decode()
    assert "Level 54</span>" in html


@pytest.mark.django_db
@pytest.mark.parametrize(
    "tab,title",
    [
        ("player_profile", "Saucy Tulip · Bonkverse"),
        ("player_activity", "Saucy Tulip · Activity · Bonkverse"),
        ("player_level", "Saucy Tulip · Level · Bonkverse"),
        ("player_maps", "Saucy Tulip · Maps &amp; modes · Bonkverse"),
        ("player_people", "Saucy Tulip · People · Bonkverse"),
    ],
)
def test_each_tab_has_its_own_title(client, mocked_http, tab, title):
    mock_player(mocked_http, "Saucy Tulip")
    mock_map(mocked_http, "Saucy Tulip")
    html = client.get(reverse(f"players:{tab}", args=["Saucy Tulip"])).content.decode()
    assert f"<title>{title}</title>" in html


@pytest.mark.django_db
def test_profile_is_on_bv_components(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    html = client.get(reverse("players:player_profile", args=["Saucy Tulip"])).content.decode()
    assert 'class="content site-page"' in html
    assert "css/player_profile.css" not in html and "players/css/profile.css" in html


@pytest.mark.django_db
def test_maps_tab_shows_the_chosen_map(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    mock_map(mocked_http, "Saucy Tulip", "888")
    html = client.get(
        reverse("players:player_maps", args=["Saucy Tulip"]) + "?map=888"
    ).content.decode()
    assert "Map Buddy" in html
    assert f"{REPLAYS}/api/map/888/thumbnail.svg" in html


@pytest.mark.django_db
def test_maps_tab_survives_a_map_outage(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    mock_map(mocked_http, "Saucy Tulip", status=503)
    html = client.get(reverse("players:player_maps", args=["Saucy Tulip"])).content.decode()
    assert "can't be loaded right now" in html


@pytest.mark.django_db
def test_people_tab_is_one_list_with_a_switch(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    url = reverse("players:player_people", args=["Saucy Tulip"])
    html = client.get(url).content.decode()
    assert "Plays with" in html and "Teams with" in html and "Plays against" in html
    assert 'href="?list=with" aria-current="page"' in html
    assert "Friend One" in html and "Rival Two" not in html
    against = client.get(url + "?list=against").content.decode()
    assert "Rival Two" in against and 'href="?list=against" aria-current="page"' in against
    assert "Friend One" in client.get(url + "?list=nonsense").content.decode()


@pytest.mark.django_db
def test_activity_and_level_hand_data_to_their_scripts(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    activity = client.get(reverse("players:player_activity", args=["Saucy Tulip"])).content.decode()
    level = client.get(reverse("players:player_level", args=["Saucy Tulip"])).content.decode()
    assert 'id="activity-data"' in activity and "js/player_activity.js" in activity
    assert 'id="level-data"' in level and "js/player_level.js" in level
    assert "1 h 36 m" in activity


@pytest.mark.django_db
def test_unknown_player_is_404(client, mocked_http):
    mock_player(mocked_http, "nobody", status=404, body={"error": "No replays"})
    response = client.get(reverse("players:player_profile", args=["nobody"]))
    assert response.status_code == 404
    assert "No profile for" in response.content.decode()


@pytest.mark.django_db
def test_account_without_replays_gets_overview_and_skins_only(client, mocked_http):
    UserFactory(username="newbie")
    SkinFactory(creator="newbie", name="First Skin")
    mock_player(mocked_http, "newbie", status=404, body={"error": "No replays"})
    html = client.get(reverse("players:player_profile", args=["newbie"])).content.decode()
    assert "No replays found" in html
    assert reverse("players:player_skins", args=["newbie"]) in html
    assert reverse("players:player_activity", args=["newbie"]) not in html
    skins = client.get(reverse("players:player_skins", args=["newbie"])).content.decode()
    assert "First Skin" in skins


@pytest.mark.django_db
def test_replay_outage_shows_a_notice(client, mocked_http):
    UserFactory(username="someone")
    mock_player(mocked_http, "someone", status=503, body={"error": "down"})
    response = client.get(reverse("players:player_profile", args=["someone"]))
    assert response.status_code == 200
    assert "can't be loaded right now" in response.content.decode()


@pytest.mark.django_db
def test_profile_is_cached(client, mocked_http):
    mock_player(mocked_http, "Saucy Tulip")
    client.get(reverse("players:player_profile", args=["Saucy Tulip"]))
    client.get(reverse("players:player_people", args=["saucy tulip"]))
    assert len(mocked_http.calls) == 1


@pytest.mark.django_db
def test_player_names_are_escaped(client, mocked_http):
    name = "<img src=x onerror=alert(1)>"
    mock_player(mocked_http, name)
    html = client.get(reverse("players:player_profile", args=[name])).content.decode()
    assert "<img src=x" not in html
    assert "&lt;img src=x" in html


# ── Privacy ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_hidden_sections_lose_their_tab_and_card(client, mocked_http):
    owner = UserFactory(username="Saucy Tulip")
    ProfileVisibility.objects.create(user=owner, play_partners=False, activity=False)
    mock_player(mocked_http, "Saucy Tulip")

    html = client.get(reverse("players:player_profile", args=["Saucy Tulip"])).content.decode()
    assert reverse("players:player_people", args=["Saucy Tulip"]) not in html
    assert "Plays with most" not in html
    assert "Friend One" not in html
    assert "Level explorer" in html

    hidden = client.get(reverse("players:player_people", args=["Saucy Tulip"])).content.decode()
    assert "keeps this part of their profile private" in hidden
    assert "Friend One" not in hidden
    assert "Back after" not in html  # activity milestones go too


# Letters that some case rule turns into an English one, written in place of
# it: Python's lower() makes the Kelvin sign "k" (the profile cache key and
# the player lookup used it), the replay site's database lower() makes both
# that and the dotted capital I English letters, while the account lookup
# (Postgres UPPER()) matched neither. So the profile and friend list were
# found, the account with the privacy switches wasn't, and every hidden
# section was shown to anyone (audit, 2026-11-25).
KELVIN_SIGN = "\u212a"
DOTTED_CAPITAL_I = "\u0130"
HIDDEN_TABS = ["player_people", "player_friends", "player_level", "player_activity", "player_maps"]


def _member_who_hid_everything(name):
    """A member with every section hidden, a bonk.io friend, and replays."""
    from players.models import BonkPlayer, Friendship

    owner = UserFactory(username=name)
    ProfileVisibility.objects.create(
        user=owner,
        level_history=False,
        activity=False,
        maps_and_modes=False,
        play_partners=False,
        friends=False,
        skins=False,
        favorites=False,
    )
    me = BonkPlayer.objects.create(bonk_id=4242, username=name)
    pal = BonkPlayer.objects.create(bonk_id=4343, username="Secret Pal")
    Friendship.objects.create(player_low=me, player_high=pal)
    return owner


def _assert_nothing_hidden_is_shown(client, spelling):
    for tab in ["player_profile", *HIDDEN_TABS]:
        html = client.get(reverse(f"players:{tab}", args=[spelling])).content.decode()
        for private in ("Friend One", "Rival Two", "Secret Pal", "Level explorer", "Snipers Spot"):
            assert private not in html, f"{tab} shows {private!r} under {spelling!r}"
    calculator = client.get(reverse("players:xp_calculator_player"), {"name": spelling})
    assert calculator.json()["ok"] is False


@pytest.mark.django_db
def test_lookalike_spelling_in_the_url_cant_read_a_cached_private_profile(client, mocked_http):
    _member_who_hid_everything("Fook")
    mock_player(mocked_http, "Fook")
    spelling = "Foo" + KELVIN_SIGN
    mock_player(mocked_http, spelling, status=404, body={"error": "No replays"})

    # Anyone's visit caches the replay profile, hidden sections or not.
    hidden = client.get(reverse("players:player_people", args=["Fook"])).content.decode()
    assert "keeps this part of their profile private" in hidden

    _assert_nothing_hidden_is_shown(client, spelling)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name,spelling",
    [("Fook", "Foo" + KELVIN_SIGN), ("Fooi", "Foo" + DOTTED_CAPITAL_I)],
)
def test_lookalike_spelling_the_replay_site_accepts_cant_read_a_private_profile(
    client, mocked_http, name, spelling
):
    """The replay site matches with its database's lower(), so it answers a
    look-alike spelling with the real player's profile."""
    _member_who_hid_everything(name)
    mock_player(mocked_http, spelling, body=profile_json(name))

    _assert_nothing_hidden_is_shown(client, spelling)


@pytest.mark.django_db
def test_a_replay_profile_that_doesnt_say_whose_it_is_is_refused(client, mocked_http):
    """The check compares the profile's `username` with the name asked for.
    An answer without one must not pass it by default."""
    _member_who_hid_everything("Fooi")
    spelling = "Foo" + DOTTED_CAPITAL_I
    nameless = {k: v for k, v in profile_json("Fooi").items() if k != "username"}
    mock_player(mocked_http, spelling, body=nameless)

    _assert_nothing_hidden_is_shown(client, spelling)


@pytest.mark.django_db
def test_a_lookalike_player_doesnt_stand_in_for_or_hide_the_real_one(client, mocked_http):
    """Both spellings lower() to the same text, and the newer row used to win
    the shared key."""
    from players.models import BonkPlayer
    from skins.selectors import bonk_players_named

    real = BonkPlayer.objects.create(bonk_id=1, username="Fook")
    fake = BonkPlayer.objects.create(bonk_id=2, username="Foo" + KELVIN_SIGN)

    found = bonk_players_named(["fOOK", fake.username])

    assert found == {"fook": real, "foo" + KELVIN_SIGN: fake}


@pytest.mark.django_db
def test_other_capitalization_still_opens_the_profile_with_its_privacy(client, mocked_http):
    owner = _member_who_hid_everything("Fook")
    mock_player(mocked_http, "fOOK", body=profile_json("Fook"))

    hidden = client.get(reverse("players:player_people", args=["fOOK"])).content.decode()
    assert "keeps this part of their profile private" in hidden

    client.force_login(owner)
    mine = client.get(reverse("players:player_people", args=["fOOK"])).content.decode()
    assert "Friend One" in mine


@pytest.mark.django_db
def test_owner_sees_everything_and_what_is_hidden(client, mocked_http):
    owner = UserFactory(username="Saucy Tulip")
    ProfileVisibility.objects.create(user=owner, play_partners=False)
    mock_player(mocked_http, "Saucy Tulip")
    client.force_login(owner)

    html = client.get(reverse("players:player_people", args=["Saucy Tulip"])).content.decode()
    assert "Friend One" in html
    assert "Only you can see: People" in html
    assert "Profile settings" in html


@pytest.mark.django_db
def test_hidden_skins_and_favorites_drop_the_skins_tab(client, mocked_http):
    owner = UserFactory(username="Saucy Tulip")
    ProfileVisibility.objects.create(user=owner, skins=False, favorites=False)
    mock_player(mocked_http, "Saucy Tulip")
    html = client.get(reverse("players:player_profile", args=["Saucy Tulip"])).content.decode()
    assert reverse("players:player_skins", args=["Saucy Tulip"]) not in html


@pytest.mark.django_db
def test_skins_tab_sorts_and_switches_to_favorites(client, mocked_http):
    owner = UserFactory(username="maker")
    SkinFactory(creator="maker", name="Alpha", upvotes=1)
    SkinFactory(creator="maker", name="Beta", upvotes=9)
    fav = SkinFactory(creator="someone else", name="Liked One")
    fav.favorited_by.add(owner)
    mock_player(mocked_http, "maker", status=404, body={"error": "No replays"})

    top = client.get(reverse("players:player_skins", args=["maker"])).content.decode()
    assert top.index("Beta") < top.index("Alpha")
    az = client.get(reverse("players:player_skins", args=["maker"]) + "?sort=az").content.decode()
    assert az.index("Alpha") < az.index("Beta")
    favs = client.get(
        reverse("players:player_skins", args=["maker"]) + "?view=favorites"
    ).content.decode()
    assert "Liked One" in favs and "Beta" not in favs


# ── Settings and My Profile ────────────────────────────────────


@pytest.mark.django_db
def test_settings_need_login(client):
    assert client.get(reverse("players:profile_settings")).status_code == 302


@pytest.mark.django_db
def test_settings_default_to_public(logged_in_client):
    html = logged_in_client.get(reverse("players:profile_settings")).content.decode()
    assert html.count("checked") == len(ProfileVisibility.SECTIONS)


@pytest.mark.django_db
def test_saving_settings(logged_in_client, user):
    response = logged_in_client.post(
        reverse("players:profile_settings"), {"level_history": "on", "skins": "on"}
    )
    assert response.status_code == 302
    saved = ProfileVisibility.objects.get(user=user)
    assert saved.level_history and saved.skins
    assert not saved.activity and not saved.play_partners and not saved.favorites


@pytest.mark.django_db
def test_switches_save_as_they_flip(logged_in_client, user):
    """profile_settings.js posts the form on every flip and wants JSON back."""
    response = logged_in_client.post(
        reverse("players:profile_settings"), {"skins": "on"}, HTTP_ACCEPT="application/json"
    )
    assert response.json() == {"ok": True}
    saved = ProfileVisibility.objects.get(user=user)
    assert saved.skins and not saved.level_history


@pytest.mark.django_db
def test_my_profile_is_now_your_profiles_skins_tab(logged_in_client, user):
    """One profile (design review): the old /my-profile/ address, still in
    the account menu and old links, goes to your profile's Skins tab."""
    response = logged_in_client.get(reverse("skins:my_profile"))
    assert response.status_code == 302
    assert response.url == reverse("players:player_skins", args=[user.username])


def test_my_profile_asks_signed_out_visitors_to_log_in(client):
    response = client.get(reverse("skins:my_profile"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))
