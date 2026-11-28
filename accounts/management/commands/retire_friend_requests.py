"""Undo what friend-request sign-in may have given someone who wasn't the
owner (accounts/retire_friend_requests.py). Run it once after the deploy
that removed friend requests has settled (runbook): migration 0014 only
refuses waiting claims, so until this runs, accounts proven only by friend
request keep their groups, one-click sign-ins and sessions. A nonzero
"accounts" count is expected the first time. Safe to repeat.

    python manage.py retire_friend_requests
"""

from django.core.management.base import BaseCommand

from accounts.retire_friend_requests import retire


class Command(BaseCommand):
    help = "Refuse waiting friend-request claims and sign friend-request-only accounts out."

    def handle(self, *args, **options):
        counts = retire()
        for key, value in counts.items():
            self.stdout.write(f"{key}: {value}")
