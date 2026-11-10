"""The communities app (Discord directory) after its move out of skins/
(RFC-0001 Phase 5.2 code, 5.2b models): the parts a move could silently
break, plus its selectors and service called directly. The submit and refresh flows
themselves are covered end to end in tests/test_discord.py.
"""

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from bonk_skin_search.celery_app import app as celery_app
from communities import selectors
from communities.models import DiscordServer, DiscordServerSnapshot, DiscordTag
from communities.services import SubmitOutcome, extract_invite_code, submit_server
from communities.tasks import refresh_discord_servers

INITIAL = importlib.import_module("communities.migrations.0001_initial")


def _server(guild_id, **fields):
    defaults = {
        "invite_code": f"code{guild_id}",
        "invite_url": f"https://discord.gg/code{guild_id}",
        "name": f"Server {guild_id}",
    }
    return DiscordServer.objects.create(guild_id=guild_id, **{**defaults, **fields})


# ---------- the move kept the task's name ----------


def test_refresh_task_keeps_its_registered_name():
    """Saved schedules and runs queued before a deploy name the task by its
    old path; the worker must still know it by that name."""
    celery_app.loader.import_default_modules()

    assert refresh_discord_servers.name == "skins.tasks.refresh_discord_servers"
    # shared_task hands back a proxy, so compare the code the worker would run.
    assert celery_app.tasks[selectors.REFRESH_TASK].run.__module__ == "communities.tasks"


def test_schedule_and_page_use_the_same_task_name():
    schedule = settings.CELERY_BEAT_SCHEDULE["refresh-discord-servers"]

    assert schedule["task"] == selectors.REFRESH_TASK
    assert timedelta(seconds=schedule["schedule"]) == selectors.REFRESH_INTERVAL


# ---------- the model move kept every table ----------


def test_models_keep_their_original_tables():
    """Changing any of these names would make Django rename the real table."""
    assert DiscordTag._meta.db_table == "skins_discordtag"
    assert DiscordServer._meta.db_table == "skins_discordserver"
    assert DiscordServer.tags.through._meta.db_table == "skins_discordserver_tags"
    assert DiscordServerSnapshot._meta.db_table == "skins_discordserversnapshot"
    assert [i.name for i in DiscordServerSnapshot._meta.indexes] == [
        "skins_disco_server__cb589f_idx"
    ]


@pytest.mark.django_db
def test_migration_relabels_content_types_both_ways():
    """Permissions and admin history follow the models: the content type rows
    are relabelled in place (same ids), and back again on reverse."""
    ContentType.objects.filter(app_label="communities", model__in=INITIAL.MODELS).delete()
    old = {m: ContentType.objects.create(app_label="skins", model=m).id for m in INITIAL.MODELS}

    INITIAL.relabel_content_types(apps, None)

    moved = dict(
        ContentType.objects.filter(app_label="communities", model__in=INITIAL.MODELS).values_list(
            "model", "id"
        )
    )
    assert moved == old

    INITIAL.unlabel_content_types(apps, None)

    assert set(
        ContentType.objects.filter(app_label="skins", model__in=INITIAL.MODELS).values_list(
            "id", flat=True
        )
    ) == set(old.values())


# ---------- selectors ----------


@pytest.mark.django_db
def test_listed_servers_filters_and_orders():
    competitive = DiscordTag.objects.create(name="competitive")
    small = _server("1", name="Bonk Club", member_count=10)
    big = _server("2", name="Other", description="bonk league", member_count=500)
    _server("3", name="Bonk Hidden", member_count=999, status="banned")
    big.tags.add(competitive)

    assert list(selectors.listed_servers()) == [big, small]
    assert list(selectors.listed_servers("bonk")) == [big, small]
    assert list(selectors.listed_servers("club")) == [small]
    assert list(selectors.listed_servers(tag_names=["competitive"])) == [big]


@pytest.mark.django_db
def test_next_refresh_is_an_hour_after_the_last_run():
    assert selectors.next_refresh_at() is None

    every_hour = IntervalSchedule.objects.create(every=1, period=IntervalSchedule.HOURS)
    last_run = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    PeriodicTask.objects.create(
        name="refresh-discord-servers",
        task=selectors.REFRESH_TASK,
        interval=every_hour,
        last_run_at=last_run,
    )

    assert selectors.next_refresh_at() == last_run + timedelta(hours=1)


@pytest.mark.django_db
def test_recent_snapshots_are_the_latest_oldest_first():
    server = _server("1")
    start = datetime(2026, 11, 1, tzinfo=UTC)
    for hour in range(5):
        DiscordServerSnapshot.objects.create(
            server=server,
            member_count=hour,
            online_count=0,
            recorded_at=start + timedelta(hours=hour),
        )

    snapshots = selectors.recent_snapshots(server, limit=3)

    assert [s.member_count for s in snapshots] == [2, 3, 4]


# ---------- service ----------


@pytest.mark.parametrize(
    ("typed", "code"),
    [
        ("abc", "abc"),
        ("  abc  ", "abc"),
        ("https://discord.gg/abc", "abc"),
        ("https://discord.com/invite/abc/", "abc"),
        ("https://discord.gg/", ""),
    ],
)
def test_extract_invite_code(typed, code):
    assert extract_invite_code(typed) == code


@pytest.mark.django_db
def test_submit_refuses_before_calling_discord(mocked_http):
    assert submit_server("   ", []).outcome == SubmitOutcome.MISSING_INVITE
    assert submit_server("https://discord.gg/", []).outcome == SubmitOutcome.INVALID_FORMAT
    assert len(mocked_http.calls) == 0
