# # skins/friends_sync.py

# from typing import Dict, Any, Iterable, Tuple, Set
# from django.db import transaction
# from django.db.models import Q
# from django.utils import timezone

# from .models import BonkPlayer, Friendship, FriendCountHistory


# def _ordered_pair(a_id: int, b_id: int) -> Tuple[int, int]:
#     """Return tuple sorted ascending (by PK, not bonk_id)."""
#     return (a_id, b_id) if a_id < b_id else (b_id, a_id)


# @transaction.atomic
# def sync_friends_for_player(
#     *,
#     current_bonk_id: int | None,
#     current_username: str,
#     friends_json: Dict[str, Any],
# ) -> Dict[str, int]:
#     """
#     Upsert the current player + friends, then upsert friendship edges
#     (undirected, de-duplicated) and remove edges no longer present.

#     Returns simple stats for UI.
#     """
#     now = timezone.now()
#     players_upserted = 0

#     # --- Guard: payload shape ---
#     friends: Iterable[Dict[str, Any]] = friends_json.get("friends") or []
#     # Some Bonk responses include `id` as int, some as str.
#     norm_friends = []
#     for f in friends:
#         try:
#             f_id = int(f.get("id"))
#         except Exception:
#             continue
#         f_name = (f.get("name") or "").strip() or f"player_{f_id}"
#         norm_friends.append({"id": f_id, "name": f_name})

#     # --- Upsert current player ---
#     # (If bonk_id is missing, we still create by username so favorites etc. work,
#     # but we cannot build edges without an id.)
#     if current_bonk_id is None:
#         current = BonkPlayer.objects.filter(username=current_username).first()
#         if not current:
#             current = BonkPlayer.objects.create(
#                 bonk_id=-1,  # placeholder so unique constraint doesn't explode; adjust if you never expect None
#                 username=current_username,
#             )
#     else:
#         current, _ = BonkPlayer.objects.get_or_create(
#             bonk_id=current_bonk_id,
#             defaults={"username": current_username},
#         )
#         # keep username fresh
#         if current_username and current.username != current_username:
#             current.username = current_username
#             current.save(update_fields=["username", "updated_at"])

#     # --- Also upsert players from incoming friend requests ---
#     requests_list: Iterable[Dict[str, Any]] = friends_json.get("requests") or []
#     for req in requests_list:
#         try:
#             req_id = int(req.get("id"))
#         except Exception:
#             continue
#         req_name = (req.get("name") or "").strip() or f"player_{req_id}"

#         # Upsert the requester as a BonkPlayer so they appear in searches later
#         requester, created = BonkPlayer.objects.get_or_create(
#             bonk_id=req_id,
#             defaults={"username": req_name},
#         )
#         if created:
#             players_upserted = players_upserted + 1
#         elif req_name and requester.username != req_name:
#             requester.username = req_name
#             requester.save(update_fields=["username", "updated_at"])


#     # --- Upsert friend nodes + collect PKs ---
#     friend_ids: Set[int] = set()
#     friend_pks_by_bonkid: dict[int, int] = {}

#     for f in norm_friends:
#         fid = f["id"]
#         fname = f["name"]
#         friend_ids.add(fid)

#         friend, created = BonkPlayer.objects.get_or_create(
#             bonk_id=fid,
#             defaults={"username": fname},
#         )
#         if created:
#             players_upserted += 1
#         elif fname and friend.username != fname:
#             friend.username = fname
#             friend.save(update_fields=["username", "updated_at"])

#         friend_pks_by_bonkid[fid] = friend.pk

#     # --- Edge upserts (present now) ---
#     added_edges = 0
#     touched_edges = 0

#     for fid in friend_ids:
#         other_pk = friend_pks_by_bonkid[fid]
#         low_pk, high_pk = _ordered_pair(current.pk, other_pk)
#         _, created = Friendship.objects.update_or_create(
#             player_low_id=low_pk,
#             player_high_id=high_pk,
#             defaults={"last_confirmed_at": now},
#         )
#         touched_edges += 1
#         if created:
#             added_edges += 1

#     # --- Remove edges that disappeared since last sync ---
#     # Find all existing neighbors by PK, convert to their bonk_ids, subtract.
#     existing_edges = Friendship.objects.filter(
#         Q(player_low=current) | Q(player_high=current)
#     ).select_related("player_low", "player_high")

#     existing_neighbor_bonkids: Set[int] = set()
#     neighbor_pk_to_edge_ids: dict[int, list[int]] = {}  # map other PK -> edge IDs

#     for e in existing_edges:
#         other = e.player_high if e.player_low_id == current.pk else e.player_low
#         existing_neighbor_bonkids.add(other.bonk_id)
#         neighbor_pk_to_edge_ids.setdefault(other.pk, []).append(e.id)

#     to_remove_bonkids = existing_neighbor_bonkids - friend_ids
#     removed_edges = 0
#     if to_remove_bonkids:
#         to_remove_pks = list(
#             BonkPlayer.objects.filter(bonk_id__in=to_remove_bonkids).values_list("pk", flat=True)
#         )
#         if to_remove_pks:
#             deleted, _ = Friendship.objects.filter(
#                 Q(player_low=current, player_high_id__in=to_remove_pks)
#                 | Q(player_high=current, player_low_id__in=to_remove_pks)
#             ).delete()
#             removed_edges = deleted

#     # --- Friend count snapshot/history ---
#     friends_now = len(friend_ids)
#     if current.last_friend_count != friends_now:
#         current.last_friend_count = friends_now
#         current.last_seen = now
#         current.save(update_fields=["last_friend_count", "last_seen", "updated_at"])
#         FriendCountHistory.objects.create(player=current, count=friends_now)

#     return {
#         "players_upserted": players_upserted,
#         "friends_now": friends_now,
#         "added_edges": added_edges,
#         "removed_edges": removed_edges,
#         "edges_touched": touched_edges,
#     }

# skins/friends_sync.py

from typing import Dict, Any, Iterable, Tuple, Set
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import BonkPlayer, Friendship, FriendCountHistory


def _ordered_pair(a_id: int, b_id: int) -> Tuple[int, int]:
    """Return tuple sorted ascending (by PK, not bonk_id)."""
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


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

    Returns simple stats for UI.
    """
    now = timezone.now()
    players_upserted = 0

    # --------- Normalize confirmed friends ----------
    friends_list: Iterable[Dict[str, Any]] = friends_json.get("friends") or []
    norm_friends = []
    for f in friends_list:
        try:
            fid = int(f.get("id"))
        except Exception:
            continue
        fname = (f.get("name") or "").strip() or f"player_{fid}"
        norm_friends.append({"id": fid, "name": fname})

    # --------- Normalize friend requests -------------
    requests_list: Iterable[Dict[str, Any]] = friends_json.get("requests") or []
    norm_requests = []
    for r in requests_list:
        try:
            rid = int(r.get("id"))
        except Exception:
            continue
        rname = (r.get("name") or "").strip() or f"player_{rid}"
        norm_requests.append({"id": rid, "name": rname})

    # --------- Combine all players to upsert ----------
    combined = norm_friends + norm_requests

    # --------- Upsert current player ----------
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
            current.username = current_username
            current.save(update_fields=["username", "updated_at"])

    # --------- Upsert all players (friends + requests) ----------
    friend_ids: Set[int] = set()            # confirmed friends only
    friend_pks_by_bonkid: dict[int, int] = {}

    for obj in combined:
        pid = obj["id"]
        pname = obj["name"]

        # Track only confirmed friends for edges
        if pid in [f["id"] for f in norm_friends]:
            friend_ids.add(pid)

        player, created = BonkPlayer.objects.get_or_create(
            bonk_id=pid,
            defaults={"username": pname},
        )
        if created:
            players_upserted += 1
        elif pname and player.username != pname:
            player.username = pname
            player.save(update_fields=["username", "updated_at"])

        friend_pks_by_bonkid[pid] = player.pk

    # --------- Upsert edges for ACTUAL (confirmed) friends ----------
    added_edges = 0
    touched_edges = 0

    for fid in friend_ids:
        other_pk = friend_pks_by_bonkid[fid]
        low_pk, high_pk = _ordered_pair(current.pk, other_pk)

        _, created = Friendship.objects.update_or_create(
            player_low_id=low_pk,
            player_high_id=high_pk,
            defaults={"last_confirmed_at": now},
        )
        touched_edges += 1
        if created:
            added_edges += 1

    # --------- Remove edges that no longer exist ----------
    existing_edges = Friendship.objects.filter(
        Q(player_low=current) | Q(player_high=current)
    ).select_related("player_low", "player_high")

    existing_friend_ids: Set[int] = set()
    for e in existing_edges:
        other = e.player_high if e.player_low_id == current.pk else e.player_low
        existing_friend_ids.add(other.bonk_id)

    to_remove = existing_friend_ids - friend_ids
    removed_edges = 0

    if to_remove:
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
    friends_now = len(friend_ids)
    if current.last_friend_count != friends_now:
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
    }
