"""Fill a local database with made-up data to develop against.

Never run in production: every populate_* command it calls writes fake rows.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

# Each is a management command; tests/test_populate.py checks they all exist.
COMMANDS = [
    "populate_bonkplayers",
    "populate_friendships",
    "populate_skins",
    "populate_discord",
    "populate_flashfriends",
]


class Command(BaseCommand):
    help = "Populate all local dev data"

    def handle(self, *args, **kwargs):
        self.stdout.write("Installing Postgres extensions...")
        call_command("init_pg_extensions")

        for cmd in COMMANDS:
            self.stdout.write(f"Running {cmd}...")
            call_command(cmd)

        self.stdout.write(self.style.SUCCESS("All dev data populated"))
