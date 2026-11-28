"""Undo what friend-request sign-in may have given someone who wasn't the
owner (accounts/retire_friend_requests.py). Migration 0014 runs it at
deploy; run it once more after the deploy has settled, because old
processes still ran friend requests for that minute. Safe to repeat.

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
