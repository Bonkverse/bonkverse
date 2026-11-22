"""Seed a small, fixed set of data for the browser checks.

scripts/check_responsive.mjs and scripts/check_contrast.mjs look at real
pages, so the pages need something on them: skins with images (drawn here,
no network), a reported skin, a category cover, players, Discord servers,
and a staff account whose session the scripts use for signed-in pages, with
an API key (prefix "uicheck0") and a few weeks of its usage.
CI runs this on an empty database (.github/workflows/ci.yml, job
"browser"); on an empty database the first skin is /skins/detail/1, the
page the scripts open.

Safe to run twice. Refuses to run in production: it creates a staff
account with a session anyone holding the file could use.

    python manage.py seed_ui_checks [--session-file path]
"""

from datetime import timedelta
from pathlib import Path

import cairosvg
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.utils import timezone

from accounts.models import BonkUser
from communities.models import DiscordServer, DiscordTag
from players.models import BonkPlayer
from public_api.models import ApiKey, ApiKeyUsageDay
from skins.models import MODERATOR_GROUP, CategoryCover, Skin, SkinReport

STAFF = "ui-check-staff"
API_KEY_PREFIX = "uicheck0"  # /developers/keys/uicheck0/ in the check scripts
SKINS = [
    # name, creator, upvotes, downvotes, themes (category keywords)
    ("Bongo Cat", "Isabelle26", 41, 2, ["cat", "animal", "cute"]),
    ("Minimal Fox", STAFF, 30, 1, ["fox", "minimal"]),
    ("Red Planet", "legendboss", 25, 4, ["planet", "space"]),
    ("Teal Wave", "ButDoge", 18, 0, ["ocean", "wave", "nature"]),
    ("Night Sky", "Magic", 12, 3, ["star", "space"]),
    ("Pixel Heart", STAFF, 9, 1, ["pixel", "8-bit"]),
    ("Flag of Somewhere", "The Saucy Tulip", 7, 2, ["flag"]),
    ("Fire Ball", "zorro", 6, 5, ["fire", "flame"]),
    ("A Very Long Skin Name That Has To Wrap On Small Phones", "someone", 3, 0, ["meme"]),
    ("Reported Skin", "someone", 1, 9, ["logo"]),
]
COLORS = ["#ffc400", "#ff7043", "#e53935", "#26a69a", "#3949ab", "#ec407a", "#43a047", "#fb8c00"]


def _image(skin, index):
    """Draw a simple ball for the skin into MEDIA_ROOT/skins/<id>.png."""
    color, ring = COLORS[index % len(COLORS)], COLORS[(index + 3) % len(COLORS)]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">'
        f'<circle cx="128" cy="128" r="120" fill="{ring}"/>'
        f'<circle cx="128" cy="128" r="96" fill="{color}"/></svg>'
    )
    folder = Path(settings.MEDIA_ROOT) / "skins"
    folder.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(folder / f"{skin.id}.png"))
    return f"{settings.MEDIA_URL}skins/{skin.id}.png"


class Command(BaseCommand):
    help = "Seed fixed data for the browser checks (not for production)."

    def add_arguments(self, parser):
        parser.add_argument("--session-file", help="Write the staff account's session id here.")

    def handle(self, *args, session_file=None, **options):
        if settings.IS_PROD:
            raise CommandError("seed_ui_checks makes a staff account: never in production.")

        staff, _ = BonkUser.objects.get_or_create(username=STAFF)
        if not staff.is_staff:
            staff.is_staff = True
            staff.save(update_fields=["is_staff"])
        staff.groups.add(Group.objects.get(name=MODERATOR_GROUP))  # the report queue

        skins = []
        for i, (name, creator, up, down, themes) in enumerate(SKINS):
            labels = {"style": "", "themes": themes, "objects": [], "references": [], "colors": []}
            skin, _ = Skin.objects.get_or_create(
                name=name,
                defaults={
                    "creator": creator,
                    "upvotes": up,
                    "downvotes": down,
                    "labels": labels,
                    "skin_code": "",
                },
            )
            if not skin.image_url or not skin.image_url.startswith(settings.MEDIA_URL):
                skin.image_url = _image(skin, i)
                skin.save(update_fields=["image_url"])
            skins.append(skin)

        staff.favorite_skins.add(skins[0], skins[2])
        SkinReport.objects.get_or_create(
            skin=skins[-1], reporter=None, reason="inappropriate", details="seeded report"
        )
        CategoryCover.objects.get_or_create(category="animals", defaults={"skin": skins[0]})
        CategoryCover.objects.get_or_create(category="space", defaults={"skin": skins[2]})

        for i, name in enumerate(["tester", "Isabelle26", "legendboss", "ButDoge", "Magic", STAFF]):
            BonkPlayer.objects.get_or_create(
                username=name, defaults={"bonk_id": 900_000 + i, "last_friend_count": 10 * i}
            )

        tag, _ = DiscordTag.objects.get_or_create(name="Competitive")
        for i, name in enumerate(["Bonk League", "Death Arrows Club", "Skin Makers"]):
            server, _ = DiscordServer.objects.get_or_create(
                guild_id=str(100_000 + i),
                defaults={
                    "name": name,
                    "invite_code": f"seed{i}",
                    "invite_url": f"https://discord.gg/seed{i}",
                    "description": "A seeded server for the browser checks.",
                    "member_count": 120 * (i + 1),
                    "online_count": 12 * (i + 1),
                },
            )
            server.tags.add(tag)

        api_key, _ = ApiKey.objects.get_or_create(
            prefix=API_KEY_PREFIX,
            defaults={
                "name": "League leaderboard bot",
                "owner": staff,
                # Not the hash of any key: nothing can call the API with it.
                "key_hash": "0" * 64,
            },
        )
        today = timezone.now().date()
        for days_ago in range(0, 24, 2):
            for endpoint, requests in (("player", 400 - 12 * days_ago), ("lookup_players", 20)):
                ApiKeyUsageDay.objects.get_or_create(
                    api_key=api_key,
                    day=today - timedelta(days=days_ago),
                    endpoint=endpoint,
                    defaults={
                        "requests": requests,
                        "errors": days_ago % 3,
                        "rate_limited": days_ago % 5,
                    },
                )

        if session_file:
            client = Client()
            client.force_login(staff)
            Path(session_file).write_text(client.cookies[settings.SESSION_COOKIE_NAME].value)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(skins)} skins (first is /skins/detail/{skins[0].id}), "
                f"players, Discord servers and staff account {STAFF}."
            )
        )
