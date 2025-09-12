from django.core.management.base import BaseCommand
from skins.models import Skin, SkinImage

class Command(BaseCommand):
    help = "Populate skin_images table with svg/png/thumbnail rows for all skins"

    def handle(self, *args, **options):
        skins = Skin.objects.all()
        objs = []
        for skin in skins:
            objs.append(SkinImage(skin=skin, kind="svg", path=f"skins/{skin.id}.svg"))
            objs.append(SkinImage(skin=skin, kind="png", path=f"skins/{skin.id}.png"))
            objs.append(SkinImage(skin=skin, kind="thumbnail", path=f"skins/{skin.id}_thumb.png"))

        SkinImage.objects.bulk_create(objs, ignore_conflicts=True)
        self.stdout.write(self.style.SUCCESS(f"Populated {len(objs)} skin_images rows"))
