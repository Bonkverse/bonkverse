"""Roles on player profiles (players/roles.py): ButDogeBot is marked as a bot."""

import pytest

from players.models import BonkPlayer
from players.roles import role_for

pytestmark = pytest.mark.django_db

DESCRIPTION = "This is a Human-Controlled bot, and is not affiliated with Bonk.io"


@pytest.mark.parametrize("name", ["ButDogeBot", "butdogebot", "BUTDOGEBOT"])
def test_butdogebot_is_a_bot_whatever_the_case(name):
    role = role_for(name)
    assert role.label == "Bot"
    assert role.description == DESCRIPTION


@pytest.mark.parametrize("name", ["ButDoge", "ButDogeBot2", "", None])
def test_other_players_have_no_role(name):
    assert role_for(name) is None


def test_the_profile_shows_the_role_and_what_it_means(client):
    BonkPlayer.objects.create(username="ButDogeBot", bonk_id=123456)

    page = client.get("/player/ButDogeBot/").content.decode()

    assert '<span class="bv-pill bv-pill--accent"' in page
    assert ">Bot</span>" in page
    assert DESCRIPTION in page


def test_other_profiles_show_no_role(client):
    BonkPlayer.objects.create(username="SomeoneElse", bonk_id=654321)

    page = client.get("/player/SomeoneElse/").content.decode()

    assert DESCRIPTION not in page
    assert ">Bot</span>" not in page
