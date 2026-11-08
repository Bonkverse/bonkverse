"""python manage.py sync_replays — sync names and DBIDs with the replay site.

Copies registered names seen in replays into Bonkverse and sends Bonkverse's
known DBIDs to the replay site (players/replay_sync.py). Each run carries on
from where the last one stopped; run it repeatedly (or with a large
--batches) for the first, full pass over the archive.
"""

from django.core.management.base import BaseCommand

from players import replay_sync


class Command(BaseCommand):
    help = "Copy replay player names into Bonkverse and send DBIDs to the replay site."

    def add_arguments(self, parser):
        parser.add_argument("--names-only", action="store_true", help="Only pull replay names.")
        parser.add_argument("--ids-only", action="store_true", help="Only push DBIDs.")
        parser.add_argument(
            "--batches",
            type=int,
            default=200,
            help="Most batches per direction this run (5,000 replays / 2,000 players each).",
        )

    def handle(self, *args, **opts):
        result = replay_sync.run(
            names=not opts["ids_only"],
            ids=not opts["names_only"],
            max_batches=opts["batches"],
        )
        if "skipped" in result:
            self.stderr.write(self.style.WARNING(f"Skipped: {result['skipped']}"))
            return
        for part, label in (("names", "Replay names"), ("ids", "DBIDs")):
            r = result.get(part)
            if not r:
                continue
            count = r.get("added", r.get("sent"))
            verb = "added" if part == "names" else "sent"
            state = "up to date" if r["done"] else "more to do (run again)"
            line = f"{label}: {count} {verb} in {r['batches']} batches, {state}"
            if r["error"]:
                self.stderr.write(self.style.ERROR(f"{line}; stopped: {r['error']}"))
            else:
                self.stdout.write(self.style.SUCCESS(line))
