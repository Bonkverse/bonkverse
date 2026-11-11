"""Tests for storing a bonk.io friend list (players/friends_sync.py).

Input is the typed list integrations/bonk_api.py returns (BonkFriend).
"""

from datetime import timedelta

import pytest
from django.db import connection
from django.db.models import Q
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from integrations.bonk_api import BonkFriend
from players.friends_sync import (
    EdgeChanges,
    PlayerUpsert,
    PruneResult,
    add_edges,
    prune_edges,
    read_friend_list,
    record_friend_count,
    sync_friends_for_player,
    upsert_current_player,
    upsert_players,
)
from players.models import BonkPlayer, FriendCountHistory, Friendship
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


def test_confirms_only_this_players_edges():
    """Regression: confirming edges matched any edge whose low end was in one
    list and high end in the other, so an edge between two of the player's
    friends was marked confirmed too."""
    long_ago = timezone.now() - timedelta(days=30)
    low = BonkPlayerFactory(bonk_id=2001, username="Low")  # pk below the player's
    BonkPlayerFactory(bonk_id=ME, username="Me Myself")
    high = BonkPlayerFactory(bonk_id=2002, username="High")  # pk above it
    between = Friendship.objects.create(
        player_low=low, player_high=high, last_confirmed_at=long_ago
    )

    _sync([BonkFriend(2001, "Low"), BonkFriend(2002, "High")])

    between.refresh_from_db()
    assert between.last_confirmed_at == long_ago
    me = BonkPlayer.objects.get(bonk_id=ME)
    mine = Friendship.objects.filter(Q(player_low=me) | Q(player_high=me))
    assert all(edge.last_confirmed_at > long_ago for edge in mine)
    assert mine.count() == 2


def test_query_count_does_not_grow_with_the_list():
    """Same number of queries for 3 friends as for 60 (each step is batched)."""

    def queries_for(n, offset):
        BonkPlayer.objects.all().delete()
        friends = [BonkFriend(offset + i, f"F{offset + i}") for i in range(n)]
        _sync(friends)  # first sync: creates rows and edges
        with CaptureQueriesContext(connection) as first:
            _sync(friends[:-1] + [BonkFriend(offset + n, "New")])  # one gone, one new
        return len(first)

    assert queries_for(3, 3000) == queries_for(60, 4000)


# ── each step ─────────────────────────────────────────────────────────────


class TestReadFriendList:
    def test_sorts_entries_by_what_they_get(self):
        reported = read_friend_list(
            [BonkFriend(1, "Pal"), BonkFriend(2, None)],
            [BonkFriend(3, "Asker"), BonkFriend(4, None)],
        )

        assert reported.friend_ids == {1, 2}  # counted, kept: named or not
        assert reported.named_friend_ids == {1}  # gets an edge
        assert reported.named_players == {1: "Pal", 3: "Asker"}  # gets a row
        assert reported.skipped_names == 2

    def test_keeps_names_exactly(self):
        reported = read_friend_list([BonkFriend(1, "  two spaces ")], [])

        assert reported.named_players == {1: "  two spaces "}


class TestUpsertCurrentPlayer:
    def test_creates_the_player(self):
        player = upsert_current_player(ME, "Me Myself")

        assert (player.bonk_id, player.username) == (ME, "Me Myself")

    def test_corrects_a_stale_stored_name(self):
        BonkPlayerFactory(bonk_id=ME, username="Me Myself")

        player = upsert_current_player(ME, " Me Myself ")

        assert BonkPlayer.objects.get(pk=player.pk).username == " Me Myself "

    def test_takes_over_a_replay_only_row_with_the_same_name(self):
        replay_row = BonkPlayer.objects.create(bonk_id=None, username="Me Myself")

        player = upsert_current_player(ME, "me myself")

        assert player.pk == replay_row.pk
        assert BonkPlayer.objects.count() == 1


class TestUpsertPlayers:
    def test_creates_new_rows_and_reports_their_pks(self):
        result = upsert_players({2001: "A", 2002: "B"})

        assert result.created == 2
        assert set(result.pks) == {2001, 2002}
        assert result.pks[2001] == BonkPlayer.objects.get(bonk_id=2001).pk

    def test_corrects_names_and_moves_updated_at(self):
        old = BonkPlayerFactory(bonk_id=2001, username="Old")
        before = BonkPlayer.objects.get(pk=old.pk).updated_at

        result = upsert_players({2001: "New"})

        row = BonkPlayer.objects.get(pk=old.pk)
        assert (row.username, result.created) == ("New", 0)
        assert row.updated_at > before  # the replay site picks the name up
        assert result.corrections == [
            {"bonk_id": 2001, "old_username": "Old", "new_username": "New"}
        ]

    def test_nothing_to_do(self):
        assert upsert_players({}) == PlayerUpsert(created=0)


class TestAddEdges:
    def test_adds_missing_edges_and_confirms_all(self):
        me = BonkPlayerFactory(bonk_id=ME)
        known, new = BonkPlayerFactory(bonk_id=2001), BonkPlayerFactory(bonk_id=2002)
        long_ago = timezone.now() - timedelta(days=30)
        Friendship.objects.create(player_low=me, player_high=known, last_confirmed_at=long_ago)

        result = add_edges(me, [known.pk, new.pk])

        assert result == EdgeChanges(added=1, touched=2)
        assert Friendship.objects.filter(last_confirmed_at__lte=long_ago).count() == 0
        assert _friend_ids() == {2001, 2002}

    def test_no_friends(self):
        me = BonkPlayerFactory(bonk_id=ME)

        assert add_edges(me, []) == EdgeChanges(added=0, touched=0)


class TestPruneEdges:
    def _with_friends(self, *bonk_ids):
        me = BonkPlayerFactory(bonk_id=ME)
        for bonk_id in bonk_ids:
            Friendship.objects.create(player_low=me, player_high=BonkPlayerFactory(bonk_id=bonk_id))
        return me

    def test_removes_friends_not_reported(self):
        me = self._with_friends(2001, 2002, 2003, 2004)

        result = prune_edges(me, frozenset({2001, 2002, 2003}))

        assert result == PruneResult(removed=1, suspicious_drop=False)
        assert _friend_ids() == {2001, 2002, 2003}

    def test_a_big_drop_removes_nothing(self):
        me = self._with_friends(2001, 2002, 2003, 2004)

        result = prune_edges(me, frozenset({2001}))

        assert result == PruneResult(removed=0, suspicious_drop=True)
        assert len(_friend_ids()) == 4

    def test_small_lists_are_never_suspicious(self):
        me = self._with_friends(2001, 2002)

        assert prune_edges(me, frozenset()) == PruneResult(removed=2, suspicious_drop=False)


class TestRecordFriendCount:
    def test_writes_history_when_the_count_changes(self):
        me = BonkPlayerFactory(bonk_id=ME, last_friend_count=3)

        assert record_friend_count(me, 4) is True
        assert record_friend_count(me, 4) is False

        assert list(
            FriendCountHistory.objects.filter(player=me).values_list("count", flat=True)
        ) == [4]
        assert BonkPlayer.objects.get(pk=me.pk).last_friend_count == 4
