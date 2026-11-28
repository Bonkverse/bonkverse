"""Room codes prove existing accounts (2026-11-27, ADR 0026).

- `BonkAccountLink.password_proven_at` is now `owner_proven_at` in code (a
  room code counts like a password). The column keeps its name, so this is
  a state-only change: code from before and after the deploy both work.
- `LinkClaim.bonk_level`: the level a room showed for the proven player.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_linkclaim_room_code")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="bonkaccountlink",
                    old_name="password_proven_at",
                    new_name="owner_proven_at",
                ),
                migrations.AlterField(
                    model_name="bonkaccountlink",
                    name="owner_proven_at",
                    field=models.DateTimeField(
                        blank=True, db_column="password_proven_at", null=True
                    ),
                ),
            ],
            database_operations=[],
        ),
        migrations.AddField(
            model_name="linkclaim",
            name="bonk_level",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
