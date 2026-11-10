"""Reusable Skin queries (skins/querysets.py) and the period definition (core/periods.py).

Pages use these instead of writing the same annotation or filter again; the
architecture test at the bottom keeps it that way.
"""

import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from core.periods import PERIODS, period_start
from skins.models import Skin
from skins.querysets import SEARCH_MODES
from tests.factories import SkinFactory, UserFactory

REPO = Path(__file__).resolve().parent.parent


class TestPeriods:
    def test_known_periods_reach_back_from_now(self):
        now = timezone.now()
        assert period_start("today", now) == now - timedelta(days=1)
        assert period_start("week", now) == now - timedelta(days=7)

    @pytest.mark.parametrize("name", ["all", "", "month", "yesterday"])
    def test_other_names_mean_all_time(self, name):
        assert period_start(name) is None

    def test_only_the_periods_pages_offer(self):
        assert set(PERIODS) == {"today", "week"}


@pytest.mark.django_db
class TestAnnotations:
    def test_with_favorite_count(self):
        popular, plain = SkinFactory(), SkinFactory()
        popular.favorited_by.add(UserFactory(), UserFactory())

        counts = dict(Skin.objects.with_favorite_count().values_list("id", "fav_count"))

        assert counts == {popular.id: 2, plain.id: 0}

    def test_with_score(self):
        skin = SkinFactory(upvotes=5, downvotes=2)

        assert Skin.objects.with_score().get(id=skin.id).score == 3


@pytest.mark.django_db
class TestCreatedIn:
    def test_filters_by_rolling_window(self):
        now = timezone.now()
        fresh, this_week, old = SkinFactory(), SkinFactory(), SkinFactory()
        Skin.objects.filter(id=fresh.id).update(created_at=now - timedelta(hours=2))
        Skin.objects.filter(id=this_week.id).update(created_at=now - timedelta(days=3))
        Skin.objects.filter(id=old.id).update(created_at=now - timedelta(days=30))

        def ids(period):
            return set(Skin.objects.created_in(period, now).values_list("id", flat=True))

        assert ids("today") == {fresh.id}
        assert ids("week") == {fresh.id, this_week.id}
        assert ids("all") == {fresh.id, this_week.id, old.id}


@pytest.mark.django_db
class TestSearchModes:
    @pytest.fixture
    def skins(self):
        return {
            "name": SkinFactory(name="Crimson Dragon", creator="zed", description="plain"),
            "creator": SkinFactory(name="Blob", creator="DragonMaker", description="plain"),
            "description": SkinFactory(name="Blob 2", creator="zed", description="a dragon"),
        }

    @pytest.mark.parametrize("mode", ["name", "creator", "description"])
    def test_each_mode_searches_its_field(self, skins, mode):
        found = set(Skin.objects.search("dragon", mode).values_list("id", flat=True))

        assert found == {skins[mode].id}

    def test_tags_mode_keeps_its_old_filter(self):
        # Known broken (labels is an object, not a word list; "fix tags mode" is
        # an open item). This refactor keeps the query exactly as it was.
        assert str(Skin.objects.search("Dragon", "tags").query) == str(
            Skin.objects.filter(labels__icontains=["dragon"]).query
        )

    def test_unknown_mode_falls_back_to_relevance(self, skins):
        assert str(Skin.objects.search("dragon", "nope").query) == str(
            Skin.objects.search("dragon", "relevance").query
        )

    def test_modes_offered(self):
        assert set(SEARCH_MODES) == {"relevance", "name", "creator", "tags", "description"}


@pytest.mark.parametrize(
    "pattern, use",
    [
        (r"Count\(\s*[\"']favorited_by[\"']", "Skin.objects....with_favorite_count()"),
        (r"F\(\s*[\"']upvotes[\"']\s*\)\s*-\s*F\(\s*[\"']downvotes", "....with_score()"),
    ],
)
def test_skin_queries_are_written_once(pattern, use):
    """RFC-0001 "one home per fact": these live in skins/querysets.py and core/periods.py."""
    allowed = {REPO / "skins" / "querysets.py", REPO / "core" / "periods.py"}
    skip = {"tests", "migrations", "staticfiles", "media", "backups", "node_modules", ".git"}
    offenders = [
        str(path.relative_to(REPO))
        for path in REPO.rglob("*.py")
        if skip.isdisjoint(path.relative_to(REPO).parts)
        and path not in allowed
        and re.search(pattern, path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"use {use} instead: {offenders}"
