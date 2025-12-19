from django.core.management.base import BaseCommand
from skins.models import DiscordTag, DiscordServer, DiscordServerSnapshot
import uuid
import random

class Command(BaseCommand):
    help = "Populate Discord servers"

    def handle(self, *args, **kwargs):
        tags = [
            DiscordTag.objects.get_or_create(name=n)[0]
            for n in ["competitive", "skins", "memes", "events"]
        ]

        for i in range(50):
            server = DiscordServer.objects.create(
                guild_id=str(100000 + i),
                invite_code=f"invite{i}",
                invite_url=f"https://discord.gg/invite{i}",
                name=f"Bonk Server {i}",
                description="Seeded Discord server",
                member_count=random.randint(50, 5000),
                online_count=random.randint(5, 500),
            )
            server.tags.set(random.sample(tags, random.randint(1, 3)))

            for _ in range(10):
                DiscordServerSnapshot.objects.create(
                    server=server,
                    member_count=server.member_count,
                    online_count=server.online_count,
                )

        self.stdout.write(self.style.SUCCESS("Discord servers populated"))
