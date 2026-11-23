"""Leaderboards (stats/leaderboards.py, stats/views.py): one "Top skins" page,
a tab per board (Most upvoted, Most favorited) and period chips (all time,
this month, this week). Same URLs and URL names as the old views."""

import ast
from datetime import timedelta
from pathlib import Path

import pytest
from django.http import Http404
from django.template.loader import get_template
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from skins.models import Skin
from stats import leaderboards, views
from tests.factories import SkinFactory, SkinReportFactory, UserFactory

pytestmark = pytest.mark.django_db

REPO = Path(__file__).resolve().parent.parent


def _rows(response):
    return [(skin.name, skin.value) for skin in response.context["rows"]]


def _age(skin, days):
    Skin.objects.filter(id=skin.id).update(created_at=timezone.now() - timedelta(days=days))


@pytest.fixture
def skins():
    fans = [UserFactory() for _ in range(3)]
    a = SkinFactory(name="A", upvotes=9, downvotes=1)
    b = SkinFactory(name="B", upvotes=5, downvotes=7)
    c = SkinFactory(name="C", upvotes=1, downvotes=3)
    a.favorited_by.add(fans[0])
    c.favorited_by.add(*fans)
    return a, b, c


@pytest.mark.parametrize(
    "board, expected",
    [
        ("upvoted", [("A", 9), ("B", 5), ("C", 1)]),
        ("favorited", [("C", 3), ("A", 1)]),  # B has none: left out
    ],
)
def test_each_board_ranks_by_its_count(client, skins, board, expected):
    response = client.get(reverse(f"stats:leaderboards_{board}"))

    assert response.status_code == 200
    assert _rows(response) == expected
    assert f'class="bv-muted">{leaderboards.LEADERBOARDS[board].column}</span>' in response.text


def test_urls_and_names_are_unchanged():
    assert reverse("stats:leaderboards_upvoted") == "/leaderboards/upvoted/"
    assert reverse("stats:leaderboards_favorited") == "/leaderboards/favorited/"


def test_page_is_top_skins_with_a_tab_per_board(client):
    response = client.get(reverse("stats:leaderboards_favorited"))

    assert "<h1>Top skins</h1>" in response.text
    assert response.context["tabs"] == [
        {"url_name": "stats:leaderboards_upvoted", "label": "Most upvoted", "current": False},
        {"url_name": "stats:leaderboards_favorited", "label": "Most favorited", "current": True},
    ]
    assert 'href="/leaderboards/favorited/" aria-current="page"' in response.text


def test_period_keeps_skins_uploaded_in_that_window(client):
    new = SkinFactory(name="New", upvotes=2)
    month = SkinFactory(name="Month", upvotes=5)
    old = SkinFactory(name="Old", upvotes=9)
    _age(month, 20)
    _age(old, 100)
    url = reverse("stats:leaderboards_upvoted")

    assert _rows(client.get(url + "?period=week")) == [("New", 2)]
    assert _rows(client.get(url + "?period=month")) == [("Month", 5), ("New", 2)]
    assert _rows(client.get(url)) == [("Old", 9), ("Month", 5), ("New", 2)]
    assert new and old


def test_period_chips_mark_the_current_one_and_tabs_keep_it(client):
    response = client.get(reverse("stats:leaderboards_upvoted") + "?period=week")

    assert 'href="?period=week" aria-current="page">This week' in response.text
    assert 'href="/leaderboards/favorited/?period=week"' in response.text
    assert "<title>Top skins · Most upvoted · This week · Bonkverse</title>" in response.text


def test_unknown_period_is_all_time(client, skins):
    response = client.get(reverse("stats:leaderboards_upvoted") + "?period=decade")

    assert response.context["period"] == "all"
    assert len(_rows(response)) == 3


def test_empty_period_says_so(client):
    old = SkinFactory(upvotes=3)
    _age(old, 100)

    response = client.get(reverse("stats:leaderboards_upvoted") + "?period=week")

    assert "No skins here yet" in response.text


def test_rows_link_the_skin_and_its_creator(client):
    skin = SkinFactory(name="Bongo Cat", creator="Isabelle26", upvotes=4)

    html = client.get(reverse("stats:leaderboards_upvoted")).text

    assert f'href="{skin.get_absolute_url()}">Bongo Cat</a>' in html
    assert 'href="/player/Isabelle26/">Isabelle26</a>' in html


def test_reported_skins_are_left_out(client):
    SkinFactory(name="Fine", upvotes=1)
    SkinReportFactory(skin=SkinFactory(name="Reported", upvotes=50))

    assert _rows(client.get(reverse("stats:leaderboards_upvoted"))) == [("Fine", 1)]


def test_there_is_no_most_downvoted_board(client):
    """Design review 2026-11-09: a board ranking creators by dislike invites
    brigading. Votes stay a sort, not a hall of shame."""
    assert "downvoted" not in leaderboards.LEADERBOARDS
    assert client.get("/leaderboards/downvoted/").status_code == 404


def test_shows_the_top_50(client):
    SkinFactory.create_batch(55, upvotes=1)

    assert len(client.get(reverse("stats:leaderboards_upvoted")).context["rows"]) == 50


def test_unknown_board_is_404():
    request = RequestFactory().get("/leaderboards/nope/")
    request.user = UserFactory()

    with pytest.raises(Http404):
        views.leaderboard(request, board="nope")


@pytest.mark.parametrize("board", list(leaderboards.LEADERBOARDS))
@pytest.mark.parametrize("period", list(leaderboards.PERIODS))
def test_one_query_for_the_board_however_many_skins(
    client, django_assert_max_num_queries, board, period
):
    SkinFactory.create_batch(30, upvotes=1)

    # An anonymous visitor: only the board.
    with django_assert_max_num_queries(1):
        client.get(reverse(f"stats:leaderboards_{board}") + f"?period={period}")


@pytest.mark.parametrize("board", list(leaderboards.LEADERBOARDS))
def test_every_board_has_a_row_partial(board):
    get_template(leaderboards.LEADERBOARDS[board].partial)


def test_stats_reads_other_apps_only_through_selectors():
    """Boards get their rows from the owning app's selectors (counting stays
    with the data's owner), so stats never imports another app's models."""
    apps = {path.parent.name for path in REPO.glob("*/apps.py")}
    found = []
    for path in (REPO / "stats").rglob("*.py"):
        if "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                top, _, rest = node.module.partition(".")
                if top != "stats" and rest == "models" and top in apps:
                    found.append(f"{path.name}: {node.module}")
    assert found == []


# ── Your own row (ADR 0021: the page's one highlight) ─────────────────────


def test_your_best_ranked_skin_is_the_one_highlight(client):
    me = UserFactory(username="Maker")
    SkinFactory(name="Mine low", creator="maker", upvotes=2)
    SkinFactory(name="Someone else", creator="Other", upvotes=8)
    best = SkinFactory(name="Mine high", creator="Maker", upvotes=5)
    client.force_login(me)

    response = client.get(reverse("stats:leaderboards_upvoted"))

    assert response.context["own_skin_id"] == best.id
    html = response.text
    assert html.count("bv-highlight") == 1
    assert html.count("Your top skin") == 1


def test_no_highlight_when_signed_out_or_not_on_the_board(client):
    SkinFactory(name="Theirs", creator="Other", upvotes=3)

    assert "bv-highlight" not in client.get(reverse("stats:leaderboards_upvoted")).text

    client.force_login(UserFactory(username="Nobody"))
    response = client.get(reverse("stats:leaderboards_upvoted"))
    assert response.context["own_skin_id"] is None
    assert "bv-highlight" not in response.text
