"""Flash-era friends from the login reply (players/flash_friends_sync.py)."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from players.flash_friends_sync import read_legacy_friends, sync_flash_friends_for_user
from players.models import FlashFriend, FlashFriendship
from tests.factories import BonkPlayerFactory, UserFactory

pytestmark = pytest.mark.django_db


def _names(user):
    return set(user.flash_friendships.values_list("flash_friend__name", flat=True))


class TestReadLegacyFriends:
    def test_keeps_names_exactly_and_drops_empty_segments(self):
        assert read_legacy_friends("#Old Pal## Spaced #   #") == (["Old Pal", " Spaced ", "   "], 3)

    def test_nothing(self):
        assert read_legacy_friends("") == ([], 0)
        assert read_legacy_friends(None) == ([], 0)


def test_links_each_name():
    user = UserFactory()

    stats = sync_flash_friends_for_user(user=user, legacy_friends="Old Pal# Spaced")

    assert _names(user) == {"Old Pal", " Spaced"}
    assert stats == {"flash_added": 2, "flash_skipped": 0, "flash_total": 2}


def test_second_login_adds_only_new_names():
    user = UserFactory()
    sync_flash_friends_for_user(user=user, legacy_friends="A#B")

    stats = sync_flash_friends_for_user(user=user, legacy_friends="A#B#C")

    assert _names(user) == {"A", "B", "C"}
    assert stats == {"flash_added": 1, "flash_skipped": 2, "flash_total": 3}


def test_shares_rows_between_users():
    first, second = UserFactory(), UserFactory()

    sync_flash_friends_for_user(user=first, legacy_friends="Shared")
    sync_flash_friends_for_user(user=second, legacy_friends="Shared")

    assert FlashFriend.objects.filter(name="Shared").count() == 1
    assert FlashFriendship.objects.count() == 2


def test_a_name_with_resolved_and_unresolved_rows_uses_the_oldest():
    """Regression: get_or_create(name=...) raised MultipleObjectsReturned when a
    name had both a resolved and an unresolved row, losing the whole list."""
    resolved = FlashFriend.objects.create(name="Both", bonk_player=BonkPlayerFactory())
    FlashFriend.objects.create(name="Both")
    user = UserFactory()

    stats = sync_flash_friends_for_user(user=user, legacy_friends="Both#Other")

    assert stats["flash_added"] == 2
    assert user.flash_friendships.filter(flash_friend=resolved).exists()


def test_repeated_name_links_once():
    user = UserFactory()

    stats = sync_flash_friends_for_user(user=user, legacy_friends="A#A")

    assert FlashFriendship.objects.filter(user=user).count() == 1
    assert stats == {"flash_added": 1, "flash_skipped": 1, "flash_total": 2}


def test_query_count_does_not_grow_with_the_list():
    """The login request waits for this; 300 names cost what 3 do."""

    def queries_for(names):
        user = UserFactory()
        with CaptureQueriesContext(connection) as queries:
            sync_flash_friends_for_user(user=user, legacy_friends="#".join(names))
        return len(queries)

    assert queries_for([f"few{i}" for i in range(3)]) == queries_for(
        [f"many{i}" for i in range(300)]
    )
