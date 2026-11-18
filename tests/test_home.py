"""The home page (site_pages/selectors.py: home; design review step 2f):
what Bonkverse is, three doors, latest replays with the collector
countdown, and two skin rows."""

from datetime import UTC, datetime, timedelta

import pytest
import responses
from django.core.cache import cache
from django.utils import timezone

from site_pages.selectors import ago, home
from tests.factories import BonkPlayerFactory, SkinFactory, SkinReportFactory

pytestmark = pytest.mark.django_db

REPLAYS = "http://replays.test"
NOW = datetime(2026, 11, 18, 22, 0, tzinfo=UTC)

RECENT = {
    "results": [
        {
            "cycle": 7,
            "id": "1234",
            "mapid": "555",
            "mapname": "Death Arrows",
            "fetched_at": (NOW - timedelta(minutes=12)).isoformat(),
            "players": [
                {"username": "Isabelle26", "guest": False},
                {"username": "Guest 77", "guest": True},
                {"username": "legendboss", "guest": False},
                {"username": "Magic", "guest": False},
                {"username": "zorro", "guest": False},
                {"username": "ButDoge", "guest": False},
            ],
        }
    ]
}
STATUS = {
    "status": "waiting",
    "next_fetch_at": (NOW + timedelta(seconds=77)).isoformat(),
    "last_run_added": 37,
    "last_run_at": (NOW - timedelta(minutes=4)).isoformat(),
}


@pytest.fixture(autouse=True)
def _replay_site(settings):
    settings.BONKVERSE_REPLAYS_URL = REPLAYS


def _mock_replay_site(mocked_http, recent=RECENT, status=STATUS):
    mocked_http.add(responses.GET, f"{REPLAYS}/api/recent", json=recent)
    mocked_http.add(responses.GET, f"{REPLAYS}/api/status", json=status)


def test_page_says_what_bonkverse_is_with_live_counts(client, mocked_http):
    _mock_replay_site(mocked_http)
    SkinFactory.create_batch(3)
    BonkPlayerFactory.create_batch(2)

    html = client.get("/").content.decode()

    assert "Skins, replays and stats for bonk.io players" in html
    assert "3 skins made by players · 3 new today" in html
    assert "Profiles for 2 players" in html
    assert "Discover. Create. Share." not in html  # the old slogan
    # The hero's tiles are the doors.
    for door in ('href="/search/"', f'href="{REPLAYS}/"', 'href="/players/"', "home-tile--editor"):
        assert door in html


def test_counts_are_grouped(client, mocked_http):
    _mock_replay_site(mocked_http)
    cache.set("players:known_count", 171228)

    assert "Profiles for 171,228 players" in client.get("/").content.decode()


def test_latest_replays_link_to_watch_pages_and_player_profiles(mocked_http):
    _mock_replay_site(mocked_http)

    data = home(now=NOW)

    [card] = data["replays"]
    assert card["map_name"] == "Death Arrows"
    assert card["watch_url"] == f"{REPLAYS}/watch/7/1234"
    assert card["thumbnail_url"] == f"{REPLAYS}/api/map/555/thumbnail.svg"
    assert [p["username"] for p in card["players"]] == [
        "Isabelle26",
        "Guest 77",
        "legendboss",
        "Magic",
    ]
    assert card["more_players"] == 2
    assert card["ago"] == "12 min ago"
    assert data["collector"] == {
        "seconds_to_next": 77,
        "next_in": "1:17",
        "last_added": 37,
        "last_ago": "4 min ago",
    }


def test_replay_names_are_doors_to_profiles_except_guests(client, mocked_http):
    soon = (timezone.now() + timedelta(minutes=2)).isoformat()
    _mock_replay_site(mocked_http, status={**STATUS, "next_fetch_at": soon})

    html = client.get("/").content.decode()

    assert 'href="/player/Isabelle26/"' in html
    assert "Guest 77" in html and 'href="/player/Guest%2077/"' not in html
    assert f'href="{REPLAYS}/watch/7/1234"' in html
    assert "data-countdown=" in html


def test_page_works_without_the_replay_site(client, mocked_http):
    mocked_http.add(responses.GET, f"{REPLAYS}/api/recent", status=503)
    SkinFactory(name="Still here")

    response = client.get("/")

    assert response.status_code == 200
    assert "Latest replays" not in response.content.decode()
    assert "Still here" in response.content.decode()


def test_replay_site_is_asked_at_most_once_a_minute_even_when_down(client, mocked_http):
    recent = mocked_http.add(responses.GET, f"{REPLAYS}/api/recent", status=503)

    client.get("/")
    client.get("/")

    assert recent.call_count == 1


def test_collecting_now_when_the_next_run_is_due(mocked_http):
    _mock_replay_site(mocked_http, status={**STATUS, "next_fetch_at": NOW.isoformat()})

    assert home(now=NOW)["collector"]["seconds_to_next"] is None


def test_skin_rows_show_newest_and_most_favorited_without_reported_skins(client, mocked_http):
    _mock_replay_site(mocked_http)
    SkinFactory(name="Fresh")
    reported = SkinFactory(name="Reported")
    SkinReportFactory(skin=reported)

    html = client.get("/").content.decode()

    assert "New skins" in html and "Most favorited" in html
    assert "Fresh" in html
    assert "Reported" not in html


@pytest.mark.parametrize(
    "delta, text",
    [
        (timedelta(seconds=20), "just now"),
        (timedelta(minutes=5), "5 min ago"),
        (timedelta(hours=3), "3 h ago"),
        (timedelta(days=10), "Nov 8, 2026"),
    ],
)
def test_ago_follows_the_design_guide(delta, text):
    assert ago(NOW - delta, NOW) == text


def test_hero_players_tile_shows_registered_players_from_the_newest_replays(mocked_http):
    _mock_replay_site(mocked_http)
    BonkPlayerFactory(username="Isabelle26", worn_skin_code="code-1")

    players = home(now=NOW)["hero_players"]

    assert [p["username"] for p in players] == [
        "Isabelle26",
        "legendboss",
        "Magic",
        "zorro",
        "ButDoge",
    ]  # guests left out, at most 5
    assert players[0]["skin"].startswith("/player/Isabelle26/")
    assert players[1]["skin"] is None  # no skin seen: a plain ball


def test_hero_skins_tile_shows_favorite_skins(client, mocked_http):
    _mock_replay_site(mocked_http)
    SkinFactory(image_url="/media/skins/fav.png")

    html = client.get("/").content.decode()

    assert 'class="home-tile__art home-balls"' in html
    assert 'src="/media/skins/fav.png"' in html
