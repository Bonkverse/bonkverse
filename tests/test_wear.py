"""Characterization tests for wearing skins on bonk.io (skins/wear_skin.py).

They pin the JSON contract the frontend wear/login-modal flow depends on:
- 401 with auth="bonkverse" -> sign in to the site
- 401 with auth="bonk"      -> show the bonk.io login modal
- 401 without auth          -> the bonk.io credentials were wrong
Any refactor in Phases 2-3 (bonk_api client, bv-api.js, one login modal)
must keep these passing.
"""

import time
from urllib.parse import parse_qs

import pytest
import requests

from skins.models import UserEvent
from tests.conftest import load_bonk_fixture
from tests.factories import SkinFactory

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
BONK_AVATAR_UPDATE_URL = "https://bonk2.io/scripts/avatar_update.php"

pytestmark = pytest.mark.django_db


def _wear_url(skin_id):
    return f"/api/skins/{skin_id}/wear/"


def _sent_form(call) -> dict:
    """Decode the form body a mocked request was sent with."""
    return {k: v[0] for k, v in parse_qs(call.request.body).items()}


class TestWearAuthContract:
    def test_anonymous_gets_bonkverse_401(self, client, skin):
        response = client.post(_wear_url(skin.id))

        assert response.status_code == 401
        assert response.json() == {"ok": False, "auth": "bonkverse"}

    def test_logged_in_without_bonk_token_gets_bonk_401(self, logged_in_client, skin):
        response = logged_in_client.post(_wear_url(skin.id))

        assert response.status_code == 401
        assert response.json() == {"ok": False, "auth": "bonk"}

    def test_expired_bonk_token_gets_bonk_401(self, logged_in_client, skin):
        session = logged_in_client.session
        session["bonk_token"] = "old-token"
        session["bonk_token_expires"] = time.time() - 1
        session.save()

        response = logged_in_client.post(_wear_url(skin.id))

        assert response.status_code == 401
        assert response.json()["auth"] == "bonk"

    def test_get_is_not_allowed(self, bonk_session_client, skin):
        response = bonk_session_client.get(_wear_url(skin.id))

        assert response.status_code == 405


class TestWearSkin:
    @pytest.fixture
    def bonk_accepts(self, mocked_http):
        return mocked_http.post(
            BONK_AVATAR_UPDATE_URL, json=load_bonk_fixture("avatar_update_success")
        )

    def test_success_sends_skin_to_active_slot(self, bonk_session_client, skin, bonk_accepts):
        response = bonk_session_client.post(_wear_url(skin.id))

        assert response.status_code == 200
        assert response.json() == {"ok": True, "slot": 2}
        sent = _sent_form(bonk_accepts.calls[0])
        assert sent == {
            "task": "updateavatar",
            "token": "test-bonk-token",
            "newavatarslot": "2",
            "newavatar": skin.skin_code,
        }

    def test_success_logs_event(self, bonk_session_client, skin, bonk_accepts):
        bonk_session_client.post(_wear_url(skin.id))

        assert UserEvent.objects.filter(event_type="skin_worn", skin=skin).exists()

    def test_success_slides_token_expiry_forward(self, bonk_session_client, skin, bonk_accepts):
        before = bonk_session_client.session["bonk_token_expires"]

        bonk_session_client.post(_wear_url(skin.id))

        assert bonk_session_client.session["bonk_token_expires"] > before

    def test_explicit_slot_wins_over_active_slot(self, bonk_session_client, skin, bonk_accepts):
        response = bonk_session_client.post(_wear_url(skin.id), {"slot": "5"})

        assert response.json()["slot"] == 5
        assert _sent_form(bonk_accepts.calls[0])["newavatarslot"] == "5"

    @pytest.mark.parametrize("bad_slot", ["0", "6", "abc", "-1"])
    def test_invalid_slot_falls_back_to_active_slot(
        self, bonk_session_client, skin, bonk_accepts, bad_slot
    ):
        response = bonk_session_client.post(_wear_url(skin.id), {"slot": bad_slot})

        assert response.json()["slot"] == 2

    def test_no_active_slot_defaults_to_3(self, bonk_session_client, skin, bonk_accepts):
        session = bonk_session_client.session
        del session["bonk_active_slot"]
        session.save()

        response = bonk_session_client.post(_wear_url(skin.id))

        assert response.json()["slot"] == 3

    def test_bonk_rejecting_token_asks_for_bonk_login(self, bonk_session_client, skin, mocked_http):
        mocked_http.post(
            BONK_AVATAR_UPDATE_URL, json=load_bonk_fixture("avatar_update_token_expired")
        )

        response = bonk_session_client.post(_wear_url(skin.id))

        assert response.status_code == 401
        assert response.json()["auth"] == "bonk"

    def test_bonk_network_error_asks_for_bonk_login(self, bonk_session_client, skin, mocked_http):
        mocked_http.post(BONK_AVATAR_UPDATE_URL, body=requests.Timeout("slow"))

        response = bonk_session_client.post(_wear_url(skin.id))

        assert response.status_code == 401
        assert response.json() == {"ok": False, "auth": "bonk", "error": "network_error"}

    def test_skin_without_code_is_400(self, bonk_session_client):
        skin = SkinFactory(skin_code=None)

        response = bonk_session_client.post(_wear_url(skin.id))

        assert response.status_code == 400
        assert response.json()["error"] == "skin_code_not_found"

    def test_missing_skin_is_404(self, bonk_session_client):
        response = bonk_session_client.post(_wear_url(999_999))

        assert response.status_code == 404


class TestWearSkinCode:
    URL = "/api/skins/wear-code/"

    def test_missing_code_is_400(self, bonk_session_client):
        response = bonk_session_client.post(self.URL)

        assert response.status_code == 400
        assert response.json()["error"] == "skin_code_not_found"

    def test_success(self, bonk_session_client, mocked_http):
        call = mocked_http.post(
            BONK_AVATAR_UPDATE_URL, json=load_bonk_fixture("avatar_update_success")
        )

        response = bonk_session_client.post(self.URL, {"skin_code": "RAWCODE", "slot": "1"})

        assert response.json() == {"ok": True, "slot": 1}
        assert _sent_form(call.calls[0])["newavatar"] == "RAWCODE"


class TestBonkLoginForWear:
    URL = "/api/bonk/login/"

    def test_anonymous_gets_bonkverse_401(self, client):
        response = client.post(self.URL, {"bonk_username": "a", "bonk_password": "b"})

        assert response.status_code == 401
        assert response.json()["auth"] == "bonkverse"

    def test_missing_params_is_400(self, logged_in_client):
        response = logged_in_client.post(self.URL, {"bonk_username": "a"})

        assert response.status_code == 400
        assert response.json()["error"] == "missing_params"

    def test_wrong_bonk_password_is_401_without_auth_tag(self, logged_in_client, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_wrong_password"))

        response = logged_in_client.post(self.URL, {"bonk_username": "a", "bonk_password": "b"})

        assert response.status_code == 401
        assert "auth" not in response.json()
        assert "bonk_token" not in logged_in_client.session

    def test_success_saves_token_and_active_slot(self, logged_in_client, mocked_http):
        call = mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        response = logged_in_client.post(
            self.URL, {"bonk_username": "TestPlayer", "bonk_password": "hunter2"}
        )

        assert response.json() == {"ok": True, "active_slot": 2}
        assert logged_in_client.session["bonk_token"] == "SCRUBBED-TEST-TOKEN-abc123"
        assert logged_in_client.session["bonk_active_slot"] == 2
        # Pinned divergence: this path sends task=legacy, the main login view does not.
        # Phase 2 unifies both behind integrations/bonk_api.py.
        assert _sent_form(call.calls[0])["task"] == "legacy"
