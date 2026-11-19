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


# ── The pages (design review: Discord servers) ───────────────────────


@pytest.mark.django_db
def test_list_has_no_placeholder_text_and_groups_numbers(client):
    _server("1", name="Quiet", description="", member_count=12345, online_count=678)

    html = client.get("/serverlist/").content.decode()

    assert "12,345 members · 678 online" in html
    assert "No description provided" not in html
    assert "No tags provided" not in html


@pytest.mark.django_db
def test_tag_chips_are_links_that_toggle_the_tag_and_keep_the_search(client):
    DiscordTag.objects.create(name="competitive")
    DiscordTag.objects.create(name="casual")

    html = client.get("/serverlist/?q=bonk&tag=casual").content.decode()

    assert (
        'href="?q=bonk&amp;tag=casual&amp;tag=competitive" aria-pressed="false">competitive' in html
    )
    assert 'href="?q=bonk" aria-pressed="true">casual' in html


def test_tag_filters_toggle():
    tags = [DiscordTag(name="a"), DiscordTag(name="b")]

    chips = selectors.tag_filters(tags, ["a"], "")

    assert chips == [
        {"name": "a", "on": True, "href": "?"},
        {"name": "b", "on": False, "href": "?tag=a&tag=b"},
    ]


@pytest.mark.django_db
def test_icons_fall_back_to_a_letter_without_a_broken_image(client):
    _server("1", name="bonk club", icon_hash="abc")
    _server("2", name="Zed", icon_hash="")

    html = client.get("/serverlist/").content.decode()

    assert 'src="https://cdn.discordapp.com/icons/1/abc.png?size=128" alt=""' in html
    assert "communities/js/servers.js" in html  # removes icons that fail to load
    assert ">B</span>" in html and ">Z</span>" in html


@pytest.mark.django_db
def test_list_is_a_fixed_number_of_queries(client, django_assert_max_num_queries):
    tag = DiscordTag.objects.create(name="competitive")
    for i in range(10):
        _server(str(i), name=f"S{i}").tags.add(tag)

    with django_assert_max_num_queries(4):  # servers, their tags, all tags, refresh time
        client.get("/serverlist/")


@pytest.mark.django_db
def test_empty_search_says_so_and_offers_all_servers(client):
    html = client.get("/serverlist/?q=nothing").content.decode()

    assert "No servers match" in html
    assert 'href="/serverlist/">Show all servers' in html


def test_growth_chart_line_and_change():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    snaps = [
        DiscordServerSnapshot(
            member_count=c, online_count=0, recorded_at=start + timedelta(hours=i)
        )
        for i, c in enumerate([100, 120, 110])
    ]

    chart = selectors.growth_chart(snaps, width=100, height=50)

    assert chart["points"] == "8.0,42.0 50.0,8.0 92.0,25.0"
    assert (chart["low"], chart["high"], chart["change"], chart["change_size"]) == (
        100,
        120,
        10,
        10,
    )
    assert selectors.growth_chart(snaps[:1]) is None


@pytest.mark.django_db
def test_detail_shows_the_growth_chart(client):
    server = _server("1", name="Grower", member_count=130)
    for i, count in enumerate([100, 130]):
        DiscordServerSnapshot.objects.create(
            server=server,
            member_count=count,
            online_count=1,
            recorded_at=datetime(2026, 11, 1, tzinfo=UTC) + timedelta(hours=i),
        )

    html = client.get(f"/{server.id}/").content.decode()

    assert "<polyline" in html
    assert "↑ 30" in html
