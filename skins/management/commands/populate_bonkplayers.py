from django.core.management.base import BaseCommand
from django.utils import timezone
from skins.models import BonkPlayer, FriendCountHistory
import random

class Command(BaseCommand):
    help = "Populate BonkPlayer and FriendCountHistory"

    def handle(self, *args, **kwargs):
        players = []
        for i in range(500):
            p = BonkPlayer.objects.create(
                bonk_id=100000 + i,
                username=f"Player{i}",
                last_seen=timezone.now(),
                last_friend_count=random.randint(0, 200),
            )
            players.append(p)

            FriendCountHistory.objects.create(
                player=p,
                count=p.last_friend_count,
            )

        self.stdout.write(self.style.SUCCESS("BonkPlayers populated"))
