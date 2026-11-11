"""The Players page (players.views.directory): one search over Bonk players,
replay players and legacy flash friends, as cards that open profiles."""

import pytest
import requests
from django.urls import reverse

from integrations.replays import PlayerError, lookup_players, search_players
from skins.models import BonkAccountLink
from players.models import BonkPlayer, FlashFriend, FlashFriendship
from tests.factories import UserFactory

REPLAYS = "http://replays.test"


@pytest.fixture(autouse=True)
def _replays_url(settings):
    settings.BONKVERSE_REPLAYS_URL = REPLAYS


def mock_lookup(mocked_http, results, status=200):
    mocked_http.get(f"{REPLAYS}/api/players/lookup", json={"results": results}, status=status)


def mock_search(mocked_http, results):
    mocked_http.get(f"{REPLAYS}/api/players", json={"results": results})


# ── Client ─────────────────────────────────────────────────────


def test_lookup_keys_by_lower_name(mocked_http):
    mock_lookup(mocked_http, [{"username": "Saucy Tulip", "games": 9, "level": 54}])
    result = lookup_players(REPLAYS, ["Saucy Tulip", "nobody"])
    assert result.data == {"saucy tulip": {"username": "Saucy Tulip", "games": 9, "level": 54}}
    assert "names=Saucy+Tulip" in mocked_http.calls[0].request.url


def test_lookup_with_no_names_makes_no_request(mocked_http):
    assert lookup_players(REPLAYS, []).data == {}
    assert len(mocked_http.calls) == 0


def test_lookup_unavailable(mocked_http):
    mocked_http.get(f"{REPLAYS}/api/players/lookup", body=requests.ConnectionError("down"))
    assert lookup_players(REPLAYS, ["x"]).error == PlayerError.UNAVAILABLE


def test_search_needs_three_letters(mocked_http):
    assert search_players(REPLAYS, "ab").data == []
    assert len(mocked_http.calls) == 0


# ── Page ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_all_players_cards_show_replay_stats_and_link_profiles(client, mocked_http):
    BonkPlayer.objects.create(bonk_id=1, username="Saucy Tulip", last_friend_count=45)
    BonkPlayer.objects.create(bonk_id=2, username="saucepan", last_friend_count=80)
    mock_lookup(mocked_http, [{"username": "Saucy Tulip", "games": 2052, "level": 206}])

    html = client.get(reverse("players_directory") + "?q=sau").content.decode()
    assert ">206<" in html and ">2,052<" in html and ">45<" in html
    assert reverse("player_profile", args=["Saucy Tulip"]) in html
    # No replays and no Bonkverse account, but known from friend lists:
    # a basic profile (overview and friends)
    assert reverse("player_profile", args=["saucepan"]) in html


@pytest.mark.django_db
def test_exact_name_and_members_come_first(client, mocked_http):
    BonkPlayer.objects.create(bonk_id=1, username="tulipfan", last_friend_count=99)
    member = BonkPlayer.objects.create(bonk_id=2, username="tulip_member", last_friend_count=1)
    BonkPlayer.objects.create(bonk_id=3, username="tulip", last_friend_count=0)
    BonkAccountLink.objects.create(user=UserFactory(username="tulip_member"), bonk_player=member)
    mock_lookup(mocked_http, [])

    html = client.get(reverse("players_directory") + "?q=tulip").content.decode()
    assert html.index(">tulip<") < html.index("tulip_member") < html.index("tulipfan")
    assert 'aria-label="Bonkverse member"' in html


@pytest.mark.django_db
def test_search_by_bonk_id(client, mocked_http):
    BonkPlayer.objects.create(bonk_id=4242, username="numbered")
    mock_lookup(mocked_http, [])
    html = client.get(reverse("players_directory") + "?q=4242").content.decode()
    assert "numbered" in html


@pytest.mark.django_db
def test_most_active_view_uses_replay_search(client, mocked_http):
    BonkPlayer.objects.create(bonk_id=7, username="The Saucy Tulip", last_friend_count=45)
    mock_search(mocked_http, [{"username": "The Saucy Tulip", "games": 2052, "level": 206}])
    html = client.get(reverse("players_directory") + "?view=replays&q=the").content.decode()
    assert "The Saucy Tulip" in html and ">45<" in html and ">206<" in html


@pytest.mark.django_db
def test_most_active_asks_for_three_letters(client, mocked_http):
    html = client.get(reverse("players_directory") + "?view=replays&q=th").content.decode()
    assert "at least 3 letters" in html
    assert len(mocked_http.calls) == 0


@pytest.mark.django_db
def test_flash_view_links_resolved_names(client, mocked_http):
    resolved = BonkPlayer.objects.create(bonk_id=9, username="NowCalledThis")
    user = UserFactory()
    for f in [
        FlashFriend.objects.create(name="oldname", bonk_player=resolved),
        FlashFriend.objects.create(name="lostpal"),
    ]:
        FlashFriendship.objects.create(user=user, flash_friend=f)
    mock_lookup(mocked_http, [{"username": "NowCalledThis", "games": 3, "level": 12}])

    html = client.get(reverse("players_directory") + "?view=flash").content.decode()
    assert reverse("player_profile", args=["NowCalledThis"]) in html
    assert "lostpal" in html and "Listed by" in html
    assert "No profile yet" in html  # unresolved Flash name


@pytest.mark.django_db
def test_replay_outage_still_lists_players(client, mocked_http):
    BonkPlayer.objects.create(bonk_id=1, username="someone")
    mocked_http.get(f"{REPLAYS}/api/players/lookup", status=503, json={"error": "down"})
    html = client.get(reverse("players_directory")).content.decode()
    assert "someone" in html
    assert "can't be loaded right now" in html


@pytest.mark.django_db
def test_names_are_escaped(client, mocked_http):
    BonkPlayer.objects.create(bonk_id=1, username="<b>x</b>")
    mock_lookup(mocked_http, [])
    html = client.get(reverse("players_directory")).content.decode()
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html


@pytest.mark.django_db
@pytest.mark.parametrize(
    "old,expected",
    [
        ("/players_search/players/?q=abc", "/players/?view=all&q=abc"),
        ("/players_search/flash-friends/", "/players/?view=flash"),
    ],
)
def test_old_pages_redirect(client, old, expected):
    response = client.get(old)
    assert response.status_code == 302
    assert response["Location"] == expected


@pytest.mark.django_db
def test_navbar_links_to_players(client, mocked_http):
    mock_lookup(mocked_http, [])
    html = client.get("/").content.decode()
    assert f'href="{reverse("players_directory")}"' in html


@pytest.mark.django_db
def test_cards_show_the_account_id(client, mocked_http):
    BonkPlayer.objects.create(bonk_id=13159907, username="dbid haver")
    mock_lookup(mocked_http, [])
    html = client.get(reverse("players_directory") + "?q=dbid").content.decode()
    assert "DBID 13159907" in html
