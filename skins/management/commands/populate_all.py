from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = "Populate all local dev data"
    

    def handle(self, *args, **kwargs):
        self.stdout.write("Installing Postgres extensions...")
        call_command("init_pg_extensions")

        commands = [
            "populate_bonkplayers",
            "populate_friendships",
            "populate_skins",
            "populate_changelog",
            "populate_player_stats",
            "populate_discord",
            "populate_flashfriends",
        ]

        for cmd in commands:
            self.stdout.write(f"Running {cmd}...")
            call_command(cmd)

        self.stdout.write(self.style.SUCCESS("All dev data populated"))
