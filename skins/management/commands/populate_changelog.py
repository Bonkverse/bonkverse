from django.core.management.base import BaseCommand
from skins.models import Changelog

class Command(BaseCommand):
    help = "Populate changelog"

    def handle(self, *args, **kwargs):
        for i in range(20):
            Changelog.objects.create(
                title=f"Dev Update {i}",
                content="This is a seeded changelog entry.",
                version=f"0.{i}",
            )

        self.stdout.write(self.style.SUCCESS("Changelog populated"))
