"""The player models after their move from skins/ to players/ (RFC-0001
Phase 5.4b): same tables and index names, content types relabelled in place."""

import importlib

import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType

from players.models import (
    BonkPlayer,
    FlashFriend,
    FlashFriendship,
    FriendCountHistory,
    Friendship,
)
from skins.models import BonkAccountLink

MOVE = importlib.import_module("players.migrations.0005_move_player_models_from_skins")


def test_models_keep_their_original_tables():
    """Changing these would make Django rename the real tables."""
    assert {
        model._meta.db_table
        for model in (BonkPlayer, Friendship, FriendCountHistory, FlashFriend, FlashFriendship)
    } == {
        "skins_bonkplayer",
        "skins_friendship",
        "skins_friendcounthistory",
        "skins_flashfriend",
        "skins_flashfriendship",
    }


def test_indexes_keep_their_database_names():
    """Unnamed, Django would name them after the new app and rename the real indexes."""
    assert {index.name for index in BonkPlayer._meta.indexes} == {
        "skins_bonkp_bonk_id_65d61a_idx",
        "skins_bonkp_usernam_420f86_idx",
    }
    assert {index.name for index in Friendship._meta.indexes} == {
        "skins_frien_player__25ca38_idx",
        "skins_frien_player__7d8c94_idx",
    }


def test_account_link_points_at_the_moved_player():
    assert BonkAccountLink._meta.get_field("bonk_player").related_model is BonkPlayer


@pytest.mark.django_db
def test_migration_relabels_content_types_both_ways():
    ContentType.objects.filter(app_label="players", model__in=MOVE.MODELS).delete()
    old = {m: ContentType.objects.create(app_label="skins", model=m).id for m in MOVE.MODELS}

    MOVE.relabel_content_types(apps, None)

    moved = dict(
        ContentType.objects.filter(app_label="players", model__in=MOVE.MODELS).values_list(
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
def test_friend_graph_reads_through_the_new_home():
    low = BonkPlayer.objects.create(bonk_id=1, username="alpha")
    high = BonkPlayer.objects.create(bonk_id=2, username="beta")
    Friendship.objects.create(player_low=low, player_high=high)

    assert low.edges_low.get().player_high == high
