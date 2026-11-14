"""BonkAccountLink after its move from skins/ to accounts/ (RFC-0001 Phase
5.5): same table, constraint and index names, content type relabelled in place."""

import importlib

import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import connection

from accounts.models import BonkAccountLink
from players.models import BonkPlayer
from tests.factories import UserFactory

MOVE = importlib.import_module("accounts.migrations.0001_initial")


def test_link_keeps_its_original_table():
    """Changing this would make Django rename the real table."""
    assert BonkAccountLink._meta.db_table == "skins_bonkaccountlink"
    assert BonkAccountLink._meta.app_label == "accounts"


@pytest.mark.django_db
def test_constraint_and_index_names_are_unchanged():
    """They come from the table name, so they survive the move as they are."""
    with connection.cursor() as cursor:
        cursor.execute("select indexname from pg_indexes where tablename = 'skins_bonkaccountlink'")
        names = {row[0] for row in cursor.fetchall()}

    assert names == {
        "skins_bonkaccountlink_pkey",
        "skins_bonkaccountlink_user_id_bonk_player_id_01a276d9_uniq",
        "skins_bonkaccountlink_user_id_11465a49",
        "skins_bonkaccountlink_bonk_player_id_ef29c7f5",
    }


@pytest.mark.django_db
def test_migration_relabels_content_types_both_ways():
    ContentType.objects.filter(model__in=MOVE.MODELS).delete()
    old = {m: ContentType.objects.create(app_label="skins", model=m).id for m in MOVE.MODELS}

    MOVE.relabel_content_types(apps, None)

    moved = dict(
        ContentType.objects.filter(app_label="accounts", model__in=MOVE.MODELS).values_list(
            "model", "id"
        )
    )
    assert moved == old

    MOVE.unlabel_content_types(apps, None)

    assert set(
        ContentType.objects.filter(app_label="skins", model__in=MOVE.MODELS).values_list(
            "id", flat=True
        )
    ) == set(old.values())


@pytest.mark.django_db
def test_link_reads_through_its_new_home():
    user = UserFactory()
    player = BonkPlayer.objects.create(bonk_id=1, username="alpha")
    BonkAccountLink.objects.create(
        user=user, bonk_player=player, token_encrypted=BonkAccountLink.encrypt_token("t0k")
    )

    link = user.bonk_accounts.get()

    assert link.bonk_player == player
    assert link.bonk_token() == "t0k"
    assert player.linked_site_users.get() == link
