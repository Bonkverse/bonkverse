"""Check (and optionally repair) every skin's upvote/downvote counters.

Usage:
    python manage.py audit_vote_counts            # report only, changes nothing
    python manage.py audit_vote_counts --fix      # set counters to the real counts
    python manage.py audit_vote_counts --show 50  # list up to 50 drifted skins

Before RFC-0001 4.1, two votes at the same moment could lose one update, so a
skin's stored `upvotes`/`downvotes` may differ from its SkinVote rows. The
rows are the truth; this command compares the two. Safe to run any time and
to re-run: --fix only touches skins that differ, each under its row lock.
"""

from django.core.management.base import BaseCommand

from skins.votes import fix_vote_counts, recount_votes


class Command(BaseCommand):
    help = "Compare skin vote counters with SkinVote rows; --fix repairs the differences."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix", action="store_true", help="write the real counts (default: report only)"
        )
        parser.add_argument(
            "--show", type=int, default=20, help="how many drifted skins to list (default 20)"
        )

    def handle(self, *args, fix, show, **options):
        drifted = recount_votes()
        if not drifted:
            self.stdout.write(self.style.SUCCESS("All vote counters match their votes."))
            return

        off_up = sum(abs(stored_up - real_up) for _, stored_up, _, real_up, _ in drifted)
        off_down = sum(abs(stored_down - real_down) for _, _, stored_down, _, real_down in drifted)
        self.stdout.write(
            f"{len(drifted)} skin(s) have wrong counters "
            f"(upvotes off by {off_up} in total, downvotes by {off_down})."
        )
        for skin_id, stored_up, stored_down, real_up, real_down in drifted[:show]:
            self.stdout.write(
                f"  skin {skin_id}: stored {stored_up}/{stored_down}, "
                f"real {real_up}/{real_down} (up/down)"
            )
        if len(drifted) > show:
            self.stdout.write(f"  ... and {len(drifted) - show} more (use --show to list more)")

        if not fix:
            self.stdout.write("Dry run: nothing changed. Re-run with --fix to repair.")
            return

        changed = fix_vote_counts(drifted)
        self.stdout.write(self.style.SUCCESS(f"Fixed {changed} skin(s)."))
