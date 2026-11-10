"""Skin leaderboards (skins/leaderboards.py): one view, one template, a config
entry per board. Same URLs and URL names as the three old views."""

import pytest
from django.http import Http404
from django.test import RequestFactory
from django.urls import reverse

from skins import leaderboards
from tests.factories import SkinFactory, UserFactory

pytestmark = pytest.mark.django_db


def _rows(response):
    return [(skin.name, skin.value) for skin in response.context["skins"]]


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
        ("downvoted", [("B", 7), ("C", 3), ("A", 1)]),
        ("favorited", [("C", 3), ("A", 1), ("B", 0)]),
    ],
)
def test_each_board_ranks_by_its_count(client, skins, board, expected):
    response = client.get(reverse(f"leaderboards_{board}"))

    assert response.status_code == 200
    assert _rows(response) == expected
    assert f"<th>{leaderboards.LEADERBOARDS[board].column}</th>" in response.text


def test_urls_and_names_are_unchanged():
    assert reverse("leaderboards_upvoted") == "/leaderboards/upvoted/"
    assert reverse("leaderboards_favorited") == "/leaderboards/favorited/"
    assert reverse("leaderboards_downvoted") == "/leaderboards/downvoted/"


def test_tabs_list_upvoted_and_favorited_and_mark_the_current_one(client):
    response = client.get(reverse("leaderboards_favorited"))

    assert response.context["tabs"] == [
        {"url_name": "leaderboards_upvoted", "label": "Most upvoted", "current": False},
        {"url_name": "leaderboards_favorited", "label": "Most favorited", "current": True},
    ]
    assert 'href="/leaderboards/favorited/" aria-current="page"' in response.text


def test_downvoted_board_has_no_tabs(client):
    response = client.get(reverse("leaderboards_downvoted"))

    assert "site-leaderboard-tabs" not in response.text


def test_shows_the_top_50(client):
    SkinFactory.create_batch(55)

    assert len(client.get(reverse("leaderboards_upvoted")).context["skins"]) == 50


def test_unknown_board_is_404():
    request = RequestFactory().get("/leaderboards/nope/")
    request.user = UserFactory()

    with pytest.raises(Http404):
        leaderboards.leaderboard(request, board="nope")


@pytest.mark.parametrize("board", list(leaderboards.LEADERBOARDS))
def test_one_query_for_the_board_however_many_skins(client, django_assert_max_num_queries, board):
    SkinFactory.create_batch(30)

    # An anonymous visitor: the page frame's changelog banner, then the board.
    with django_assert_max_num_queries(2):
        client.get(reverse(f"leaderboards_{board}"))
