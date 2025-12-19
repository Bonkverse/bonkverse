from django.core.management.base import BaseCommand
from skins.models import FlashFriend, FlashFriendship, BonkUser
import random

class Command(BaseCommand):
    help = "Populate Flash friends (requires at least one BonkUser)"

    def handle(self, *args, **kwargs):
        users = list(BonkUser.objects.all())
        if not users:
            self.stdout.write("No BonkUser found — skipping flash friends")
            return

        for i in range(500):
            ff = FlashFriend.objects.create(name=f"FlashFriend{i}")
            FlashFriendship.objects.create(
                user=random.choice(users),
                flash_friend=ff,
            )

        self.stdout.write(self.style.SUCCESS("Flash friends populated"))
