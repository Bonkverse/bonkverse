"""Room codes prove accounts already on Bonkverse (2026-11-27, ADR 0026).

- `BonkAccountLink.room_proven_at` / `room_level`: a room-code proof, kept
  apart from `password_proven_at` so a later password can still take the
  account back from a relayed code (sign_in._reclaim).
- `LinkClaim.bonk_level`: the level a room showed for the proven player.

Only new nullable columns: code from before and after the deploy both work.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0012_linkclaim_room_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="bonkaccountlink",
            name="room_level",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bonkaccountlink",
            name="room_proven_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="linkclaim",
            name="bonk_level",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
