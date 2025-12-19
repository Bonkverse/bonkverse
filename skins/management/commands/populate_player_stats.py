from django.core.management.base import BaseCommand
from skins.models import PlayerWin, PlayerLoss
import random

class Command(BaseCommand):
    help = "Populate wins and losses"

    def handle(self, *args, **kwargs):
        for i in range(500):
            username = f"Player{random.randint(0, 499)}"
            PlayerWin.objects.create(username=username)
            PlayerLoss.objects.create(username=username)

        self.stdout.write(self.style.SUCCESS("Player stats populated"))
