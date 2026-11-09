"""Skin search (skins/search.py): results, index use, and the query time limit.

Search must stay index-backed. On 2026-11-03 a burst of searches stalled the site
because every search read the whole skins table; these tests pin the behavior
that prevents that.
"""

import pytest
from django.db import OperationalError, connection

from core.db import time_limited_queries
from skins.models import Skin
from skins.search import MIN_NAME_SIMILARITY, _relevance
from tests.factories import SkinFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog():
    return {
        "dragon": SkinFactory(
            name="Dragon Fire",
            creator="Saucy",
            description="a fiery dragon",
            labels={"style": "Cartoon", "themes": ["fantasy"], "objects": ["dragon"]},
        ),
        "whale": SkinFactory(name="Blue Whale", creator="ocean_man", description="big whale"),
        "percent": SkinFactory(name="100% Cat", creator="Bob_the_Builder", description="cat"),
        "plain": SkinFactory(name="Plain", creator="nobody", description="nothing here"),
    }


def _names(response):
    return {skin.name for skin in response.context["skins_on_page"]}


class TestResults:
    def test_relevance_finds_by_name_description_and_labels(self, client, catalog):
        assert _names(client.get("/search/?q=dragon")) == {"Dragon Fire"}
        assert _names(client.get("/search/?q=whale")) == {"Blue Whale"}

    def test_relevance_tolerates_typos_in_name(self, client, catalog):
        assert "Dragon Fire" in _names(client.get("/search/?q=dragn+fire"))

    def test_relevance_finds_by_creator(self, client, catalog):
        assert _names(client.get("/search/?q=Saucy")) == {"Dragon Fire"}

    def test_no_match_shows_empty_state(self, client, catalog):
        response = client.get("/search/?q=zzzzqqq")

        assert response.status_code == 200
        assert _names(response) == set()
        assert "No skins match “zzzzqqq”".encode() in response.content

    @pytest.mark.parametrize("mode", ["name", "creator", "description"])
    def test_contains_modes_are_case_insensitive(self, client, catalog, mode):
        query = {"name": "DRAGON", "creator": "sAuCy", "description": "FIERY"}[mode]

        assert _names(client.get(f"/search/?q={query}&mode={mode}")) == {"Dragon Fire"}

    def test_contains_mode_treats_wildcards_literally(self, client, catalog):
        # "%" and "_" are LIKE wildcards; a search for them must match them literally.
        assert _names(client.get("/search/?q=100%25&mode=name")) == {"100% Cat"}
        assert _names(client.get("/search/?q=b_the&mode=creator")) == {"100% Cat"}
        assert _names(client.get("/search/?q=_&mode=name")) == set()

    @pytest.mark.parametrize("sort", ["relevance", "newest", "favorites", "upvotes"])
    def test_empty_query_shows_a_random_sample_with_any_sort(self, client, catalog, sort):
        """Regression: an empty query sliced a random sample and then re-sorted it,
        which Django rejects, so /search/?sort=newest returned 500."""
        response = client.get(f"/search/?sort={sort}")

        assert response.status_code == 200
        assert _names(response) == {s.name for s in catalog.values()}

    def test_empty_query_sample_is_capped_at_one_page(self, client):
        SkinFactory.create_batch(60)

        assert len(client.get("/search/").context["skins_on_page"]) == 50


class TestIndexes:
    """With sequential scans disabled, Postgres must still answer each search
    from an index. If the stored vector and the query ever disagree (e.g. a
    different text-search config), the index becomes unusable and this fails."""

    def _plan(self, queryset) -> str:
        with time_limited_queries(5000, pg_trgm__similarity_threshold=MIN_NAME_SIMILARITY):
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL enable_seqscan = off")
            return queryset.explain()

    def test_relevance_uses_search_vector_and_name_indexes(self, catalog):
        plan = self._plan(_relevance(Skin.objects.all(), "dragon"))

        assert "skin_search_vector_gin" in plan
        assert "skin_name_trgm" in plan

    @pytest.mark.parametrize(
        "field,index",
        [
            ("name", "skin_name_trgm"),
            ("creator", "skin_creator_trgm"),
            ("description", "skin_description_trgm"),
        ],
    )
    def test_contains_modes_use_trigram_indexes(self, catalog, field, index):
        plan = self._plan(Skin.objects.filter(**{f"{field}__ilike_contains": "drag"}))

        assert index in plan

    def test_search_vector_updates_when_a_skin_changes(self, catalog):
        skin = catalog["plain"]
        skin.description = "now it has a unicorn"
        skin.save()

        assert Skin.objects.filter(search_vector="unicorn").get() == skin


class TestTimeLimit:
    def test_postgres_cancels_a_query_over_the_limit(self):
        with pytest.raises(OperationalError):
            with time_limited_queries(50):
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_sleep(1)")

    def test_limit_does_not_leak_outside_the_block(self):
        with time_limited_queries(50):
            pass

        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_sleep(0.1)")  # would be cancelled if it leaked

    def test_timed_out_search_shows_a_message_instead_of_500(
        self, client, catalog, monkeypatch, caplog
    ):
        def always_times_out(*args, **kwargs):
            raise OperationalError("canceling statement due to statement timeout")

        monkeypatch.setattr("skins.search.time_limited_queries", always_times_out)

        response = client.get("/search/?q=dragon")

        assert response.status_code == 200
        assert b"took too long" in response.content
        assert "search timed out" in caplog.text


def test_time_limit_is_undone_after_a_cancelled_query():
    """A cancelled query rolls the block back, which must also undo the limit."""
    with pytest.raises(OperationalError):
        with time_limited_queries(50):
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_sleep(1)")

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_sleep(0.1)")  # would be cancelled if it leaked
