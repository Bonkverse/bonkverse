"""Storing a player's bonk.io friend list (friends.php) as Friendship edges.

Owns: syncing a linked player's friends (sync_friends_for_link, run by the
sync_friends worker task in players/tasks.py after login), upserting BonkPlayer rows
for friends and requests, adding and pruning Friendship edges, and
friend-count history.
Does not own: talking to bonk.io (integrations/bonk_api.py), queueing the
sync (players.services.queue_friend_sync, called by skins/sign_in.py) or Flash-era friends (flash_friends_sync.py).

A sync is a fixed list of steps, each its own function with its own tests
(tests/test_friends_sync.py), run in this order by sync_friends_for_player:

1. read_friend_list: what bonk.io reported, with unnamed entries set aside.
2. upsert_current_player: the player whose list it is.
3. upsert_players: a BonkPlayer row for every named friend and request,
   correcting stored names that differ from bonk.io's.
4. add_edges: a Friendship edge for every named friend, confirmed now.
5. prune_edges: remove edges for friends no longer listed, unless the list
   shrank so much it looks like a bad reply.
6. record_friend_count: the count and its history, unless the list looked bad.

Names are kept exactly as bonk.io sends them (never trimmed). The number of
database queries doesn't grow with the size of the friend list.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from integrations.bonk_api import BonkFriend, get_client

from skins.events import log_event
from skins.models import BonkAccountLink
from .models import BonkPlayer, FriendCountHistory, Friendship

logger = logging.getLogger(__name__)

# sync_friends_for_link's error when the link has no usable stored token.
NO_TOKEN = "no_token"

# A sync only prunes an edge for an id that's absent from bonk.io's reply. If
# the number of friends reported drops this sharply from what's stored, that's
# more likely a partial reply than a mass unfriending, so the sync keeps every
# edge and doesn't record the count.
MIN_FRIENDS_FOR_DROP_CHECK = 3
SUSPICIOUS_DROP_RATIO = 0.5  # a >50% drop from the stored count is flagged


@dataclass(frozen=True)
class LinkSyncResult:
    """What one friend sync did: counts when it ran, or why it didn't."""

    stats: dict | None = None
    error: str | None = None  # a BonkError code, or NO_TOKEN


def sync_friends_for_link(link: BonkAccountLink) -> LinkSyncResult:
    """Fetch the linked player's bonk.io friends and store them.

    Logs a `friends_synced` event with the counts; the profile page's toast
    polls /api/friends-sync-status/ for that event. Safe to run twice: the
    stored list is computed from what bonk.io returns now.

    Args:
        link: an account link with its user and bonk_player loaded.

    Returns:
        LinkSyncResult with `stats` on success, or `error` (a BonkError code,
        or NO_TOKEN) when bonk.io didn't give a friend list.
    """
    bonk_token = link.bonk_token()
    if not bonk_token:
        logger.warning("friends sync skipped: no usable token on account link %s", link.id)
        return LinkSyncResult(error=NO_TOKEN)

    result = get_client().get_friends(bonk_token)
    if not result.ok:
        logger.warning("friends sync skipped: %s (bonk_error=%s)", result.error, result.bonk_error)
        return LinkSyncResult(error=result.error)

    stats = sync_friends_for_player(
        current_bonk_id=link.bonk_player.bonk_id,
        current_username=link.bonk_player.username,
        friends=result.friends,
        requests=result.requests,
    )
    log_event(link.user, "friends_synced", **stats)
    return LinkSyncResult(stats=stats)


def sync_friends_for_player(
    *,
    current_bonk_id: int | None,
    current_username: str,
    friends: Iterable[BonkFriend],
    requests: Iterable[BonkFriend] = (),
) -> dict:
    """Store one player's friend list, as bonk.io reported it.

    Friends become Friendship edges; friend requests only get BonkPlayer rows.
    Edges for friends no longer listed are removed, unless the list looks
    like a bad reply (see prune_edges).

    Args:
        current_bonk_id: the player's bonk.io id; None matches by name.
        current_username: the player's name, exactly as bonk.io spells it.
        friends: confirmed friends from friends.php.
        requests: incoming friend requests from friends.php.

    Returns:
        Counts for the logs and the profile toast: players_upserted,
        friends_now, added_edges, removed_edges, edges_touched,
        skipped_names, suspicious_drop, corrected_usernames, corrected_count.
    """
    reported = read_friend_list(friends, requests)
    current = upsert_current_player(current_bonk_id, current_username)
    players = upsert_players(reported.named_players)
    friend_pks = [players.pks[i] for i in reported.named_friend_ids if i in players.pks]
    edges = add_edges(current, friend_pks)
    pruned = prune_edges(current, reported.friend_ids)
    if not pruned.suspicious_drop:
        record_friend_count(current, len(reported.friend_ids))

    return {
        "players_upserted": players.created,
        "friends_now": len(reported.friend_ids),
        "added_edges": edges.added,
        "removed_edges": pruned.removed,
        "edges_touched": edges.touched,
        "skipped_names": reported.skipped_names,
        "suspicious_drop": pruned.suspicious_drop,
        # e.g. [{"bonk_id": 1834575, "old_username": "Name", "new_username": " Name"}]
        "corrected_usernames": players.corrections,
        "corrected_count": len(players.corrections),
    }


# ── 1. read the list ────────────────────────────────────────────────────


@dataclass(frozen=True)
class FriendList:
    """bonk.io's reply, ready to store."""

    # Every friend id reported, named or not: the friend count, and the ids
    # whose edges are kept.
    friend_ids: frozenset[int]
    # Friends with a usable name: these get an edge.
    named_friend_ids: frozenset[int]
    # {bonk_id: name} for friends and requests with a usable name: these get
    # a BonkPlayer row.
    named_players: dict[int, str]
    # Entries without a usable name (not stored, not invented).
    skipped_names: int


def read_friend_list(friends: Iterable[BonkFriend], requests: Iterable[BonkFriend]) -> FriendList:
    """Sort bonk.io's entries into what gets a row, an edge, or only a count.

    An entry without a name gets no row and no new edge (no made-up
    "player_<id>" names), but a friend without one still counts and keeps
    their existing edge.
    """
    friend_ids: set[int] = set()
    named_friend_ids: set[int] = set()
    named_players: dict[int, str] = {}
    skipped = 0
    for kind, entries in (("friend", friends), ("friend request", requests)):
        for entry in entries:
            if kind == "friend":
                friend_ids.add(entry.bonk_id)
            if entry.name is None:
                skipped += 1
                logger.warning(
                    "%s id=%s had a missing/blank name in friends.php response",
                    kind,
                    entry.bonk_id,
                )
                continue
            named_players[entry.bonk_id] = entry.name
            if kind == "friend":
                named_friend_ids.add(entry.bonk_id)
    return FriendList(
        friend_ids=frozenset(friend_ids),
        named_friend_ids=frozenset(named_friend_ids),
        named_players=named_players,
        skipped_names=skipped,
    )


# ── 2. the player ───────────────────────────────────────────────────────


def upsert_current_player(bonk_id: int | None, username: str) -> BonkPlayer:
    """The BonkPlayer whose list this is, created if new.

    With an id, the stored name is corrected to bonk.io's spelling (bonk.io
    names are permanent, so a difference means our copy is stale, e.g.
    stripped by an old bug). Without one, it's matched by name,
    case-insensitively (docs/bonk/accounts.md).
    """
    if bonk_id is None:
        player = BonkPlayer.objects.filter(username__iexact=username).order_by("pk").first()
        return player or BonkPlayer.objects.create(bonk_id=-1, username=username)

    adopt_replay_names({bonk_id: username})
    player, _ = BonkPlayer.objects.get_or_create(bonk_id=bonk_id, defaults={"username": username})
    if username and player.username != username:
        logger.warning(
            "BonkPlayer username mismatch for bonk_id=%s (current player): "
            "stored=%r, live=%r; correcting stored value",
            bonk_id,
            player.username,
            username,
        )
        player.username = username
        player.save(update_fields=["username", "updated_at"])
    return player


# ── 3. everyone in the list ─────────────────────────────────────────────


@dataclass(frozen=True)
class PlayerUpsert:
    created: int
    corrections: list[dict] = field(default_factory=list)
    pks: dict[int, int] = field(default_factory=dict)  # {bonk_id: BonkPlayer pk}


def upsert_players(players: dict[int, str]) -> PlayerUpsert:
    """A BonkPlayer row for each {bonk_id: name}, with bonk.io's spelling.

    Replay-only rows with the same name get the id first
    (adopt_replay_names), so an account keeps one row. Stored names that
    differ are corrected, and `updated_at` moves so the replay site picks up
    the new name (players.replay_sync pushes rows changed since its last run).
    """
    adopt_replay_names(players)
    stored = {
        bonk_id: (pk, name)
        for pk, bonk_id, name in BonkPlayer.objects.filter(bonk_id__in=players).values_list(
            "pk", "bonk_id", "username"
        )
    }

    new = [
        BonkPlayer(bonk_id=bonk_id, username=name)
        for bonk_id, name in players.items()
        if bonk_id not in stored
    ]
    if new:
        BonkPlayer.objects.bulk_create(new, ignore_conflicts=True)

    corrections = []
    renamed = []
    now = timezone.now()
    for bonk_id, live_name in players.items():
        if bonk_id not in stored:
            continue
        pk, stored_name = stored[bonk_id]
        if stored_name == live_name:
            continue
        logger.warning(
            "correcting stale username for bonk_id=%s: stored=%r live=%r",
            bonk_id,
            stored_name,
            live_name,
        )
        renamed.append(BonkPlayer(pk=pk, username=live_name, updated_at=now))
        corrections.append(
            {"bonk_id": bonk_id, "old_username": stored_name, "new_username": live_name}
        )
    if renamed:
        BonkPlayer.objects.bulk_update(renamed, ["username", "updated_at"], batch_size=200)

    pks = dict(BonkPlayer.objects.filter(bonk_id__in=players).values_list("bonk_id", "pk"))
    return PlayerUpsert(created=len(new), corrections=corrections, pks=pks)


# ── 4. edges for the friends listed ─────────────────────────────────────


@dataclass(frozen=True)
class EdgeChanges:
    added: int
    touched: int  # every edge confirmed this sync, new or not


def _ordered_pair(a_id: int, b_id: int) -> tuple[int, int]:
    """An edge's (player_low, player_high): sorted by pk, not bonk_id."""
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


def add_edges(player: BonkPlayer, friend_pks: Iterable[int]) -> EdgeChanges:
    """An edge between `player` and each friend, with last_confirmed_at = now."""
    now = timezone.now()
    pairs = [_ordered_pair(player.pk, pk) for pk in friend_pks]
    if not pairs:
        return EdgeChanges(added=0, touched=0)

    existing = set(
        Friendship.objects.filter(Q(player_low=player) | Q(player_high=player)).values_list(
            "player_low_id", "player_high_id"
        )
    )
    new = [
        Friendship(player_low_id=low, player_high_id=high, last_confirmed_at=now)
        for low, high in pairs
        if (low, high) not in existing
    ]
    if new:
        Friendship.objects.bulk_create(new, ignore_conflicts=True)

    # Only this player's edges. (Filtering low in one list and high in the
    # other also matched edges between two of their friends.)
    Friendship.objects.filter(
        Q(player_low=player, player_high_id__in=[high for _, high in pairs])
        | Q(player_high=player, player_low_id__in=[low for low, _ in pairs])
    ).update(last_confirmed_at=now)
    return EdgeChanges(added=len(new), touched=len(pairs))


# ── 5. edges for friends no longer listed ───────────────────────────────


@dataclass(frozen=True)
class PruneResult:
    removed: int
    suspicious_drop: bool


def prune_edges(player: BonkPlayer, reported_ids: frozenset[int]) -> PruneResult:
    """Remove `player`'s edges to friends missing from `reported_ids`.

    `reported_ids` is every friend id bonk.io listed, named or not, so a
    friend whose name couldn't be read keeps their edge. When the list
    reports far fewer friends than are stored (MIN_FRIENDS_FOR_DROP_CHECK,
    SUSPICIOUS_DROP_RATIO), nothing is removed and the drop is logged.
    Runs after add_edges, so the stored count includes edges added this sync.
    """
    stored_ids = set()
    for low_id, low_bonk, high_bonk in Friendship.objects.filter(
        Q(player_low=player) | Q(player_high=player)
    ).values_list("player_low_id", "player_low__bonk_id", "player_high__bonk_id"):
        stored_ids.add(high_bonk if low_id == player.pk else low_bonk)

    stored, reported = len(stored_ids), len(reported_ids)
    if stored >= MIN_FRIENDS_FOR_DROP_CHECK and reported < stored * (1 - SUSPICIOUS_DROP_RATIO):
        logger.warning(
            "suspicious friend-count drop for bonk_id=%s: had %s stored friendships, "
            "this sync only reported %s; skipping edge removal for this sync",
            player.bonk_id,
            stored,
            reported,
        )
        return PruneResult(removed=0, suspicious_drop=True)

    gone = stored_ids - reported_ids
    if not gone:
        return PruneResult(removed=0, suspicious_drop=False)
    gone_pks = list(BonkPlayer.objects.filter(bonk_id__in=gone).values_list("pk", flat=True))
    removed, _ = Friendship.objects.filter(
        Q(player_low=player, player_high_id__in=gone_pks)
        | Q(player_high=player, player_low_id__in=gone_pks)
    ).delete()
    return PruneResult(removed=removed, suspicious_drop=False)


# ── 6. the count ────────────────────────────────────────────────────────


def record_friend_count(player: BonkPlayer, count: int) -> bool:
    """Store `count` on the player and in its history, if it changed.

    Returns whether anything was written. Callers skip this for a list that
    looked like a bad reply, so the history graph doesn't get a false dip.
    """
    if player.last_friend_count == count:
        return False
    player.last_friend_count = count
    player.last_seen = timezone.now()
    player.save(update_fields=["last_friend_count", "last_seen", "updated_at"])
    FriendCountHistory.objects.create(player=player, count=count)
    return True


# ── shared with login and the replay sync ───────────────────────────────


@transaction.atomic
def adopt_replay_names(players: dict[int, str]) -> set[int]:
    """Give replay-only rows their DBID. `players` is {bonk_id: username} as
    bonk.io just reported them. A name copied in from replays
    (players.replay_sync, bonk_id empty) with one of these names gets that
    bonk_id, so the account keeps one row instead of two. Returns the
    bonk_ids adopted this way; callers create rows only for the rest.
    bonk.io names are unique case-insensitively (docs/bonk/accounts.md)."""
    by_name = {name.lower(): bonk_id for bonk_id, name in players.items() if name}
    if not by_name:
        return set()
    taken = set(
        BonkPlayer.objects.filter(bonk_id__in=list(players)).values_list("bonk_id", flat=True)
    )
    adopted: set[int] = set()
    now = timezone.now()
    rows = (
        BonkPlayer.objects.annotate(lname=Lower("username"))
        .filter(bonk_id__isnull=True, lname__in=list(by_name))
        .values_list("pk", "lname")
    )
    for pk, lname in rows:
        bonk_id = by_name[lname]
        if bonk_id in taken or bonk_id in adopted:
            continue  # a row with this ID already exists; leave the copy alone
        BonkPlayer.objects.filter(pk=pk, bonk_id__isnull=True).update(
            bonk_id=bonk_id, username=players[bonk_id], updated_at=now
        )
        adopted.add(bonk_id)
    return adopted
