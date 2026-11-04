"""Tests for storing a bonk.io friend list (skins/friends_sync.py).

Input is the typed list integrations/bonk_api.py returns (BonkFriend).
"""

import pytest

from integrations.bonk_api import BonkFriend
from skins.friends_sync import sync_friends_for_player
from skins.models import BonkPlayer, Friendship
from tests.factories import BonkPlayerFactory

pytestmark = pytest.mark.django_db

ME = 1_000_001


def _sync(friends, requests=(), **kwargs):
    return sync_friends_for_player(
        current_bonk_id=kwargs.get("bonk_id", ME),
        current_username=kwargs.get("username", "Me Myself"),
        friends=friends,
        requests=requests,
    )


def _friend_ids():
    me = BonkPlayer.objects.get(bonk_id=ME)
    edges = Friendship.objects.filter(player_low=me) | Friendship.objects.filter(player_high=me)
    return {(e.player_high if e.player_low_id == me.pk else e.player_low).bonk_id for e in edges}


def test_creates_players_and_edges_for_friends_only():
    stats = _sync(
        [BonkFriend(2001, "Pal"), BonkFriend(2002, " Spaced ")],
        requests=[BonkFriend(2003, "Asker")],
    )

    assert _friend_ids() == {2001, 2002}
    assert BonkPlayer.objects.get(bonk_id=2002).username == " Spaced "  # never trimmed
    assert BonkPlayer.objects.filter(bonk_id=2003).exists()  # request: player, no edge
    assert stats["friends_now"] == 2


def test_friend_without_name_still_counts_and_is_not_pruned():
    _sync([BonkFriend(2001, "Pal"), BonkFriend(2002, "Other")])

    stats = _sync([BonkFriend(2001, None), BonkFriend(2002, "Other")])

    assert _friend_ids() == {2001, 2002}
    assert stats["skipped_names"] == 1
    assert stats["friends_now"] == 2


def test_removes_friends_no_longer_listed():
    _sync([BonkFriend(2001, "A"), BonkFriend(2002, "B")])

    stats = _sync([BonkFriend(2001, "A")])

    assert _friend_ids() == {2001}
    assert stats["removed_edges"] == 1


def test_suspicious_drop_skips_pruning():
    _sync([BonkFriend(2000 + i, f"F{i}") for i in range(10)])

    stats = _sync([BonkFriend(2000, "F0")])

    assert stats["suspicious_drop"] is True
    assert len(_friend_ids()) == 10


def test_corrects_stale_stored_name():
    BonkPlayerFactory(bonk_id=2001, username="Stripped")

    stats = _sync([BonkFriend(2001, " Stripped ")])

    assert BonkPlayer.objects.get(bonk_id=2001).username == " Stripped "
    assert stats["corrected_count"] == 1


def test_without_bonk_id_matches_current_player_case_insensitively():
    existing = BonkPlayerFactory(bonk_id=ME, username="Me Myself")

    sync_friends_for_player(
        current_bonk_id=None, current_username="me myself", friends=[BonkFriend(2001, "Pal")]
    )

    assert BonkPlayer.objects.filter(username__iexact="me myself").count() == 1
    assert _friend_ids() == {2001}
    assert existing.pk == BonkPlayer.objects.get(bonk_id=ME).pk
