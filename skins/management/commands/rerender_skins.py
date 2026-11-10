"""Re-render skins' images from their stored codes, in bulk.

Usage (on the `bonkverse` service: the media volume is only mounted there):
    python manage.py rerender_skins                      # dry run: counts, changes nothing
    python manage.py rerender_skins --run                # every skin with a code
    python manage.py rerender_skins --run --only-broken  # only skins whose files look broken
    python manage.py rerender_skins --run --purge-cache  # ... then empty Cloudflare's cache
    python manage.py rerender_skins --run --start-after 4567   # carry on after a stop

Each skin goes through the same steps as the staff Re-render button
(skins/rerender.py): render from the stored code, SVG safety check, replace
the three files and image rows, and point image_url at /media/. A skin that
fails keeps its old images. Paced (--per-second) so the editor's render
service isn't flooded; safe to stop and re-run, since a re-run only redoes
work. Progress lines say where to resume.

Stops early after --max-failures render failures in a row (the render service
is probably down), printing the id to resume from.
"""

import os
import time
from collections import Counter, defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from integrations.cloudflare import purge_whole_site
from skins.models import Skin
from skins.rerender import RerenderError, rerender
from skins.skin_media import file_problems

PROGRESS_EVERY = 100


class Command(BaseCommand):
    help = "Re-render skins from their stored codes (dry run unless --run)."

    def add_arguments(self, parser):
        parser.add_argument("--run", action="store_true", help="re-render (default: dry run)")
        parser.add_argument(
            "--only-broken", action="store_true", help="only skins whose files look broken"
        )
        parser.add_argument(
            "--start-after", type=int, default=0, help="skip skins with this id or lower"
        )
        parser.add_argument("--limit", type=int, default=None, help="at most this many skins")
        parser.add_argument(
            "--per-second", type=float, default=2.0, help="renders per second (default 2)"
        )
        parser.add_argument(
            "--max-failures",
            type=int,
            default=10,
            help="stop after this many render failures in a row (default 10)",
        )
        parser.add_argument(
            "--purge-cache",
            action="store_true",
            help="empty Cloudflare's whole cache when the run finishes",
        )

    def handle(
        self,
        *args,
        run,
        only_broken,
        start_after,
        limit,
        per_second,
        max_failures,
        purge_cache,
        **options,
    ):
        if per_second <= 0:
            raise CommandError("--per-second must be above 0")
        skins_dir = os.path.join(settings.MEDIA_ROOT, "skins")
        if not os.path.isdir(skins_dir):
            message = (
                f"{skins_dir} doesn't exist. Run this on the bonkverse service, "
                "where the media volume is mounted."
            )
            if run:
                raise CommandError(message)
            self.stdout.write(self.style.WARNING(message))

        skins = Skin.objects.filter(id__gt=start_after).order_by("id")
        if not run:
            self._dry_run(skins)
            return

        targets = self._targets(skins, only_broken, limit)
        self.stdout.write(
            f"Re-rendering {len(targets)} skin(s) at {per_second:g}/s "
            f"(about {len(targets) / per_second / 60:.0f} min)."
        )
        stopped = self._rerender_all(targets, per_second, max_failures)

        if purge_cache:
            if stopped:
                self.stdout.write("Not purging Cloudflare: the run stopped early.")
            else:
                self._purge()

    # ── dry run ────────────────────────────────────────────────────────

    def _dry_run(self, skins):
        counts = Counter()
        examples = defaultdict(list)
        media_prefix = settings.MEDIA_URL
        for skin_id, code, image_url in skins.values_list("id", "skin_code", "image_url").iterator(
            chunk_size=2000
        ):
            counts["skins"] += 1
            if not code:
                counts["no code (can't re-render)"] += 1
                continue
            counts["with a code"] += 1
            if not (image_url or "").startswith(media_prefix):
                counts["image_url outside /media/ (will switch to /media/)"] += 1
            problems = file_problems(skin_id)
            if problems:
                counts["with a code, files look broken"] += 1
                for problem in problems:
                    if len(examples[problem]) < 5:
                        examples[problem].append(skin_id)

        self.stdout.write("Dry run: nothing changed.")
        for label, count in counts.items():
            self.stdout.write(f"  {label}: {count}")
        for problem, ids in sorted(examples.items()):
            self.stdout.write(f"  e.g. {problem}: skins {ids}")
        with_code = counts["with a code"]
        self.stdout.write(
            f"--run would re-render {with_code} skin(s) (about {with_code / 2 / 60:.0f} min "
            f"at 2/s); --only-broken would do {counts['with a code, files look broken']}."
        )

    # ── run ─────────────────────────────────────────────────────────────

    def _targets(self, skins, only_broken, limit):
        ids = []
        for skin_id in (
            skins.exclude(skin_code="")
            .exclude(skin_code__isnull=True)
            .values_list("id", flat=True)
            .iterator(chunk_size=2000)
        ):
            if only_broken and not file_problems(skin_id):
                continue
            ids.append(skin_id)
            if limit and len(ids) >= limit:
                break
        return ids

    def _rerender_all(self, ids, per_second, max_failures) -> bool:
        """Re-render each skin; returns True if it stopped early."""
        interval = 1 / per_second
        failed = defaultdict(list)
        done = in_a_row = 0
        last_id = None
        for position, skin_id in enumerate(ids, start=1):
            started = time.monotonic()
            skin = Skin.objects.filter(id=skin_id).first()
            if skin is not None:
                result = rerender(skin)
                if result.error:
                    failed[result.error].append(skin_id)
                    in_a_row = in_a_row + 1 if result.error == RerenderError.RENDER_FAILED else 0
                else:
                    done += 1
                    in_a_row = 0
            last_id = skin_id

            if in_a_row >= max_failures:
                self.stdout.write(
                    self.style.ERROR(
                        f"Stopped: {in_a_row} render failures in a row (render service down?). "
                        f"Resume with --start-after {self._resume_point(ids, position, in_a_row)}."
                    )
                )
                self._summary(done, failed)
                return True
            if position % PROGRESS_EVERY == 0:
                self.stdout.write(
                    f"{position}/{len(ids)}: {done} re-rendered, "
                    f"{sum(len(v) for v in failed.values())} failed, last id {last_id} "
                    f"(resume with --start-after {last_id})"
                )
            time.sleep(max(0.0, interval - (time.monotonic() - started)))

        self._summary(done, failed)
        return False

    @staticmethod
    def _resume_point(ids, position, in_a_row):
        """The id just before the failing streak, so a resume retries all of it."""
        first_failure = position - in_a_row  # 0-based index of the streak's first skin
        return ids[first_failure - 1] if first_failure > 0 else ids[0] - 1

    def _summary(self, done, failed):
        self.stdout.write(self.style.SUCCESS(f"Re-rendered {done} skin(s)."))
        for error, ids in sorted(failed.items()):
            shown = ", ".join(str(i) for i in ids[:50])
            more = f" (+{len(ids) - 50} more)" if len(ids) > 50 else ""
            self.stdout.write(f"  {error}: {len(ids)}: {shown}{more}")

    def _purge(self):
        result = purge_whole_site()
        if result.skipped:
            self.stdout.write("Cloudflare isn't configured here; nothing to purge.")
        elif result.ok:
            self.stdout.write(self.style.SUCCESS("Cloudflare cache emptied."))
        else:
            self.stdout.write(
                self.style.ERROR(f"Cloudflare purge failed ({result.error}); see the logs.")
            )
