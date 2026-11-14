"""Tests for the skin each player last wore (players/worn_skins.py), and that
login and wearing record it (accounts/sign_in.py, skins/wear_skin.py)."""

import logging
from datetime import timedelta

import pytest
from django.utils import timezone

from players.models import BonkPlayer, WornSkinSource
from players.services import record_worn_skin
from tests.conftest import load_bonk_fixture
from tests.factories import SKIN_CODE, BonkPlayerFactory, SkinFactory

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
BONK_AVATAR_UPDATE_URL = "https://bonk2.io/scripts/avatar_update.php"
# The skin in login_success.json's active slot (2).
LOGIN_SKIN_CODE = load_bonk_fixture("login_success")["avatar2"]
# A real skin code, URL-encoded the way some imports stored it.
ENCODED_SKIN_CODE = (
    "CgcDYQACCQkBCgcFYWwAAQBNPlt5PUI19d8%2FGMUDPsJvGgAAAAAAAAoFAAEATT5beT1CNfXfvvn8kL80i70BAAAAAAAK"
    "BQABAEs%2BgkonQjVq%2FL2vivk9L4r5AAAAzxsPCgUAAQANP1yl2D9VbKUAAAAAAAAAAAAAAM8bDwAAAAA%3D"
)

pytestmark = pytest.mark.django_db


class TestRecordWornSkin:
    def test_stores_code_source_and_time(self):
        player = BonkPlayerFactory()
        seen_at = timezone.now() - timedelta(minutes=5)

        assert record_worn_skin(player.bonk_id, SKIN_CODE, WornSkinSource.LOGIN, seen_at=seen_at)

        player.refresh_from_db()
        assert player.worn_skin_code == SKIN_CODE
        assert player.worn_skin_seen_at == seen_at
        assert player.worn_skin_source == WornSkinSource.LOGIN

    def test_stores_the_code_url_decoded(self):
        player = BonkPlayerFactory()

        record_worn_skin(player.bonk_id, ENCODED_SKIN_CODE, WornSkinSource.WEAR)

        player.refresh_from_db()
        assert "%" not in player.worn_skin_code
        assert player.worn_skin_code.endswith("AAAAA=")

    def test_newer_sighting_replaces_older(self):
        player = BonkPlayerFactory()
        now = timezone.now()
        record_worn_skin(
            player.bonk_id, SKIN_CODE, WornSkinSource.LOGIN, seen_at=now - timedelta(1)
        )

        assert record_worn_skin(player.bonk_id, ENCODED_SKIN_CODE, WornSkinSource.WEAR, seen_at=now)

        player.refresh_from_db()
        assert player.worn_skin_source == WornSkinSource.WEAR

    def test_older_sighting_does_not_replace_newer(self):
        player = BonkPlayerFactory()
        now = timezone.now()
        record_worn_skin(player.bonk_id, SKIN_CODE, WornSkinSource.WEAR, seen_at=now)

        stored = record_worn_skin(
            player.bonk_id, ENCODED_SKIN_CODE, WornSkinSource.LOGIN, seen_at=now - timedelta(1)
        )

        assert stored is False
        player.refresh_from_db()
        assert (player.worn_skin_code, player.worn_skin_source) == (SKIN_CODE, WornSkinSource.WEAR)

    def test_text_that_is_not_a_skin_is_not_stored(self, caplog):
        player = BonkPlayerFactory()

        with caplog.at_level(logging.WARNING, logger="players.worn_skins"):
            stored = record_worn_skin(player.bonk_id, "POC-FINAL-002", WornSkinSource.WEAR)

        assert stored is False
        player.refresh_from_db()
        assert player.worn_skin_code is None
        assert "POC-FINAL-002" not in caplog.text
        assert "isn't a skin code" in caplog.text

    @pytest.mark.parametrize("skin_code", [None, ""])
    def test_no_code_stores_nothing(self, skin_code):
        player = BonkPlayerFactory()

        assert record_worn_skin(player.bonk_id, skin_code, WornSkinSource.LOGIN) is False

    def test_no_or_unknown_player_stores_nothing(self):
        assert record_worn_skin(None, SKIN_CODE, WornSkinSource.LOGIN) is False
        assert record_worn_skin(999_999_999, SKIN_CODE, WornSkinSource.LOGIN) is False
        assert not BonkPlayer.objects.exists()


class TestLoginRecordsWornSkin:
    def test_site_login_stores_the_active_slots_skin(self, client, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        client.post("/login/", {"username": "TestPlayer", "password": "hunter2"})

        player = BonkPlayer.objects.get(bonk_id=1234567)
        assert player.worn_skin_code == LOGIN_SKIN_CODE
        assert player.worn_skin_source == WornSkinSource.LOGIN

    def test_login_with_an_empty_active_slot_stores_nothing(self, client, mocked_http):
        body = {**load_bonk_fixture("login_success"), "activeAvatarNumber": 3}
        mocked_http.post(BONK_LOGIN_URL, json=body)

        client.post("/login/", {"username": "TestPlayer", "password": "hunter2"})

        assert BonkPlayer.objects.get(bonk_id=1234567).worn_skin_code is None

    def test_a_bad_skin_code_does_not_stop_the_login(self, client, mocked_http):
        body = {**load_bonk_fixture("login_success"), "avatar2": "not a skin"}
        mocked_http.post(BONK_LOGIN_URL, json=body)

        response = client.post("/login/", {"username": "TestPlayer", "password": "hunter2"})

        assert response.status_code == 302
        assert "_auth_user_id" in client.session
        assert BonkPlayer.objects.get(bonk_id=1234567).worn_skin_code is None

    def test_wear_modal_login_stores_identity_and_skin(self, logged_in_client, mocked_http):
        BonkPlayerFactory(bonk_id=1234567, username="TestPlayer")
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        logged_in_client.post(
            "/api/bonk/login/", {"bonk_username": "TestPlayer", "bonk_password": "hunter2"}
        )

        assert logged_in_client.session["bonk_user_id"] == 1234567
        player = BonkPlayer.objects.get(bonk_id=1234567)
        assert player.worn_skin_code == LOGIN_SKIN_CODE


@pytest.fixture
def wearing_client(bonk_session_client):
    """bonk_session_client (active slot 2) whose session names its player."""
    player = BonkPlayerFactory()
    session = bonk_session_client.session
    session["bonk_user_id"] = player.bonk_id
    session.save()
    bonk_session_client.player = player
    return bonk_session_client


class TestWearRecordsWornSkin:
    @pytest.fixture
    def bonk_accepts(self, mocked_http):
        return mocked_http.post(
            BONK_AVATAR_UPDATE_URL, json=load_bonk_fixture("avatar_update_success")
        )

    def test_wear_into_active_slot_is_recorded(self, wearing_client, bonk_accepts):
        skin = SkinFactory()

        wearing_client.post(f"/api/skins/{skin.id}/wear/")

        player = wearing_client.player
        player.refresh_from_db()
        assert player.worn_skin_code == SKIN_CODE
        assert player.worn_skin_source == WornSkinSource.WEAR

    def test_editor_code_worn_into_active_slot_is_recorded(self, wearing_client, bonk_accepts):
        wearing_client.post("/api/skins/wear-code/", {"skin_code": SKIN_CODE})

        wearing_client.player.refresh_from_db()
        assert wearing_client.player.worn_skin_code == SKIN_CODE

    def test_wear_into_another_slot_is_not_recorded(self, wearing_client, bonk_accepts):
        skin = SkinFactory()

        wearing_client.post(f"/api/skins/{skin.id}/wear/", {"slot": "4"})

        wearing_client.player.refresh_from_db()
        assert wearing_client.player.worn_skin_code is None

    def test_refused_wear_is_not_recorded(self, wearing_client, mocked_http):
        mocked_http.post(BONK_AVATAR_UPDATE_URL, json=load_bonk_fixture("avatar_update_too_big"))
        skin = SkinFactory()

        wearing_client.post(f"/api/skins/{skin.id}/wear/")

        wearing_client.player.refresh_from_db()
        assert wearing_client.player.worn_skin_code is None

    def test_a_recording_failure_still_reports_the_wear(
        self, wearing_client, bonk_accepts, monkeypatch
    ):
        def broken(*args, **kwargs):
            raise RuntimeError("database hiccup")

        monkeypatch.setattr("skins.wear_skin.record_worn_skin", broken)
        skin = SkinFactory()

        response = wearing_client.post(f"/api/skins/{skin.id}/wear/")

        assert response.json() == {"ok": True, "slot": 2}

    def test_session_without_identity_records_nothing(self, bonk_session_client, bonk_accepts):
        skin = SkinFactory()

        response = bonk_session_client.post(f"/api/skins/{skin.id}/wear/")

        assert response.json()["ok"] is True
        assert not BonkPlayer.objects.filter(worn_skin_seen_at__isnull=False).exists()
