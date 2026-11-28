"""Friend-request sign-in was removed (2026-11-27, ADR 0024).

- Claims still waiting (or proven but not finished) end as refused, with the
  message the old waiting page shows. Finished and expired ones stay as
  history.
- Accounts proven only by friend request (no password or room-code proof on
  any link; every link from before friend requests was marked
  password-proven by 0010) are signed out everywhere and lose their
  one-click sign-ins: a friend request can't show who started the claim, so
  whoever got in that way doesn't keep the account. The accounts themselves
  are left as they are; the next sign-in needs a room code or the password.

Not reversible: ended sessions, one-click rows and claim statuses stay as
they are on the way back.
"""

from django.db import migrations
from django.db.models import Q

GONE = (
    "Signing in with a friend request has been replaced by room codes, which are safer. "
    "Sign in with a room code or your bonk.io password."
)


def cancel(apps, schema_editor):
    LinkClaim = apps.get_model("accounts", "LinkClaim")
    BonkAccountLink = apps.get_model("accounts", "BonkAccountLink")
    RememberedSignIn = apps.get_model("accounts", "RememberedSignIn")

    LinkClaim.objects.filter(method="friend", status__in=["pending", "proven"]).update(
        status="refused", problem=GONE
    )

    linked = set(BonkAccountLink.objects.filter(active=True).values_list("user_id", flat=True))
    owner_proven = set(
        BonkAccountLink.objects.filter(
            Q(password_proven_at__isnull=False) | Q(room_proven_at__isnull=False)
        ).values_list("user_id", flat=True)
    )
    friend_only = sorted(linked - owner_proven)
    RememberedSignIn.objects.filter(user_id__in=friend_only).delete()

    # Live code on purpose: the one place that knows how a session holds an
    # account (as the one in use, or signed in or unlocked on that browser).
    from accounts.sessions import end_other_sessions

    for user_id in friend_only:
        end_other_sessions(user_id, None)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0013_room_proof_and_claim_level")]

    operations = [migrations.RunPython(cancel, migrations.RunPython.noop)]
