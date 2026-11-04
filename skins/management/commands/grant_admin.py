"""Give (or take away) full admin access for an existing site account.

Usage:
    python manage.py grant_admin "The Saucy Tulip"
    python manage.py grant_admin "The Saucy Tulip" --revoke

The account must already exist, i.e. that player has signed in to Bonkverse
with bonk.io at least once. Admins then open /admin/ while signed in.
"""

from django.core.management.base import BaseCommand, CommandError

from skins.models import BonkUser


class Command(BaseCommand):
    help = "Make a site account a superuser (staff + all admin permissions), or revoke it."

    def add_arguments(self, parser):
        parser.add_argument("username", help="bonk.io username, as shown on Bonkverse")
        parser.add_argument("--revoke", action="store_true", help="remove admin access")

    def handle(self, *args, username, revoke, **options):
        try:
            user = BonkUser.objects.get(username__iexact=username)
        except BonkUser.DoesNotExist:
            raise CommandError(
                f"No account named {username!r}. They need to sign in to Bonkverse once first."
            ) from None

        if revoke:
            # Staff (re-render etc.) is a separate role; revoking admin keeps it.
            user.is_superuser = False
            user.save(update_fields=["is_superuser"])
            self.stdout.write(f"{user.username}: admin access removed (is_staff unchanged).")
            return

        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])
        self.stdout.write(f"{user.username}: now an admin. Open /admin/ while signed in.")
