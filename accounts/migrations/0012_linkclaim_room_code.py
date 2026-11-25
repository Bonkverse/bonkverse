from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_remembered_sign_ins"),
    ]

    operations = [
        migrations.AddField(
            model_name="linkclaim",
            name="method",
            field=models.CharField(
                choices=[("friend", "Friend request"), ("room", "Room code")],
                default="friend",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="linkclaim",
            name="code_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="linkclaim",
            name="room_id",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="linkclaim",
            name="room_link",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="linkclaim",
            name="wrong_codes",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
