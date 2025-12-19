from django.core.management.base import BaseCommand
from skins.models import BonkPlayer, Friendship
import random

class Command(BaseCommand):
    help = "Populate Friendships"

    def handle(self, *args, **kwargs):
        players = list(BonkPlayer.objects.all())

        created = 0
        while created < 500:
            a, b = random.sample(players, 2)
            low, high = sorted([a, b], key=lambda x: x.id)

            obj, is_new = Friendship.objects.get_or_create(
                player_low=low,
                player_high=high,
            )
            if is_new:
                created += 1

        self.stdout.write(self.style.SUCCESS("Friendships populated"))
