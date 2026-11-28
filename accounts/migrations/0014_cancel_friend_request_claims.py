"""Friend-request sign-in was removed (2026-11-27, ADR 0024): refuse the
friend-request claims still waiting, and take back what a friend request may
have given someone who wasn't the owner (accounts/retire_friend_requests.py:
accounts proven only by friend request leave their groups, lose their
one-click sign-ins, and are signed out everywhere).

Uses live code on purpose: the one place that knows how groups and sessions
hold an account. Not reversible: ended sessions, groupings, one-click rows
and claim statuses stay as they are on the way back. Run again after the
deploy with `manage.py retire_friend_requests`.
"""

from django.db import migrations


def retire(apps, schema_editor):
    from accounts.retire_friend_requests import retire as run

    run()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0013_room_proof_and_claim_level"),
        ("sessions", "0001_initial"),
    ]

    operations = [migrations.RunPython(retire, migrations.RunPython.noop)]
