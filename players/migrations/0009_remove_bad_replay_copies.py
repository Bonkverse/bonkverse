"""Remove BonkPlayers that the replay sync copied in by mistake.

1. Names with invisible marks: the first replay sync (2026-11-08) copied in
   "YuZuuuuu" followed by 1, 2, 3 ... left-to-right marks (U+200E), one row
   each, and the Players list showed every one as "YuZuuuuu". The sync now
   skips such names (players.replay_sync.has_invisible_marks).
2. Second copies of one name: a DBID-less row whose name (A-Z case aside,
   core.bonk.fold) already has a row with a DBID or an older row.

Only rows with no DBID that nothing points at (account links, friendships,
friend-count history, Flash friends) are removed, so no account, friend
edge or link is touched. Not reversible: the rows were only copies of
replay names, and the next sync doesn't bring them back.
"""

import unicodedata

from django.db import migrations

ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _fold(name):
    """core.bonk.fold, copied so this migration doesn't depend on app code."""
    return name.translate(ASCII_LOWER)


def _has_invisible_marks(name):
    """players.replay_sync.has_invisible_marks, copied for the same reason."""
    return any(unicodedata.category(ch) == "Cf" for ch in name)


def remove_bad_replay_copies(apps, schema_editor):
    BonkPlayer = apps.get_model("players", "BonkPlayer")
    Friendship = apps.get_model("players", "Friendship")
    FriendCountHistory = apps.get_model("players", "FriendCountHistory")
    FlashFriend = apps.get_model("players", "FlashFriend")
    BonkAccountLink = apps.get_model("accounts", "BonkAccountLink")

    # Every row in name order of arrival: the first row seen for a folded
    # name is the one kept, unless a row with a DBID has that name.
    with_dbid = set()
    nameless_first = {}
    doomed = []
    rows = BonkPlayer.objects.order_by("pk").values_list("pk", "bonk_id", "username")
    for pk, bonk_id, username in rows.iterator(chunk_size=5000):
        key = _fold(username)
        if bonk_id is not None:
            with_dbid.add(key)
            continue
        if _has_invisible_marks(username) or key in nameless_first:
            doomed.append(pk)
        else:
            nameless_first[key] = pk
    # A DBID-less row whose name has a row with a DBID is a copy too.
    doomed.extend(pk for key, pk in nameless_first.items() if key in with_dbid)
    if not doomed:
        return

    referenced = set()
    for model, fields in (
        (Friendship, ("player_low_id", "player_high_id")),
        (FriendCountHistory, ("player_id",)),
        (FlashFriend, ("bonk_player_id",)),
        (BonkAccountLink, ("bonk_player_id",)),
    ):
        for field in fields:
            referenced.update(
                model.objects.filter(**{f"{field}__in": doomed}).values_list(field, flat=True)
            )
    gone = [pk for pk in doomed if pk not in referenced]
    for start in range(0, len(gone), 5000):
        BonkPlayer.objects.filter(pk__in=gone[start : start + 5000], bonk_id__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("players", "0008_user_fields_point_at_accounts"),
        ("accounts", "0013_room_proof_and_claim_level"),
    ]

    operations = [
        migrations.RunPython(remove_bad_replay_copies, migrations.RunPython.noop),
    ]
