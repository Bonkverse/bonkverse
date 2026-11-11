"""bonk.io level math, account dates from IDs, XP from login, the XP & Level
calculator and its JSON, and account ages on profiles and player cards."""

from datetime import date
from urllib.parse import quote

import pytest
from django.urls import reverse
from django.utils import timezone

from core.bonk import dbid, levels
from players import calculator
from players.models import ProfileVisibility
from players.models import BonkPlayer
from tests.factories import UserFactory
from tests.test_players import REPLAYS, profile_json

# ── Level math (checked against bonkonauts and BonkLeagues) ──────


@pytest.mark.parametrize(
    "level,xp", [(1, 0), (2, 100), (200, 3_960_100), (250, 6_200_100), (300, 8_940_100)]
)
def test_xp_for_level(level, xp):
    assert levels.xp_for_level(level) == xp
    assert levels.level_for_xp(xp) == level


def test_progress_within_a_level():
    p = levels.progress(4_239_000)
    assert (p.level, p.into_level, p.level_size, p.percent) == (206, 36_500, 41_100, 88.81)
    assert p.to_next == 4_600


def test_goal():
    g = levels.goal(4_239_000, levels.xp_for_level(300))
    assert (g.xp_needed, g.wins_needed, g.days_at_cap) == (4_701_100, 47_011, 262)
    assert levels.goal(10, 5).xp_needed == 0


# ── Account dates ─────────────────────────────────────────────


def test_dbid_estimate_matches_known_tools():
    assert dbid.estimate(13_159_907).day == date(2023, 4, 28)


def test_dbid_known_point_is_exact():
    est = dbid.estimate(14_090_964)
    assert est.day == date(2025, 2, 8) and not est.extrapolated


def test_dbid_past_the_newest_point_is_extrapolated_and_never_future():
    est = dbid.estimate(99_999_999, today=date(2026, 11, 8))
    assert est.extrapolated and est.day == date(2026, 11, 8)


@pytest.mark.parametrize("bad", [None, 0, -5])
def test_dbid_bad_ids(bad):
    assert dbid.estimate(bad) is None


def test_known_points_go_up_together():
    pts = dbid.known_points()
    assert all(a[0] < b[0] and a[1] <= b[1] for a, b in zip(pts, pts[1:], strict=False))


# ── Calculator shaping ────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [(206, 206), (-285, None), (0, None), (10**9, None)])
def test_sane_level(raw, expected):
    assert calculator.sane_level(raw) == expected


def test_level_card_exact_and_range():
    exact = calculator.level_card(206, xp=4_239_000)
    assert exact["exact"] and exact["percent"] == 88.81 and exact["milestone"] == 250
    rough = calculator.level_card(206)
    assert not rough["exact"] and rough["xp_floor"] == 4_202_500
    # XP from an older login that no longer matches the level is ignored
    assert not calculator.level_card(206, xp=100)["exact"]


def test_recent_pace_and_series():
    profile = profile_json()
    pace = calculator.recent_pace(profile)
    assert pace["levels"] == 1 and pace["days"] == 1
    assert pace["xp_per_day"] == levels.xp_for_level(54) - levels.xp_for_level(53)
    assert calculator.level_series(profile)[0] == ["2025-03-05", 40]


# ── XP saved from bonk.io login ───────────────────────────────


@pytest.mark.django_db
def test_login_records_xp(client, mocked_http):
    from tests.conftest import load_bonk_fixture
    from tests.test_login import BONK_LOGIN_URL, _post_login

    mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))
    _post_login(client)
    player = BonkPlayer.objects.get(bonk_id=1234567)
    assert player.xp == 4200 and player.xp_seen_at is not None


# ── Pages and JSON ────────────────────────────────────────────


def mock_profile(mocked_http, name):
    mocked_http.get(f"{REPLAYS}/api/player/{quote(name, safe='')}", json=profile_json(name))


@pytest.fixture(autouse=True)
def _replays_url(settings):
    settings.BONKVERSE_REPLAYS_URL = REPLAYS


@pytest.mark.django_db
def test_calculator_page_is_public(client):
    response = client.get(reverse("xp_calculator") + "?player=Saucy%20Tulip&goal=250")
    html = response.content.decode()
    assert response.status_code == 200
    assert 'id="xc-constants"' in html and "js/xp_calculator.js" in html
    assert 'data-prefill-player="Saucy Tulip"' in html and 'data-prefill-goal="250"' in html


@pytest.mark.django_db
def test_player_json(client, mocked_http):
    BonkPlayer.objects.create(
        bonk_id=13_159_907, username="Saucy Tulip", xp=285_000, xp_seen_at=timezone.now()
    )
    mock_profile(mocked_http, "Saucy Tulip")
    data = client.get(reverse("xp_calculator_player") + "?name=Saucy%20Tulip").json()
    assert data["ok"]
    p = data["data"]
    assert p["level"] == 54 and p["created"] == "2023-04-28"
    assert p["xp"] == 285_000 and p["xp_floor"] == levels.xp_for_level(54)
    assert p["series"] and p["pace"]["levels"] == 1


@pytest.mark.django_db
def test_player_json_respects_privacy(client, mocked_http):
    owner = UserFactory(username="Saucy Tulip")
    ProfileVisibility.objects.create(user=owner, level_history=False)
    mock_profile(mocked_http, "Saucy Tulip")
    response = client.get(reverse("xp_calculator_player") + "?name=Saucy%20Tulip")
    assert response.status_code == 403 and response.json()["error"] == "private"


@pytest.mark.django_db
def test_player_json_not_found(client, mocked_http):
    mocked_http.get(f"{REPLAYS}/api/player/nobody", json={"error": "x"}, status=404)
    response = client.get(reverse("xp_calculator_player") + "?name=nobody")
    assert response.status_code == 404


@pytest.mark.django_db
def test_levels_json_is_cached(client, mocked_http):
    mocked_http.get(
        f"{REPLAYS}/api/levels/distribution", json={"levels": [[1, 5], [206, 1]], "players": 6}
    )
    for _ in range(2):
        data = client.get(reverse("xp_calculator_levels")).json()
    assert data == {"ok": True, "data": {"levels": [[1, 5], [206, 1]], "players": 6}}
    assert len(mocked_http.calls) == 1


@pytest.mark.django_db
def test_levels_json_outage(client, mocked_http):
    mocked_http.get(f"{REPLAYS}/api/levels/distribution", status=503, json={"error": "x"})
    assert client.get(reverse("xp_calculator_levels")).json() == {
        "ok": False,
        "error": "unavailable",
    }


@pytest.mark.django_db
def test_profile_shows_account_age_and_xp(client, mocked_http):
    BonkPlayer.objects.create(
        bonk_id=13_159_907, username="Saucy Tulip", xp=285_000, xp_seen_at=timezone.now()
    )
    mock_profile(mocked_http, "Saucy Tulip")
    html = client.get(reverse("player_profile", args=["Saucy Tulip"])).content.decode()
    assert "Joined bonk.io ≈ Apr 2023" in html
    assert "285,000 XP" in html


@pytest.mark.django_db
def test_player_cards_show_join_date_and_hide_impossible_levels(client, mocked_http):
    BonkPlayer.objects.create(bonk_id=13_159_907, username="Saucy Tulip", last_friend_count=4)
    mocked_http.get(
        f"{REPLAYS}/api/players/lookup",
        json={"results": [{"username": "Saucy Tulip", "games": 3, "level": -285}]},
    )
    html = client.get(reverse("players_directory")).content.decode()
    assert "Joined ≈ Apr 2023" in html
    assert "-285" not in html


@pytest.mark.django_db
def test_navbar_has_tools(client, mocked_http):
    html = client.get(reverse("players_directory")).content.decode()
    assert reverse("xp_calculator") in html


def test_calculator_script_builds_profile_links_like_the_url_conf():
    """xp_calculator.js hard-codes the profile path (so links never come from
    page data); keep it in step with players/urls.py."""
    from pathlib import Path

    script = Path("players/static/players/js/xp_calculator.js").read_text(encoding="utf-8")
    assert reverse("player_profile", args=["x"]) == "/player/x/"
    assert "`/player/${encodeURIComponent(urlName(String(name)))}/`" in script
