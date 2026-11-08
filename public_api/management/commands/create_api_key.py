"""Create a public API key and print it once.

    python manage.py create_api_key --name "Luna comp leaderboard" \
        --contact "luna0051 (Discord)" --tier partner

The full key is printed once and never stored; send it to the person
privately (a Discord DM, not a channel). Revoke with `revoke_api_key`.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from public_api.keys import create_key
from public_api.models import ApiKey


class Command(BaseCommand):
    help = "Create a public API key and print it once."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="What the key is for.")
        parser.add_argument("--contact", default="", help="How to reach the key holder.")
        parser.add_argument(
            "--tier", default=ApiKey.TIER_STANDARD, choices=[t for t, _ in ApiKey.TIERS]
        )
        parser.add_argument("--owner", default="", help="Bonkverse username responsible for it.")
        parser.add_argument("--notes", default="")

    def handle(self, *args, name, contact, tier, owner, notes, **options):
        owner_user = None
        if owner:
            owner_user = get_user_model().objects.filter(username__iexact=owner).first()
            if owner_user is None:
                raise CommandError(f"No Bonkverse account named {owner!r}.")
        api_key, raw = create_key(
            name=name, tier=tier, owner=owner_user, contact=contact, notes=notes
        )
        self.stdout.write(f"Created {api_key}.")
        self.stdout.write("Key (shown once, store it now):")
        self.stdout.write(raw)
