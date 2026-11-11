"""Advanced player search on the Players page (players/search.py) and the
Friends tab on profiles (players.selectors.friends)."""

import json
from datetime import date
from urllib.parse import urlencode

import pytest
from django.http import QueryDict
from django.urls import reverse

from core.bonk import dbid
from players import search
from players.models import ProfileVisibility
from skins.models import BonkAccountLink
from players.models import BonkPlayer, FlashFriend, FlashFriendship, Friendship
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


def rules(*lines, sort=None, **extra):
    """A query string from rule lines: (field, op, value[, value2]) or
    ("or", field, op, value…) to join with OR instead of AND."""
    params = {}
    for i, line in enumerate(lines):
        conn = "and"
        if line[0] in ("and", "or"):
            conn, line = line[0], line[1:]
        field, op, *values = line
        params.update({f"c{i}": conn, f"f{i}": field, f"o{i}": op})
        if values:
            params[f"v{i}"] = values[0]
        if len(values) > 1:
            params[f"w{i}"] = values[1]
    if sort:
        params["sort"] = sort
    params.update(extra)
    return urlencode(params)


# ── Parsing ───────────────────────────────────────────────────────


def test_rule_text_keeps_spaces_but_the_box_trims():
    q = search.parse(QueryDict("q=  ab  &" + rules(("name", "is", "  ab  "))))
    assert q.text == "ab" and q.rules[0].value == "  ab  "


def test_unusable_rules_are_dropped():
    q = search.parse(
        QueryDict(
            rules(
                ("name", "starts", ""),  # no value
                ("evil", "is", "x"),  # no such field
                ("length", "between", "9"),  # between needs two
                ("chars", "only", "emoji"),  # no such choice
                ("listed", "gte", "2"),  # Flash friends only
                ("length", "between", "9", "3"),
            )
        )
    )
    assert [(r.field, r.value, r.value2) for r in q.rules] == [("length", "3", "9")]


def test_pattern_wildcards_and_escaping():
    assert search.pattern_regex("a*b?") == "^a.*b.$"
    assert search.pattern_regex("a.b") == r"^a\.b$"


def test_chips_and_params_round_trip():
    qs = rules(("name", "starts", "_"), ("or", "length", "eq", "3"), sort="short")
    q = search.parse(QueryDict(qs))
    assert q.chips() == [("", "Name starts with “_”"), ("OR", "Length is 3 characters")]
    assert search.parse(QueryDict(urlencode(q.params()))).params() == q.params()


def test_id_for_day_is_the_inverse_of_estimate():
    day = date(2023, 4, 28)
    assert abs((dbid.estimate(dbid.id_for_day(day)).day - day).days) <= 1
    assert dbid.id_for_day(date(2000, 1, 1)) == 1


def test_examples_fit_their_list():
    labels = [label for label, _ in search.example_links("flash")]
    assert "Joined in 2014" not in labels and "Only digits" in labels


# ── Players page ──────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize(
    "qs,expected",
    [
        # Several rules on the name: starts with … AND ends with …
        (rules(("name", "starts", "a"), ("name", "ends", "c"), sort="az"), ["ab_c", "ABC", "abc"]),
        (rules(("name", "starts", "a"), ("name", "not_contains", "_"), sort="az"), ["ABC", "abc"]),
        (rules(("name", "is", "abc")), ["ABC", "abc"]),
        (rules(("name", "is", "abc"), k0="1"), ["abc"]),
        (rules(("name", "pattern", "a??"), sort="az"), ["ABC", "abc"]),
        (rules(("name", "pattern", "a*c"), sort="az"), ["ab_c", "ABC", "abc"]),
        # AND before OR: (starts with z) OR (has symbols AND 3 characters)
        (
            rules(
                ("name", "starts", "z"),
                ("or", "chars", "has", "symbols"),
                ("length", "eq", "3"),
                sort="az",
            ),
            ["x.y", "zz"],
        ),
        (rules(("chars", "only", "digits")), ["123"]),
        (rules(("chars", "only", "spaces")), ["      "]),
        (rules(("chars", "has", "symbols")), ["x.y"]),
        (rules(("chars", "none", "letters"), sort="az"), ["      ", "123"]),
        (rules(("spaces", "has", "lead"), sort="az"), ["      ", " lead"]),
        (rules(("spaces", "has", "trail"), sort="az"), ["      ", "trail "]),
        (rules(("spaces", "has", "double"), ("chars", "has", "letters")), ["two  sp"]),
        (rules(("length", "between", "6", "6"), sort="az"), ["      ", "trail "]),
        (rules(("length", "gte", "7"), sort="long"), ["two  sp"]),
        (rules(("friends", "gte", "8"), sort="friends"), ["zz", "ABC"]),
        (rules(("bonk_id", "lt", "1002"), sort="old"), ["abc", "ab_c"]),
        (rules(("length", "lte", "2"), sort="old"), ["zz"]),
    ],
)
def test_rules(client, mocked_http, roster, qs, expected):
    mock_lookup(mocked_http)
    assert names_found(client, qs) == expected


@pytest.mark.django_db
def test_name_of_only_spaces_is_found_and_drawn(client, mocked_http, roster):
    mock_lookup(mocked_http)
    response = client.get(reverse("players_directory") + "?" + rules(("name", "is", "      ")))
    assert [c["username"] for c in response.context["cards"]] == ["      "]
    assert "␣␣␣␣␣␣" in response.content.decode()


@pytest.mark.django_db
def test_joined_years_use_account_ids(client, mocked_http):
    BonkPlayer.objects.create(bonk_id=dbid.id_for_day(date(2015, 6, 1)), username="old")
    BonkPlayer.objects.create(bonk_id=dbid.id_for_day(date(2023, 6, 1)), username="new")
    mock_lookup(mocked_http)
    assert names_found(client, rules(("joined", "between", "2014", "2016"))) == ["old"]
    assert names_found(client, rules(("joined", "after", "2021"))) == ["new"]
    assert names_found(client, rules(("joined", "in", "2015"))) == ["old"]
    assert names_found(client, rules(("joined", "before", "2016"))) == ["old"]


@pytest.mark.django_db
def test_members(client, mocked_http, roster):
    BonkAccountLink.objects.create(user=UserFactory(username="zz"), bonk_player=roster["zz"])
    mock_lookup(mocked_http)
    assert names_found(client, rules(("member", "yes"))) == ["zz"]
    assert "zz" not in names_found(client, rules(("member", "no")))


@pytest.mark.django_db
def test_paging_keeps_the_rules(client, mocked_http):
    for i in range(30):
        BonkPlayer.objects.create(bonk_id=5000 + i, username=f"n{i:02d}")
    mock_lookup(mocked_http)
    response = client.get(
        reverse("players_directory") + "?" + rules(("name", "starts", "n"), sort="za")
    )
    assert "o0=starts" in response.context["base_qs"] and "sort=za" in response.context["base_qs"]
    html = response.content.decode()
    assert "Advanced search" in html and "Name starts with “n”" in html
    assert 'name="f0"' in html and 'id="qb-state"' in html


@pytest.mark.django_db
def test_flash_view_takes_name_rules(client, mocked_http):
    user = UserFactory()
    for name in ["aa", "a_a", "1"]:
        FlashFriendship.objects.create(
            user=user, flash_friend=FlashFriend.objects.create(name=name)
        )
    mock_lookup(mocked_http)
    assert names_found(client, "view=flash&" + rules(("chars", "has", "underscore"))) == ["a_a"]
    assert names_found(client, "view=flash&" + rules(("chars", "none", "letters"))) == ["1"]
    assert names_found(client, "view=flash&" + rules(("listed", "gte", "1"), sort="az")) == [
        "1",
        "a_a",
        "aa",
    ]


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
