"""Friend-request sign-in was removed (2026-11-27, ADR 0024): claims still
waiting (or proven but not finished) end as refused, with the message the
old waiting page shows. Finished and expired ones stay as history."""

from django.db import migrations

GONE = (
    "Signing in with a friend request has been replaced by room codes, which are safer. "
    "Sign in with a room code or your bonk.io password."
)


def cancel(apps, schema_editor):
    LinkClaim = apps.get_model("accounts", "LinkClaim")
    LinkClaim.objects.filter(method="friend", status__in=["pending", "proven"]).update(
        status="refused", problem=GONE
    )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0013_room_proof_and_claim_level")]

    operations = [migrations.RunPython(cancel, migrations.RunPython.noop)]
