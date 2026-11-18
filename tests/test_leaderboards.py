"""Leaderboards (stats/leaderboards.py, stats/views.py): one view, one template,
a config entry per board. Same URLs and URL names as the old views."""

import ast
from pathlib import Path

import pytest
from django.http import Http404
from django.template.loader import get_template
from django.test import RequestFactory
from django.urls import reverse

from stats import leaderboards, views
from tests.factories import SkinFactory, UserFactory

pytestmark = pytest.mark.django_db

REPO = Path(__file__).resolve().parent.parent


def _rows(response):
    return [(skin.name, skin.value) for skin in response.context["rows"]]


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
        ("favorited", [("C", 3), ("A", 1), ("B", 0)]),
    ],
)
def test_each_board_ranks_by_its_count(client, skins, board, expected):
    response = client.get(reverse(f"stats:leaderboards_{board}"))

    assert response.status_code == 200
    assert _rows(response) == expected
    assert f"<th>{leaderboards.LEADERBOARDS[board].column}</th>" in response.text


def test_urls_and_names_are_unchanged():
    assert reverse("stats:leaderboards_upvoted") == "/leaderboards/upvoted/"
    assert reverse("stats:leaderboards_favorited") == "/leaderboards/favorited/"


def test_tabs_list_upvoted_and_favorited_and_mark_the_current_one(client):
    response = client.get(reverse("stats:leaderboards_favorited"))

    assert response.context["tabs"] == [
        {"url_name": "stats:leaderboards_upvoted", "label": "Most upvoted", "current": False},
        {"url_name": "stats:leaderboards_favorited", "label": "Most favorited", "current": True},
    ]
    assert 'href="/leaderboards/favorited/" aria-current="page"' in response.text


def test_there_is_no_most_downvoted_board(client):
    """Design review 2026-11-09: a board ranking creators by dislike invites
    brigading. Votes stay a sort, not a hall of shame."""
    assert "downvoted" not in leaderboards.LEADERBOARDS
    assert client.get("/leaderboards/downvoted/").status_code == 404


def test_shows_the_top_50(client):
    SkinFactory.create_batch(55)

    assert len(client.get(reverse("stats:leaderboards_upvoted")).context["rows"]) == 50


def test_unknown_board_is_404():
    request = RequestFactory().get("/leaderboards/nope/")
    request.user = UserFactory()

    with pytest.raises(Http404):
        views.leaderboard(request, board="nope")


@pytest.mark.parametrize("board", list(leaderboards.LEADERBOARDS))
def test_one_query_for_the_board_however_many_skins(client, django_assert_max_num_queries, board):
    SkinFactory.create_batch(30)

    # An anonymous visitor: only the board. (The page frame's changelog query
    # went away with the changelog.)
    with django_assert_max_num_queries(1):
        client.get(reverse(f"stats:leaderboards_{board}"))


@pytest.mark.parametrize("board", list(leaderboards.LEADERBOARDS))
def test_every_board_has_a_table_partial(board):
    get_template(leaderboards.LEADERBOARDS[board].table)


def test_stats_reads_other_apps_only_through_selectors():
    """Boards get their rows from the owning app's selectors, so stats never
    imports another app's models (counting stays with the data's owner)."""
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
