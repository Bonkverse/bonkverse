# skins/migrations/0023_flashfriend_partial_unique.py

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('skins', '0022_userevent'),
    ]

    operations = [
        # Drop the old unique_together — Postgres treats every NULL as
        # distinct, so this never actually deduplicated unresolved
        # (bonk_player IS NULL) rows, which is nearly all of them.
        migrations.AlterUniqueTogether(
            name='flashfriend',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='flashfriend',
            constraint=models.UniqueConstraint(
                condition=models.Q(bonk_player__isnull=False),
                fields=('name', 'bonk_player'),
                name='uniq_flashfriend_name_player_resolved',
            ),
        ),
        migrations.AddConstraint(
            model_name='flashfriend',
            constraint=models.UniqueConstraint(
                condition=models.Q(bonk_player__isnull=True),
                fields=('name',),
                name='uniq_flashfriend_name_unresolved',
            ),
        ),
    ]