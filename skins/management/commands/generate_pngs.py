# import os
# import cairosvg
# from django.core.management.base import BaseCommand
# from django.conf import settings

# IMAGE_DIR = os.path.join(settings.MEDIA_ROOT, "skins")

# class Command(BaseCommand):
#     help = "Generate PNG (512px) and thumbnail (128px) from SVGs"

#     def handle(self, *args, **options):
#         svg_files = [f for f in os.listdir(IMAGE_DIR) if f.endswith(".svg")]
#         self.stdout.write(f"Found {len(svg_files)} SVGs to process...")

#         for svg_file in svg_files:
#             skin_id = os.path.splitext(svg_file)[0]
#             svg_path = os.path.join(IMAGE_DIR, svg_file)
#             png_path = os.path.join(IMAGE_DIR, f"{skin_id}.png")
#             thumb_path = os.path.join(IMAGE_DIR, f"{skin_id}_thumb.png")

#             try:
#                 # Full PNG
#                 if not os.path.exists(png_path):
#                     cairosvg.svg2png(
#                         url=svg_path,
#                         write_to=png_path,
#                         output_width=512,
#                         output_height=512
#                     )
#                     self.stdout.write(self.style.SUCCESS(f"Generated PNG for {skin_id}"))
#                 else:
#                     self.stdout.write(self.style.WARNING(f"PNG already exists for {skin_id}"))

#                 # Thumbnail
#                 if not os.path.exists(thumb_path):
#                     cairosvg.svg2png(
#                         url=svg_path,
#                         write_to=thumb_path,
#                         output_width=128,
#                         output_height=128
#                     )
#                     self.stdout.write(self.style.SUCCESS(f"Generated thumbnail for {skin_id}"))
#                 else:
#                     self.stdout.write(self.style.WARNING(f"Thumbnail already exists for {skin_id}"))

#             except Exception as e:
#                 self.stdout.write(self.style.ERROR(f"Failed {skin_id}: {e}"))

import os
import cairosvg
from django.core.management.base import BaseCommand
from django.conf import settings
from concurrent.futures import ProcessPoolExecutor, as_completed

IMAGE_DIR = os.path.join(settings.MEDIA_ROOT, "skins")

def convert_svg(svg_file):
    """Worker: convert a single SVG into PNG + thumbnail."""
    skin_id = os.path.splitext(svg_file)[0]
    svg_path = os.path.join(IMAGE_DIR, svg_file)
    png_path = os.path.join(IMAGE_DIR, f"{skin_id}.png")
    thumb_path = os.path.join(IMAGE_DIR, f"{skin_id}_thumb.png")

    results = []
    try:
        # Full PNG (512x512)
        if not os.path.exists(png_path):
            cairosvg.svg2png(url=svg_path, write_to=png_path,
                             output_width=512, output_height=512)
            results.append(f"✔ PNG for {skin_id}")
        else:
            results.append(f"⚠ PNG exists {skin_id}")

        # Thumbnail (128x128)
        if not os.path.exists(thumb_path):
            cairosvg.svg2png(url=svg_path, write_to=thumb_path,
                             output_width=128, output_height=128)
            results.append(f"✔ Thumb for {skin_id}")
        else:
            results.append(f"⚠ Thumb exists {skin_id}")

        return results

    except Exception as e:
        return [f"✘ Failed {skin_id}: {e}"]


class Command(BaseCommand):
    help = "Parallel PNG + thumbnail generation from SVGs"

    def handle(self, *args, **options):
        svg_files = [f for f in os.listdir(IMAGE_DIR) if f.endswith(".svg")]
        self.stdout.write(f"Found {len(svg_files)} SVGs to process...")

        # Use all cores (or pass max_workers=N to limit)
        with ProcessPoolExecutor() as executor:
            futures = [executor.submit(convert_svg, f) for f in svg_files]

            for future in as_completed(futures):
                for msg in future.result():
                    if msg.startswith("✔"):
                        self.stdout.write(self.style.SUCCESS(msg))
                    elif msg.startswith("⚠"):
                        self.stdout.write(self.style.WARNING(msg))
                    else:
                        self.stdout.write(self.style.ERROR(msg))
