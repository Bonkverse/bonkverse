"""Storing a player's bonk.io friend list (friends.php) as Friendship edges.

Owns: upserting BonkPlayer rows for friends and requests, adding and pruning
Friendship edges, and friend-count history.
Does not own: fetching the list from bonk.io (integrations/bonk_api.py) or
Flash-era friends (flash_friends_sync.py).
"""

import logging
from collections.abc import Iterable
from typing import Dict, List, Set, Tuple

from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from integrations.bonk_api import BonkFriend

from .models import BonkPlayer, FriendCountHistory, Friendship

logger = logging.getLogger(__name__)


def _ordered_pair(a_id: int, b_id: int) -> Tuple[int, int]:
    """Return tuple sorted ascending (by PK, not bonk_id)."""
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


# A sync only prunes an existing Friendship edge for an id that's genuinely
# absent from this sync's payload. If the *total* number of ids reported
# drops this sharply from what we already had on file, that's more likely a
# degraded/partial API response than a real mass-unfriending — so we skip
# the prune entirely for that sync and log it instead of trusting the
# smaller list.
MIN_FRIENDS_FOR_DROP_CHECK = 3
SUSPICIOUS_DROP_RATIO = 0.5  # a >50% drop from the previous count is flagged


@transaction.atomic
def adopt_replay_names(players: dict[int, str]) -> Set[int]:
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
    adopted: Set[int] = set()
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


def sync_friends_for_player(
    *,
    current_bonk_id: int | None,
    current_username: str,
    friends: Iterable[BonkFriend],
    requests: Iterable[BonkFriend] = (),
) -> Dict[str, int]:
    """
    Upsert the current player + (friends + incoming requests),
    then upsert friendship edges ONLY for confirmed friends,
    and remove edges no longer present.

    Optimized to use a fixed, small number of database round-trips
    regardless of friend-list size, instead of one round-trip per
    friend.

    Bonk.io usernames ARE unique and permanent on Bonk.io's side, but a
    pre-fix bug on our side (since removed — see f9de5d9) used to strip
    leading/trailing whitespace before storing a BonkPlayer's username,
    so some existing rows may still hold a stale, stripped value from
    before that fix landed. Every sync now compares this payload's live
    username against whatever's already stored for that bonk_id and
    self-heals the stored value on a mismatch — this is the same
    self-healing login.py already does for the *current* player, just
    generalized to every friend/request in the payload. Since bonk_id is
    the real unique identity and BonkPlayer is the single row every
    Friendship FK points to, correcting it here fixes the name
    everywhere it's displayed (search, other users' friend lists, etc.)
    with nothing else to update.

    Names are preserved exactly as bonk.io sends them — no trimming —
    and a friend/request entry with a missing or blank name is skipped
    for BonkPlayer/edge *creation* rather than given a fabricated
    "player_<id>" username. Its id is still counted as "present" for
    pruning purposes, though, so an already-known friend is never
    deleted just because this particular sync couldn't read their name.

    Returns simple stats for UI.
    """
    now = timezone.now()

    # --------- Normalize confirmed friends ----------
    # The client already dropped entries whose id isn't a number.
    raw_friend_ids: Set[int] = set()
    norm_friends = []
    skipped_names = 0
    for f in friends:
        raw_friend_ids.add(f.bonk_id)
        if f.name is None:
            skipped_names += 1
            logger.warning(
                "[bonkverse] friend id=%s had a missing/blank name in friends.php response",
                f.bonk_id,
            )
            continue
        norm_friends.append({"id": f.bonk_id, "name": f.name})

    # --------- Normalize friend requests -------------
    norm_requests = []
    for r in requests:
        if r.name is None:
            skipped_names += 1
            logger.warning(
                "[bonkverse] friend request id=%s had a missing/blank name in friends.php response",
                r.bonk_id,
            )
            continue
        norm_requests.append({"id": r.bonk_id, "name": r.name})

    # --------- Fast membership set, built ONCE ----------
    # Only ids with a usable name become "confirmed friend" edges this sync.
    # (not derived from `combined` — this is the fix for the O(n^2) bug)
    named_friend_ids: Set[int] = {f["id"] for f in norm_friends}

    # --------- Combine all players that need a BonkPlayer record ----------
    combined = norm_friends + norm_requests
    combined_by_id: dict[int, str] = {obj["id"]: obj["name"] for obj in combined}

    # --------- Upsert current player (single record, unchanged) ----------
    if current_bonk_id is None:
        # bonk.io names are unique case-insensitively (docs/bonk/accounts.md).
        current = (
            BonkPlayer.objects.filter(username__iexact=current_username).order_by("pk").first()
        )
        if not current:
            current = BonkPlayer.objects.create(
                bonk_id=-1,
                username=current_username,
            )
    else:
        adopt_replay_names({current_bonk_id: current_username})
        current, _ = BonkPlayer.objects.get_or_create(
            bonk_id=current_bonk_id,
            defaults={"username": current_username},
        )
        if current_username and current.username != current_username:
            # Bonk.io usernames are unique and permanent, so a mismatch
            # here means OUR stored value is stale (e.g. a pre-fix
            # whitespace-stripped row) rather than a real rename.
            # Self-heal it rather than just logging it.
            logger.warning(
                "[bonkverse] BonkPlayer username mismatch for bonk_id=%s (current player): "
                "stored=%r, live=%r — correcting stored value",
                current_bonk_id,
                current.username,
                current_username,
            )
            current.username = current_username
            current.save(update_fields=["username", "updated_at"])

    # --------- Batch upsert: which players already exist, and are their ----------
    # --------- stored usernames still accurate? (single query, no added ----------
    # --------- round trip vs. the old existing-ids-only lookup) ----------
    #
    # bonk_id is the real, permanent identity. username can still be wrong
    # on OUR side for a row written before the whitespace-strip fix — so
    # unlike the old comment here, an existing row's username IS worth
    # comparing against this sync's live value. Pulling (pk, bonk_id,
    # username) instead of bonk_id alone costs nothing extra: it's the
    # same rows, one more column, same single query.
    adopt_replay_names(combined_by_id)
    existing_map: dict[int, tuple[int, str]] = {
        bonk_id: (pk, username)
        for pk, bonk_id, username in BonkPlayer.objects.filter(
            bonk_id__in=combined_by_id.keys()
        ).values_list("pk", "bonk_id", "username")
    }
    existing_ids: Set[int] = set(existing_map.keys())

    to_create = [
        BonkPlayer(bonk_id=pid, username=pname)
        for pid, pname in combined_by_id.items()
        if pid not in existing_ids
    ]
    players_upserted = len(to_create)

    if to_create:
        BonkPlayer.objects.bulk_create(to_create, ignore_conflicts=True)

    # --------- Detect + self-heal stale usernames on existing rows ----------
    # Only runs a query when there's actually something to fix — in
    # steady state (everything already correct) this list is empty and
    # no extra round trip happens at all.
    corrections: List[Dict[str, str]] = []
    to_update = []
    for bonk_id, live_name in combined_by_id.items():
        hit = existing_map.get(bonk_id)
        if hit is None:
            continue
        pk, stored_name = hit
        if stored_name != live_name:
            logger.warning(
                "[bonkverse] correcting stale username for bonk_id=%s: stored=%r live=%r",
                bonk_id,
                stored_name,
                live_name,
            )
            to_update.append(BonkPlayer(pk=pk, username=live_name, updated_at=timezone.now()))
            corrections.append(
                {
                    "bonk_id": bonk_id,
                    "old_username": stored_name,
                    "new_username": live_name,
                }
            )

    if to_update:
        # updated_at too, so the new name reaches the replay site
        # (players.replay_sync pushes rows changed since its last run).
        BonkPlayer.objects.bulk_update(to_update, ["username", "updated_at"], batch_size=200)

    # --------- Fetch PKs for everyone (existing + just-created) ----------
    friend_pks_by_bonkid: dict[int, int] = dict(
        BonkPlayer.objects.filter(bonk_id__in=combined_by_id.keys()).values_list("bonk_id", "pk")
    )

    # --------- Batch upsert: which friendship edges already exist? ----------
    edge_pairs = [
        _ordered_pair(current.pk, friend_pks_by_bonkid[fid])
        for fid in named_friend_ids
        if fid in friend_pks_by_bonkid
    ]

    existing_edge_pairs: Set[Tuple[int, int]] = set(
        Friendship.objects.filter(Q(player_low=current) | Q(player_high=current)).values_list(
            "player_low_id", "player_high_id"
        )
    )

    new_edges = [
        Friendship(player_low_id=lo, player_high_id=hi, last_confirmed_at=now)
        for lo, hi in edge_pairs
        if (lo, hi) not in existing_edge_pairs
    ]
    added_edges = len(new_edges)

    if new_edges:
        Friendship.objects.bulk_create(new_edges, ignore_conflicts=True)

    # Refresh last_confirmed_at on every edge we touched this sync
    # (both newly created and already-existing ones)
    touched_lo_ids = [p[0] for p in edge_pairs]
    touched_hi_ids = [p[1] for p in edge_pairs]
    touched_edges = len(edge_pairs)

    if edge_pairs:
        Friendship.objects.filter(
            player_low_id__in=touched_lo_ids,
            player_high_id__in=touched_hi_ids,
        ).update(last_confirmed_at=now)

    # --------- Remove edges that no longer exist ----------
    existing_edges = Friendship.objects.filter(
        Q(player_low=current) | Q(player_high=current)
    ).select_related("player_low", "player_high")

    existing_friend_ids: Set[int] = set()
    for e in existing_edges:
        other = e.player_high if e.player_low_id == current.pk else e.player_low
        existing_friend_ids.add(other.bonk_id)

    # An id counts as "still present" here if it showed up anywhere in this
    # sync's friends list at all — even if its name was unusable and it
    # therefore didn't get a fresh edge above. Only ids genuinely absent
    # from the payload are candidates for removal.
    to_remove = existing_friend_ids - raw_friend_ids
    removed_edges = 0

    previous_count = len(existing_friend_ids)
    reported_count = len(raw_friend_ids)
    suspicious_drop = (
        previous_count >= MIN_FRIENDS_FOR_DROP_CHECK
        and reported_count < previous_count * (1 - SUSPICIOUS_DROP_RATIO)
    )

    if suspicious_drop:
        logger.warning(
            "[bonkverse] suspicious friend-count drop for bonk_id=%s: "
            "had %s stored friendships, this sync only reported %s — "
            "skipping edge removal for this sync",
            current.bonk_id,
            previous_count,
            reported_count,
        )
    elif to_remove:
        to_remove_pks = list(
            BonkPlayer.objects.filter(bonk_id__in=to_remove).values_list("pk", flat=True)
        )
        if to_remove_pks:
            deleted, _ = Friendship.objects.filter(
                Q(player_low=current, player_high_id__in=to_remove_pks)
                | Q(player_high=current, player_low_id__in=to_remove_pks)
            ).delete()
            removed_edges = deleted

    # --------- Save friend count history ----------
    # `reported_count` (not just the named subset) is the true friend
    # count — an unusable name shouldn't make someone disappear from the
    # count, only from getting a fresh/renamed BonkPlayer record this sync.
    # Skip recording a count from a sync we've already flagged as
    # suspicious, so a bad snapshot doesn't pollute the history graph.
    friends_now = reported_count
    if not suspicious_drop and current.last_friend_count != friends_now:
        current.last_friend_count = friends_now
        current.last_seen = now
        current.save(update_fields=["last_friend_count", "last_seen", "updated_at"])
        FriendCountHistory.objects.create(player=current, count=friends_now)

    # --------- Return stats ----------
    return {
        "players_upserted": players_upserted,
        "friends_now": friends_now,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
        "edges_touched": touched_edges,
        "skipped_names": skipped_names,
        "suspicious_drop": suspicious_drop,
        "corrected_usernames": corrections,  # e.g. [{"bonk_id": 1834575, "old_username": "Motionless in white", "new_username": " Motionless in white"}]
        "corrected_count": len(corrections),
    }
