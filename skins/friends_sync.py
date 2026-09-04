# skins/friends_sync.py

from typing import Dict, Any, Iterable, Tuple, Set
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
import logging

from .models import BonkPlayer, Friendship, FriendCountHistory

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
def sync_friends_for_player(
    *,
    current_bonk_id: int | None,
    current_username: str,
    friends_json: Dict[str, Any],
) -> Dict[str, int]:
    """
    Upsert the current player + (friends + incoming requests),
    then upsert friendship edges ONLY for confirmed friends,
    and remove edges no longer present.

    Optimized to use a fixed, small number of database round-trips
    regardless of friend-list size, instead of one round-trip per
    friend. Bonk.io usernames are unique and permanent, so existing
    BonkPlayer rows never need a username update — only brand-new
    players are ever written.

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
    friends_list: Iterable[Dict[str, Any]] = friends_json.get("friends") or []
    raw_friend_ids: Set[int] = set()
    norm_friends = []
    skipped_names = 0
    for f in friends_list:
        try:
            fid = int(f.get("id"))
        except Exception:
            continue
        raw_friend_ids.add(fid)

        fname = f.get("name")
        if not isinstance(fname, str) or fname == "":
            skipped_names += 1
            logger.warning(
                "[bonkverse] friend id=%s had a missing/blank name in friends.php response", fid
            )
            continue
        norm_friends.append({"id": fid, "name": fname})

    # --------- Normalize friend requests -------------
    requests_list: Iterable[Dict[str, Any]] = friends_json.get("requests") or []
    norm_requests = []
    for r in requests_list:
        try:
            rid = int(r.get("id"))
        except Exception:
            continue
        rname = r.get("name")
        if not isinstance(rname, str) or rname == "":
            skipped_names += 1
            logger.warning(
                "[bonkverse] friend request id=%s had a missing/blank name in friends.php response", rid
            )
            continue
        norm_requests.append({"id": rid, "name": rname})

    # --------- Fast membership set, built ONCE ----------
    # Only ids with a usable name become "confirmed friend" edges this sync.
    # (not derived from `combined` — this is the fix for the O(n^2) bug)
    named_friend_ids: Set[int] = {f["id"] for f in norm_friends}

    # --------- Combine all players that need a BonkPlayer record ----------
    combined = norm_friends + norm_requests
    combined_by_id: dict[int, str] = {obj["id"]: obj["name"] for obj in combined}

    # --------- Upsert current player (single record, unchanged) ----------
    if current_bonk_id is None:
        current = BonkPlayer.objects.filter(username=current_username).first()
        if not current:
            current = BonkPlayer.objects.create(
                bonk_id=-1,
                username=current_username,
            )
    else:
        current, _ = BonkPlayer.objects.get_or_create(
            bonk_id=current_bonk_id,
            defaults={"username": current_username},
        )
        if current_username and current.username != current_username:
            # Bonk.io usernames are unique and permanent, so this should
            # never happen in steady state. Flag it instead of silently
            # relabeling the record.
            logger.warning(
                "[bonkverse] BonkPlayer username mismatch for bonk_id=%s (current player): "
                "stored=%r, login_response=%r",
                current_bonk_id, current.username, current_username,
            )
            current.username = current_username
            current.save(update_fields=["username", "updated_at"])

    # --------- Batch upsert: which players already exist? ----------
    # Usernames are unique+permanent on Bonk.io, so an existing BonkPlayer
    # never needs its username updated — we only ever need to know
    # WHICH ids exist, not fetch full rows to compare against.
    existing_ids: Set[int] = set(
        BonkPlayer.objects.filter(bonk_id__in=combined_by_id.keys())
        .values_list("bonk_id", flat=True)
    )

    to_create = [
        BonkPlayer(bonk_id=pid, username=pname)
        for pid, pname in combined_by_id.items()
        if pid not in existing_ids
    ]
    players_upserted = len(to_create)

    if to_create:
        BonkPlayer.objects.bulk_create(to_create, ignore_conflicts=True)

    # --------- Fetch PKs for everyone (existing + just-created) ----------
    friend_pks_by_bonkid: dict[int, int] = dict(
        BonkPlayer.objects.filter(bonk_id__in=combined_by_id.keys())
        .values_list("bonk_id", "pk")
    )

    # --------- Batch upsert: which friendship edges already exist? ----------
    edge_pairs = [
        _ordered_pair(current.pk, friend_pks_by_bonkid[fid])
        for fid in named_friend_ids
        if fid in friend_pks_by_bonkid
    ]

    existing_edge_pairs: Set[Tuple[int, int]] = set(
        Friendship.objects.filter(
            Q(player_low=current) | Q(player_high=current)
        ).values_list("player_low_id", "player_high_id")
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
            current.bonk_id, previous_count, reported_count,
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
    }