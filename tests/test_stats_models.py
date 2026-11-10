"""The archived win/loss models after their move from skins/ to stats/
(RFC-0001 Phase 5.3b): same tables, content types relabelled in place."""

import importlib

import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType

from stats.models import PlayerLoss, PlayerWin

INITIAL = importlib.import_module("stats.migrations.0001_initial")


def test_models_keep_their_original_tables():
    """Changing these would make Django rename the real tables."""
    assert PlayerWin._meta.db_table == "skins_playerwin"
    assert PlayerLoss._meta.db_table == "skins_playerloss"


@pytest.mark.django_db
def test_migration_relabels_content_types_both_ways():
    ContentType.objects.filter(app_label="stats", model__in=INITIAL.MODELS).delete()
    old = {m: ContentType.objects.create(app_label="skins", model=m).id for m in INITIAL.MODELS}

    INITIAL.relabel_content_types(apps, None)

    moved = dict(
        ContentType.objects.filter(app_label="stats", model__in=INITIAL.MODELS).values_list(
            "model", "id"
        )
    )
    assert moved == old

    INITIAL.unlabel_content_types(apps, None)

    assert set(
        ContentType.objects.filter(app_label="skins", model__in=INITIAL.MODELS).values_list(
            "id", flat=True
        )
    ) == set(old.values())


@pytest.mark.django_db
def test_rows_are_readable():
    PlayerWin.objects.create(username="alpha")
    PlayerLoss.objects.create(username="alpha")

    assert PlayerWin.objects.filter(username="alpha").count() == 1
    assert PlayerLoss.objects.filter(username="alpha").count() == 1
