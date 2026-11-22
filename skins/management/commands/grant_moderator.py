"""Give (or take away) access to the skin report queue (/moderation/).

Usage:
    python manage.py grant_moderator "The Saucy Tulip"
    python manage.py grant_moderator "The Saucy Tulip" --revoke
    python manage.py grant_moderator --list

Moderators join the "Moderator" group (skins.moderate_skins). That is all
they get: not is_staff, so no re-render button and no /admin/. The account
must already exist, i.e. that player has signed in to Bonkverse once.
"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from accounts.models import BonkUser
from skins.models import MODERATOR_GROUP


class Command(BaseCommand):
    help = "Add a site account to the Moderator group (report queue), or remove it."

    def add_arguments(self, parser):
        parser.add_argument("username", nargs="?", help="bonk.io username, as shown on Bonkverse")
        parser.add_argument("--revoke", action="store_true", help="remove moderator access")
        parser.add_argument("--list", action="store_true", help="list current moderators")

    def handle(self, *args, username=None, revoke=False, list=False, **options):
        group = Group.objects.get(name=MODERATOR_GROUP)

        if list:
            names = sorted(group.user_set.values_list("username", flat=True), key=str.lower)
            self.stdout.write("\n".join(names) if names else "No moderators.")
            return

        if not username:
            raise CommandError("Give a bonk.io username (or --list).")
        try:
            user = BonkUser.objects.get(username__iexact=username)
        except BonkUser.DoesNotExist:
            raise CommandError(
                f"No account named {username!r}. They need to sign in to Bonkverse once first."
            ) from None

        if revoke:
            user.groups.remove(group)
            self.stdout.write(f"{user.username}: no longer a moderator.")
            return

        user.groups.add(group)
        self.stdout.write(
            f"{user.username}: now a moderator. "
            '"Skin reports" is in their account menu (/moderation/).'
        )
