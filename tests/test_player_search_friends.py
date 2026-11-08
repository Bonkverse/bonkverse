"""Advanced player search on the Players page (players/search.py) and the
Friends tab on profiles (players.selectors.friends)."""

import json
from datetime import date

import pytest
from django.http import QueryDict
from django.urls import reverse

from core.bonk import dbid
from players import search
from players.models import ProfileVisibility
from skins.models import BonkAccountLink, BonkPlayer, FlashFriend, FlashFriendship, Friendship
from tests.factories import UserFactory
from tests.test_players import REPLAYS, mock_player


@pytest.fixture(autouse=True)
def _replays_url(settings):
    settings.BONKVERSE_REPLAYS_URL = REPLAYS


def mock_lookup(mocked_http, results=()):
    mocked_http.get(f"{REPLAYS}/api/players/lookup", json={"results": list(results)})


def names_found(client, qs):
    """Player names on the cards of the Players page for `qs`, in order."""
    response = client.get(reverse("players_directory") + "?" + qs)
    return [c["username"] for c in response.context["cards"]]


def friends(a, b):
    low, high = sorted([a, b], key=lambda p: p.pk)
    Friendship.objects.create(player_low=low, player_high=high)


@pytest.fixture
def roster(db):
    rows = {}
    for i, name in enumerate(
        ["abc", "ab_c", "123", "x.y", " lead", "trail ", "two  sp", "      ", "ABC", "zz"]
    ):
        rows[name] = BonkPlayer.objects.create(bonk_id=1000 + i, username=name, last_friend_count=i)
    return rows


# ── Parsing ───────────────────────────────────────────────────────


def test_plain_box_trims_but_advanced_keeps_spaces():
    assert search.parse(QueryDict("q=  ab  ")).text == "ab"
    assert search.parse(QueryDict("q=  ab  &match=exact")).text == "  ab  "
    assert search.parse(QueryDict("q=%20%20&lead_space=1")).text == "  "


def test_bad_values_are_ignored_and_ranges_swapped():
    f = search.parse(QueryDict("match=evil&len_min=9&len_max=3&digits=maybe&sort=drop"))
    assert (f.match, f.len_min, f.len_max, f.kinds, f.sort) == ("contains", 3, 9, {}, "")


def test_pattern_wildcards_and_escaping():
    assert search.pattern_regex("a*b?") == "^a.*b.$"
    assert search.pattern_regex("a.b") == r"^a\.b$"


def test_chips_and_params_round_trip():
    f = search.parse(QueryDict("q=ab&match=starts&len_min=3&len_max=3&digits=no&sort=short"))
    assert f.chips() == ["Starts with “ab”", "3 characters", "No digits", "Sort: Shortest first"]
    assert search.parse(QueryDict(mutable=True) | {"q": "ab", **f.params()}).params() == f.params()


def test_id_for_day_is_the_inverse_of_estimate():
    day = date(2023, 4, 28)
    assert abs((dbid.estimate(dbid.id_for_day(day)).day - day).days) <= 1
    assert dbid.id_for_day(date(2000, 1, 1)) == 1


# ── Players page ──────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize(
    "qs,expected",
    [
        ("q=ab&match=starts&sort=az", ["ab_c", "ABC", "abc"]),
        ("q=c&match=ends&sort=az", ["ab_c", "ABC", "abc"]),
        ("q=abc&match=exact&case=1", ["abc"]),
        ("q=abc&match=exact", ["ABC", "abc"]),  # same name: most friends first
        ("q=a??&match=pattern&sort=az", ["ABC", "abc"]),
        ("q=?_?&match=pattern", []),
        ("q=a*c&match=pattern&sort=az", ["ab_c", "ABC", "abc"]),
        ("digits=yes&letters=no&symbols=no&spaces=no&underscore=no", ["123"]),
        ("symbols=yes", ["x.y"]),
        ("underscore=yes", ["ab_c"]),
        ("lead_space=1&sort=az", ["      ", " lead"]),
        ("trail_space=1&sort=az", ["      ", "trail "]),
        ("double_space=1&letters=yes", ["two  sp"]),
        ("letters=no&digits=no&symbols=no&underscore=no", ["      "]),
        ("len_min=6&len_max=6&sort=az", ["      ", "trail "]),
        ("min_friends=8&sort=friends", ["zz", "ABC"]),
        ("sort=old&len_max=2", ["zz"]),
        ("sort=long&len_min=7", ["two  sp"]),
    ],
)
def test_advanced_filters(client, mocked_http, roster, qs, expected):
    mock_lookup(mocked_http)
    assert names_found(client, qs) == expected


@pytest.mark.django_db
def test_name_of_only_spaces_is_found_and_drawn(client, mocked_http, roster):
    mock_lookup(mocked_http)
    response = client.get(reverse("players_directory") + "?q=%20%20%20%20%20%20&match=exact")
    assert [c["username"] for c in response.context["cards"]] == ["      "]
    assert "␣␣␣␣␣␣" in response.content.decode()


@pytest.mark.django_db
def test_joined_years_use_account_ids(client, mocked_http):
    old = BonkPlayer.objects.create(bonk_id=dbid.id_for_day(date(2015, 6, 1)), username="old")
    BonkPlayer.objects.create(bonk_id=dbid.id_for_day(date(2023, 6, 1)), username="new")
    mock_lookup(mocked_http)
    assert names_found(client, "joined_from=2014&joined_to=2016") == [old.username]
    assert names_found(client, "joined_from=2022") == ["new"]


@pytest.mark.django_db
def test_members_only(client, mocked_http, roster):
    BonkAccountLink.objects.create(user=UserFactory(username="zz"), bonk_player=roster["zz"])
    mock_lookup(mocked_http)
    assert names_found(client, "members=1") == ["zz"]


@pytest.mark.django_db
def test_paging_keeps_the_filters(client, mocked_http):
    for i in range(30):
        BonkPlayer.objects.create(bonk_id=5000 + i, username=f"n{i:02d}")
    mock_lookup(mocked_http)
    response = client.get(reverse("players_directory") + "?match=starts&q=n&sort=za")
    assert "match=starts" in response.context["base_qs"]
    assert "sort=za" in response.context["base_qs"]
    assert "Advanced search" in response.content.decode()
    assert "Starts with “n”" in response.content.decode()


@pytest.mark.django_db
def test_flash_view_takes_name_filters(client, mocked_http):
    user = UserFactory()
    for name in ["aa", "a_a", "1"]:
        FlashFriendship.objects.create(
            user=user, flash_friend=FlashFriend.objects.create(name=name)
        )
    mock_lookup(mocked_http)
    assert names_found(client, "view=flash&underscore=yes") == ["a_a"]
    assert names_found(client, "view=flash&letters=no") == ["1"]


@pytest.mark.django_db
def test_exact_replay_player_is_pinned_first(client, mocked_http):
    BonkPlayer.objects.create(bonk_id=1, username="-.-")
    mocked_http.get(
        f"{REPLAYS}/api/players/lookup",
        json={"results": [{"username": ".", "games": 4, "level": 9}]},
    )
    response = client.get(reverse("players_directory") + "?q=.")
    cards = response.context["cards"]
    assert [c["username"] for c in cards] == [".", "-.-"]
    assert cards[0]["profile_url"] == "/player/~./"


# ── Friends tab ───────────────────────────────────────────────────


@pytest.fixture
def circle(db):
    """tulip and claus are friends with each other and with ann; claus is
    also friends with bob. claus is a Bonkverse member."""
    p = {
        n: BonkPlayer.objects.create(bonk_id=200 + i, username=n, last_friend_count=3)
        for i, n in enumerate(["tulip", "claus", "ann", "bob"])
    }
    friends(p["tulip"], p["claus"])
    friends(p["tulip"], p["ann"])
    friends(p["claus"], p["ann"])
    friends(p["claus"], p["bob"])
    user = UserFactory(username="claus")
    BonkAccountLink.objects.create(user=user, bonk_player=p["claus"])
    return p, user


def friend_data(response):
    """The JSON the Friends tab hands its script."""
    html = response.content.decode()
    marker = '<script id="friends-data" type="application/json">'
    start = html.index(marker) + len(marker)
    return json.loads(html[start : html.index("</script>", start)])


@pytest.mark.django_db
def test_friends_tab_lists_both_directions(client, mocked_http, circle):
    mock_player(mocked_http, "tulip", status=404, body={"error": "x"})
    response = client.get(reverse("player_friends", args=["tulip"]))
    assert response.status_code == 200
    data = friend_data(response)
    assert sorted(r["n"] for r in data["bonk"]) == ["ann", "claus"]
    assert next(r for r in data["bonk"] if r["n"] == "claus")["m"] is True
    assert 'href="/player/ann/"' in response.content.decode()


@pytest.mark.django_db
def test_mutual_friends_for_a_signed_in_viewer(client, mocked_http, circle):
    _, claus = circle
    client.force_login(claus)
    mock_player(mocked_http, "tulip", status=404, body={"error": "x"})
    response = client.get(reverse("player_friends", args=["tulip"]))
    data = friend_data(response)
    assert {r["n"]: r["mu"] for r in data["bonk"]} == {"ann": True, "claus": False}
    assert next(r for r in data["bonk"] if r["n"] == "claus")["you"] is True
    assert response.context["you_are_friends"] and response.context["mutual_total"] == 1
    assert "You're friends." in response.content.decode()


@pytest.mark.django_db
def test_own_friends_tab_has_no_mutuals(client, mocked_http, circle):
    _, claus = circle
    client.force_login(claus)
    mock_player(mocked_http, "claus", status=404, body={"error": "x"})
    response = client.get(reverse("player_friends", args=["claus"]))
    assert response.context["is_self"] and not response.context["can_compare"]
    assert sorted(r["n"] for r in friend_data(response)["bonk"]) == ["ann", "bob", "tulip"]


@pytest.mark.django_db
def test_hidden_lists_stay_hidden(client, mocked_http, circle):
    _, claus = circle
    ProfileVisibility.objects.create(user=claus, friends=False)
    mock_player(mocked_http, "claus", status=404, body={"error": "x"})
    mock_player(mocked_http, "tulip", status=404, body={"error": "x"})
    # Their own tab is gone for visitors…
    overview = client.get(reverse("player_profile", args=["claus"])).content.decode()
    assert reverse("player_friends", args=["claus"]) not in overview
    tab = client.get(reverse("player_friends", args=["claus"]))
    assert "players/tab_unavailable.html" in [t.name for t in tab.templates]
    # …and they're left out of other players' lists.
    data = friend_data(client.get(reverse("player_friends", args=["tulip"])))
    assert [r["n"] for r in data["bonk"]] == ["ann"]
    # The owner still sees their own list.
    client.force_login(claus)
    data = friend_data(client.get(reverse("player_friends", args=["claus"])))
    assert len(data["bonk"]) == 3


@pytest.mark.django_db
def test_flash_friends_and_mutual_flash(client, mocked_http, circle):
    _, claus = circle
    now = BonkPlayer.objects.create(bonk_id=999, username="NewName")
    for name, bp in [("oldpal", now), ("lost", None)]:
        FlashFriendship.objects.create(
            user=claus, flash_friend=FlashFriend.objects.create(name=name, bonk_player=bp)
        )
    viewer = UserFactory(username="viewer")
    FlashFriendship.objects.create(user=viewer, flash_friend=FlashFriend.objects.get(name="lost"))
    client.force_login(viewer)
    mock_player(mocked_http, "claus", status=404, body={"error": "x"})
    response = client.get(reverse("player_friends", args=["claus"]))
    flash = {r["n"]: r for r in friend_data(response)["flash"]}
    assert flash["oldpal"]["now"] == "NewName" and flash["oldpal"]["p"]
    assert flash["lost"]["mu"] and not flash["lost"]["p"]
    assert response.context["flash_mutual_total"] == 1


@pytest.mark.django_db
def test_player_known_only_from_friend_lists_has_a_profile(client, mocked_http, circle):
    mock_player(mocked_http, "bob", status=404, body={"error": "x"})
    html = client.get(reverse("player_profile", args=["bob"])).content.decode()
    assert "Seen in friend lists" in html
    assert reverse("player_friends", args=["bob"]) in html
    assert reverse("player_activity", args=["bob"]) not in html
    assert ">1</strong>" in html  # the Friends card: claus


@pytest.mark.django_db
def test_overview_counts_mutual_friends(client, mocked_http, circle):
    _, claus = circle
    client.force_login(claus)
    mock_player(mocked_http, "tulip", status=404, body={"error": "x"})
    response = client.get(reverse("player_profile", args=["tulip"]))
    assert response.context["friend_counts"] == {"friends": 2, "flash": 0, "mutual": 1}


@pytest.mark.django_db
def test_settings_have_a_friends_switch(logged_in_client):
    html = logged_in_client.get(reverse("profile_settings")).content.decode()
    assert 'name="friends"' in html
