"""Friend-request sign-in was removed (2026-11-27, ADR 0024): friend-request
claims still waiting (or proven but not finished) end as refused, with the
message old waiting pages show. Finished and expired ones stay as history.

Only claims, with the models as they were here. Taking back what a friend
request may have given someone (groups, one-click sign-ins, sessions) is
`manage.py retire_friend_requests`, run once after the deploy has settled
(accounts/retire_friend_requests.py, runbook): it needs today's code, which
a migration mustn't run.
"""

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
