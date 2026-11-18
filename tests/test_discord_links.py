"""Discord ↔ bonk.io links (accounts/discord_links.py), the LevelBot import and
BonxBot's lookup API (GET /api/bot/discord-links/<id>/)."""

from datetime import datetime, timezone
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import IntegrityError

from accounts.models import DiscordLink
from accounts.services import discord_links_for, import_levelbot_links
from integrations.levelbot_db import LevelBotAccount
from players.models import BonkPlayer
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

TOKEN = "bot-secret"
TULIP_DISCORD = 1009876543210987654
OTHER_DISCORD = 222222222222222222
WHEN = datetime(2025, 9, 1, tzinfo=timezone.utc)


def _row(discord_id, name, main=True, when=WHEN):
    return LevelBotAccount(str(discord_id), name, main, when)


def _names(links):
    return [(link.bonk_player.username, link.is_default) for link in links]


# --- import -------------------------------------------------------------------


def test_main_becomes_default_and_alts_are_kept():
    report = import_levelbot_links(
        [
            _row(TULIP_DISCORD, "The Saucy Tulip", main=True),
            _row(TULIP_DISCORD, "Tulip Alt", main=False),
        ]
    )

    assert report.counts == {"imported": 2}
    assert _names(discord_links_for(TULIP_DISCORD)) == [
        ("The Saucy Tulip", True),
        ("Tulip Alt", False),
    ]
    link = DiscordLink.objects.get(bonk_player__username="The Saucy Tulip")
    assert (link.source, link.verified_at) == ("levelbot_import", WHEN)


def test_known_player_is_matched_ignoring_case():
    player = BonkPlayer.objects.create(bonk_id=4242, username="The Saucy Tulip")

    report = import_levelbot_links([_row(TULIP_DISCORD, "the saucy tulip")])

    assert report.new_players == 0
    assert DiscordLink.objects.get().bonk_player == player


def test_unknown_name_is_added_as_a_name_only_player():
    report = import_levelbot_links([_row(TULIP_DISCORD, " Spaced Name")])

    assert report.new_players == 1
    player = BonkPlayer.objects.get()
    assert (player.username, player.bonk_id) == (" Spaced Name", None)  # spaces kept


def test_player_already_tied_to_another_discord_user_is_left_alone():
    import_levelbot_links([_row(OTHER_DISCORD, "The Saucy Tulip")])

    report = import_levelbot_links([_row(TULIP_DISCORD, "The Saucy Tulip")])

    assert report.counts == {"claimed_by_another_discord": 1}
    assert DiscordLink.objects.get().discord_user_id == OTHER_DISCORD


def test_rerun_changes_nothing():
    rows = [_row(TULIP_DISCORD, "The Saucy Tulip"), _row(TULIP_DISCORD, "Alt", main=False)]
    import_levelbot_links(rows)

    report = import_levelbot_links(rows)

    assert report.counts == {"already_linked": 2}
    assert report.new_players == 0
    assert DiscordLink.objects.count() == 2


def test_user_without_a_main_gets_their_first_account_as_default():
    import_levelbot_links(
        [_row(TULIP_DISCORD, "First", main=False), _row(TULIP_DISCORD, "Second", main=False)]
    )

    assert _names(discord_links_for(TULIP_DISCORD)) == [("First", True), ("Second", False)]


@pytest.mark.parametrize("discord_id", ["", "not-a-number", "0", "-5"])
def test_bad_discord_id_is_skipped(discord_id):
    report = import_levelbot_links([_row(discord_id, "The Saucy Tulip")])

    assert report.counts == {"bad_discord_id": 1}
    assert not DiscordLink.objects.exists()
    assert not BonkPlayer.objects.exists()


@pytest.mark.parametrize("name", ["", "   ", None])
def test_blank_name_is_skipped(name):
    report = import_levelbot_links([_row(TULIP_DISCORD, name)])

    assert report.counts == {"blank_name": 1}
    assert not BonkPlayer.objects.exists()


def test_dry_run_counts_exactly_and_writes_nothing():
    report = import_levelbot_links(
        [_row(TULIP_DISCORD, "The Saucy Tulip"), _row(TULIP_DISCORD, "Alt", main=False)],
        dry_run=True,
    )

    assert report.counts == {"imported": 2}
    assert report.new_players == 2
    assert not DiscordLink.objects.exists()
    assert not BonkPlayer.objects.exists()


def test_other_users_links_are_not_returned():
    import_levelbot_links([_row(TULIP_DISCORD, "Tulip"), _row(OTHER_DISCORD, "Somepoop")])

    assert _names(discord_links_for(OTHER_DISCORD)) == [("Somepoop", True)]
    assert discord_links_for(333) == []


# --- database rules ---------------------------------------------------------------


def test_one_default_per_discord_user():
    a = BonkPlayer.objects.create(username="A")
    b = BonkPlayer.objects.create(username="B")
    DiscordLink.objects.create(
        discord_user_id=1, bonk_player=a, source="levelbot_import", is_default=True
    )

    with pytest.raises(IntegrityError):
        DiscordLink.objects.create(
            discord_user_id=1, bonk_player=b, source="levelbot_import", is_default=True
        )


def test_one_discord_user_per_player():
    player = BonkPlayer.objects.create(username="A")
    DiscordLink.objects.create(discord_user_id=1, bonk_player=player, source="levelbot_import")

    with pytest.raises(IntegrityError):
        DiscordLink.objects.create(discord_user_id=2, bonk_player=player, source="levelbot_import")


# --- command ------------------------------------------------------------------------


class _FakeLevelBotDB:
    rows = []

    def __init__(self, url):
        assert url == "postgresql://levelbot.test/db"

    def accounts(self):
        return list(self.rows)

    def close(self):
        pass


def test_command_dry_run_then_write(monkeypatch):
    monkeypatch.setattr(
        "accounts.management.commands.import_levelbot_links.LevelBotDB", _FakeLevelBotDB
    )
    _FakeLevelBotDB.rows = [_row(TULIP_DISCORD, "The Saucy Tulip")]
    monkeypatch.setenv("LEVELBOT_DATABASE_URL", "postgresql://levelbot.test/db")

    dry = StringIO()
    call_command("import_levelbot_links", "--dry-run", stdout=dry)
    assert "imported: 1" in dry.getvalue()
    assert "new players (name only): 1" in dry.getvalue()
    assert not DiscordLink.objects.exists()

    out = StringIO()
    call_command(
        "import_levelbot_links", "--database-url", "postgresql://levelbot.test/db", stdout=out
    )
    assert "Read 1 LevelBot account(s)." in out.getvalue()
    assert DiscordLink.objects.count() == 1


def test_command_needs_a_database_url(monkeypatch):
    monkeypatch.delenv("LEVELBOT_DATABASE_URL", raising=False)

    with pytest.raises(CommandError, match="LEVELBOT_DATABASE_URL"):
        call_command("import_levelbot_links")


# --- BonxBot lookup API -------------------------------------------------------------


def _url(discord_id=TULIP_DISCORD):
    return f"/api/bot/discord-links/{discord_id}/"


@pytest.fixture
def bot_token(settings):
    settings.BONXBOT_API_TOKEN = TOKEN


def test_api_lists_links_default_first(client, bot_token):
    BonkPlayer.objects.create(bonk_id=4242, username="The Saucy Tulip")
    import_levelbot_links(
        [_row(TULIP_DISCORD, "Tulip Alt", main=False), _row(TULIP_DISCORD, "The Saucy Tulip")]
    )

    response = client.get(_url(), headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "links": [
            {
                "bonk_username": "Tulip Alt",
                "bonk_id": None,
                "is_default": True,
                "source": "levelbot_import",
                "verified_at": "2025-09-01T00:00:00+00:00",
            },
            {
                "bonk_username": "The Saucy Tulip",
                "bonk_id": 4242,
                "is_default": False,
                "source": "levelbot_import",
                "verified_at": "2025-09-01T00:00:00+00:00",
            },
        ],
    }


def test_api_unknown_user_gets_an_empty_list(client, bot_token):
    response = client.get(_url(333), headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.json() == {"ok": True, "links": []}


@pytest.mark.parametrize("header", [None, "Bearer wrong", "Bearer "])
def test_api_refuses_without_the_token(client, bot_token, header):
    headers = {"Authorization": header} if header else {}

    response = client.get(_url(), headers=headers)

    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "unauthorized"}


def test_api_refuses_everyone_while_no_token_is_configured(client, settings):
    settings.BONXBOT_API_TOKEN = ""

    response = client.get(_url(), headers={"Authorization": "Bearer "})

    assert response.status_code == 401


def test_api_is_get_only(client, bot_token):
    response = client.post(_url(), headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 405


def test_admin_search_by_discord_id_or_name(client):
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    import_levelbot_links([_row(TULIP_DISCORD, "The Saucy Tulip")])

    for query in (str(TULIP_DISCORD), "saucy", "not-a-number"):
        response = client.get("/admin/accounts/discordlink/", {"q": query})
        assert response.status_code == 200, query
