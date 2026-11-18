"""Copy LevelBot's verified Discord ↔ bonk.io accounts onto Bonkverse, once.

    python manage.py import_levelbot_links --dry-run   # report only, changes nothing
    python manage.py import_levelbot_links             # do it

The LevelBot database URL comes from --database-url or LEVELBOT_DATABASE_URL
(the Level DB service's public connection URL, in Railway project "General
Discord Server Bots"). LevelBot's database is only read. Safe to re-run: links
already here are left alone. Logic: accounts/discord_links.py.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from accounts.services import import_levelbot_links
from integrations.levelbot_db import LevelBotDB


class Command(BaseCommand):
    help = "Import LevelBot's verified Discord ↔ bonk.io accounts as Discord links."

    def add_arguments(self, parser):
        parser.add_argument("--database-url", default=os.getenv("LEVELBOT_DATABASE_URL", ""))
        parser.add_argument(
            "--dry-run", action="store_true", help="report what would change, write nothing"
        )

    def handle(self, *args, database_url, dry_run, **options):
        if not database_url:
            raise CommandError("Pass --database-url or set LEVELBOT_DATABASE_URL.")

        db = LevelBotDB(database_url)
        try:
            accounts = db.accounts()
        finally:
            db.close()

        report = import_levelbot_links(accounts, dry_run=dry_run)
        self.stdout.write(f"Read {len(accounts)} LevelBot account(s).")
        for outcome, count in sorted(report.counts.items()):
            self.stdout.write(f"  {outcome}: {count}")
        self.stdout.write(f"  new players (name only): {report.new_players}")
        if dry_run:
            self.stdout.write("Dry run: nothing changed. Re-run without --dry-run to write.")
