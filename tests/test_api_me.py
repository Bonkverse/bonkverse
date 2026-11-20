"""/api/me/ (accounts/views.py): who is signed in, for the skin editor and
the shared header on replays.bonkverse.io and docs.bonkverse.io."""

import pytest

from accounts.models import BonkAccountLink
from players.models import BonkPlayer

pytestmark = pytest.mark.django_db


def test_signed_out_is_401(client):
    response = client.get("/api/me/")

    assert response.status_code == 401
    assert response.json() == {"authenticated": False}


def test_signed_in_without_a_seen_skin_has_no_avatar(logged_in_client, user):
    data = logged_in_client.get("/api/me/").json()

    assert data["authenticated"] is True
    assert data["user"]["username"] == user.username
    assert data["user"]["avatar"] is None


def test_avatar_is_the_worn_skins_thumbnail_as_an_absolute_url(logged_in_client, user):
    player = BonkPlayer.objects.create(bonk_id=7, username="Isabelle26", worn_skin_code="code-1")
    BonkAccountLink.objects.create(
        user=user, bonk_player=player, token_encrypted=BonkAccountLink.encrypt_token("t0k")
    )

    avatar = logged_in_client.get("/api/me/").json()["user"]["avatar"]

    # Absolute, because the replay and docs sites load it from their own origin
    assert avatar.startswith("http://testserver/player/Isabelle26/")
    assert "?v=" in avatar
