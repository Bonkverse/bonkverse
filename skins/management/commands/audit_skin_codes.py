"""Check every stored skin code with the same rules new codes must pass.

Usage:
    python manage.py audit_skin_codes          # counts by reason, with example ids
    python manage.py audit_skin_codes --ids    # every refused id

Read-only. Run it after changing the rules in core/bonk/skin_codes.py: a real
skin refused here would be refused when someone publishes one like it.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand

from core.bonk import InvalidSkinCode, SkinCode
from skins.models import Skin

EXAMPLES = 10


class Command(BaseCommand):
    help = "Check stored skin codes against the rules for new ones (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--ids", action="store_true", help="list every refused id")

    def handle(self, *args, ids, **options):
        checked = 0
        refused = defaultdict(list)
        codes = (
            Skin.objects.exclude(skin_code="")
            .exclude(skin_code__isnull=True)
            .order_by("id")
            .values_list("id", "skin_code")
        )
        for skin_id, code in codes.iterator(chunk_size=2000):
            checked += 1
            try:
                SkinCode(code).parse()
            except InvalidSkinCode as e:
                # "shape 834 doesn't exist" -> one bucket for all unknown shapes
                reason = "shape doesn't exist" if e.reason.startswith("shape ") else e.reason
                refused[reason].append(skin_id)

        total = sum(len(v) for v in refused.values())
        self.stdout.write(f"Checked {checked} skin codes: {checked - total} pass, {total} refused.")
        for reason, skin_ids in sorted(refused.items(), key=lambda kv: -len(kv[1])):
            shown = skin_ids if ids else skin_ids[:EXAMPLES]
            more = (
                "" if ids or len(skin_ids) <= EXAMPLES else f" (+{len(skin_ids) - EXAMPLES} more)"
            )
            self.stdout.write(f"  {reason}: {len(skin_ids)}: {', '.join(map(str, shown))}{more}")
