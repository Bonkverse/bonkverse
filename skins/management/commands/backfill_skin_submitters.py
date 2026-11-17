"""Record who submitted skins added before submitters were stored.

Usage:
    python manage.py backfill_skin_submitters --dry-run   # report only, changes nothing
    python manage.py backfill_skin_submitters             # write the submitter fields

Reads each legacy skin's first `skin_uploaded` event: upload-form and editor
events give the site account, BonxBot events the Discord id. Only skins still
marked `legacy` are touched, so it is safe to re-run. Skins with no upload
event (bulk imports, very old uploads) stay `legacy`.
"""

from django.core.management.base import BaseCommand

from skins.submitters import backfill_submitters


class Command(BaseCommand):
    help = "Fill submitter fields on legacy skins from their skin_uploaded events."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="report what would change, write nothing"
        )

    def handle(self, *args, dry_run, **options):
        report = backfill_submitters(dry_run=dry_run)
        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(f"{verb} {report.updated} skin(s).")
        for key, count in sorted(report.counts.items()):
            self.stdout.write(f"  {key}: {count}")
        if dry_run:
            self.stdout.write("Dry run: nothing changed. Re-run without --dry-run to write.")
