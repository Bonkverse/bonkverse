"""An index on each player's folded name, lower(username COLLATE "C")
(core.db.folded), for the Players list's one-row-per-name check
(players.selectors._one_row_per_name).

Raw SQL because Django can't put a collation inside an index expression.
Built CONCURRENTLY so the players table stays writable while it builds.
"""

from django.db import migrations

INDEX = "skins_bonkp_folded_name_idx"


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("players", "0008_user_fields_point_at_accounts"),
    ]

    operations = [
        migrations.RunSQL(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} "
            f'ON skins_bonkplayer (lower(username COLLATE "C"))',
            reverse_sql=f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}",
        ),
    ]
