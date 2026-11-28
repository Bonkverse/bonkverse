"""Friend-request sign-in was removed (2026-11-27, ADR 0024).

- Claims still waiting (or proven but not finished) end as refused, with the
  message the old waiting page shows. Finished and expired ones stay as
  history.
- One-click sign-ins of accounts proven only by friend request end: a friend
  request can't show who started the claim, so whoever got in that way
  doesn't keep a month of one-click access. The accounts themselves are left
  as they are; the next sign-in needs a room code or the password.
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

    linked = BonkAccountLink.objects.filter(active=True).values_list("user_id", flat=True)
    owner_proven = BonkAccountLink.objects.filter(
        Q(password_proven_at__isnull=False) | Q(room_proven_at__isnull=False)
    ).values_list("user_id", flat=True)
    RememberedSignIn.objects.filter(user_id__in=linked).exclude(user_id__in=owner_proven).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0013_room_proof_and_claim_level")]

    operations = [migrations.RunPython(cancel, migrations.RunPython.noop)]
