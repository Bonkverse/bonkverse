"""Copy every BonxBot Discord submission onto Bonkverse in one go.

Run on the Bonkverse web service (it writes skin images to the media volume):

    python manage.py import_bonxbot_skins --dry-run      # counts only, writes nothing
    python manage.py import_bonxbot_skins                # do it

Each skin is rendered by the editor from its code: the bot's stored skin_code,
or the one in the final_url BonkLeagues redirected to. Rows with no code
anywhere are read from BonkLeagues (2s apart); --no-bonkleagues skips those and
leaves them for a later run.

The BonxBot database URL comes from --database-url or BONXBOT_DATABASE_URL
(the Bonx DB service's public connection URL). Safe to re-run.
Logic: skins/bonxbot_migration.py.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from integrations.bonxbot_db import BonxBotDB
from skins.bonxbot_migration import migrate


class Command(BaseCommand):
    help = "Import BonxBot's Discord skin submissions onto Bonkverse (one-time migration)."

    def add_arguments(self, parser):
        parser.add_argument("--database-url", default=os.getenv("BONXBOT_DATABASE_URL", ""))
        parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
        parser.add_argument("--limit", type=int, default=None, help="Only the oldest N rows.")
        parser.add_argument(
            "--no-bonkleagues",
            action="store_true",
            help="Skip rows whose code only BonkLeagues has; a later run picks them up.",
        )

    def handle(self, *args, database_url, dry_run, limit, no_bonkleagues, **options):
        if not database_url:
            raise CommandError("Pass --database-url or set BONXBOT_DATABASE_URL.")

        db = BonxBotDB(database_url)
        try:
            report = migrate(
                db,
                dry_run=dry_run,
                limit=limit,
                skip_bonkleagues=no_bonkleagues,
                progress=self.stdout.write,
            )
        finally:
            db.close()

        heading = "Dry run, nothing written" if dry_run else "Done"
        self.stdout.write(self.style.SUCCESS(f"{heading}: {report.total} row(s)"))
        for outcome, n in sorted(report.counts.items()):
            self.stdout.write(f"  {outcome:<26} {n}")
        for bot_id, error in report.retry_later:
            self.stdout.write(f"  retry later: bot skin {bot_id}: {error}")
        for bot_id, error in report.failed:
            self.stdout.write(f"  failed: bot skin {bot_id}: {error}")
