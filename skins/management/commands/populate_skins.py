from django.core.management.base import BaseCommand
from skins.models import Skin
import random
import uuid

class Command(BaseCommand):
    help = "Populate fake skins for local search"

    def handle(self, *args, **kwargs):
        for i in range(500):
            Skin.objects.create(
                name=f"Dev Skin {i}",
                link=f"https://bonkleagues.io/skins/dev-{uuid.uuid4()}",
                creator=f"Creator{i % 25}",
                image_url="https://bonkleagues.io/api/avatar.svg",
                description="Generated dev skin",
                labels={
                    "colors": random.sample(["red", "blue", "green", "black", "white"], 2),
                    "style": random.choice(["simple", "complex", "meme"]),
                },
                upvotes=random.randint(0, 500),
                downvotes=random.randint(0, 50),
            )

        self.stdout.write(self.style.SUCCESS("Skins populated"))
