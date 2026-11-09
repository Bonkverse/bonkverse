"""Characterization tests for wearing skins on bonk.io (skins/wear_skin.py).

They pin the JSON contract the frontend wear/login-modal flow depends on:
- 401 with auth="bonkverse" -> sign in to the site
- 401 with auth="bonk"      -> show the bonk.io login modal
- 401 without auth          -> the bonk.io credentials were wrong
- 502 error="network_error" -> bonk.io unreachable; no login modal
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

    def test_logs_never_name_the_player(self, bonk_session_client, user, skin, mocked_http, caplog):
        """Regression: every wear used to log the player's username. The
        temporary [wear-debug] lines are gone (#39 fixed the modal loop); a
        refusal is logged by the bonk.io client, by code only."""
        mocked_http.post(BONK_AVATAR_UPDATE_URL, json=load_bonk_fixture("avatar_update_too_big"))

        with caplog.at_level("DEBUG"):
            bonk_session_client.post(_wear_url(skin.id))

        assert "bonk_error=avatar_too_big" in caplog.text
        assert "[wear-debug]" not in caplog.text
        assert user.username not in caplog.text

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

        # The one refusal a fresh bonk.io login fixes, so the only one that
        # opens the login modal.
        assert response.status_code == 401
        assert response.json() == {"ok": False, "auth": "bonk", "error": "token_rejected"}

    def test_bonk_network_error_does_not_ask_for_bonk_login(
        self, bonk_session_client, skin, mocked_http
    ):
        """Regression: a timeout or outage used to answer 401 auth="bonk", which
        opens the bonk.io login modal even though the token was fine (one cause
        of the "login modal keeps reappearing" bug). Logging in again can't fix
        an outage, so it is a 502 without an auth tag."""
        mocked_http.post(BONK_AVATAR_UPDATE_URL, body=requests.Timeout("slow"))

        response = bonk_session_client.post(_wear_url(skin.id))

        assert response.status_code == 502
        assert response.json() == {
            "ok": False,
            "error": "network_error",
            "message": "bonk.io isn't responding. Try again in a minute.",
        }
        # The token is kept: nothing says it went bad.
        assert bonk_session_client.session["bonk_token"] == "test-bonk-token"

    @pytest.mark.parametrize(
        "code,status,message_start",
        [
            ("avatar_too_big", 422, "This skin is too big for bonk.io"),
            ("ratelimited", 503, "bonk.io is limiting requests"),
            ("something_new", 502, "bonk.io didn't accept this skin."),
        ],
    )
    def test_refusals_a_login_cannot_fix_do_not_open_the_modal(
        self, bonk_session_client, skin, mocked_http, code, status, message_start
    ):
        """Regression for the reappearing login modal (prod logs 2026-11-05):
        bonk.io said avatar_too_big, Bonkverse answered auth="bonk", the player
        logged in, the retry was refused again, and the modal came back. The
        same happened for every "ratelimited" refusal."""
        mocked_http.post(BONK_AVATAR_UPDATE_URL, json={"r": "fail", "e": code})

        response = bonk_session_client.post(_wear_url(skin.id))

        body = response.json()
        assert response.status_code == status
        assert "auth" not in body
        assert body["message"].startswith(message_start)
        assert bonk_session_client.session["bonk_token"] == "test-bonk-token"

    def test_cloudflare_page_from_bonk_does_not_ask_for_bonk_login(
        self, bonk_session_client, skin, mocked_http
    ):
        mocked_http.post(BONK_AVATAR_UPDATE_URL, body="<html>challenge</html>", status=403)

        response = bonk_session_client.post(_wear_url(skin.id))

        assert response.status_code == 502
        assert "auth" not in response.json()

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
        body = response.json()
        assert "auth" not in body
        assert body["error"] == "wrong_password"
        assert body["message"] == "Wrong password."
        assert "bonk_token" not in logged_in_client.session

    def test_bonk_down_is_a_network_error_not_bad_credentials(self, logged_in_client, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, body=requests.ConnectionError("down"))

        response = logged_in_client.post(self.URL, {"bonk_username": "a", "bonk_password": "b"})

        assert response.json()["error"] == "network_error"

    def test_success_saves_token_and_active_slot(self, logged_in_client, mocked_http):
        call = mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        response = logged_in_client.post(
            self.URL, {"bonk_username": "TestPlayer", "bonk_password": "hunter2"}
        )

        assert response.json() == {"ok": True, "active_slot": 2}
        assert logged_in_client.session["bonk_token"] == "SCRUBBED-TEST-TOKEN-abc123"
        assert logged_in_client.session["bonk_active_slot"] == 2
        # One request shape for every bonk.io login (integrations/bonk_api.py).
        assert _sent_form(call.calls[0]) == {
            "username": "TestPlayer",
            "password": "hunter2",
            "remember": "false",
        }


class TestWearSpamProtection:
    """Regression for 2026-11-09: one player's burst of Wear clicks got
    bonk.io to rate-limit the server's IP, pausing wearing for everyone."""

    def test_second_wear_while_one_is_in_flight_is_refused(
        self, bonk_session_client, skin, mocked_http, user
    ):
        from django.core.cache import cache

        cache.add(f"wear:inflight:{user.pk}", 1, timeout=15)  # a wear is pending

        response = bonk_session_client.post(_wear_url(skin.id))

        assert response.status_code == 429
        assert response.json()["error"] == "wear_in_progress"
        assert len(mocked_http.calls) == 0  # nothing reached bonk.io

    def test_lock_is_released_after_the_wear(self, bonk_session_client, skin, mocked_http, user):
        from django.core.cache import cache

        mocked_http.post(BONK_AVATAR_UPDATE_URL, json=load_bonk_fixture("avatar_update_success"))

        bonk_session_client.post(_wear_url(skin.id))

        assert cache.get(f"wear:inflight:{user.pk}") is None

    def test_burst_of_wears_is_cut_off_per_account(self, bonk_session_client, skin, mocked_http):
        mocked_http.post(BONK_AVATAR_UPDATE_URL, json=load_bonk_fixture("avatar_update_success"))

        statuses = [bonk_session_client.post(_wear_url(skin.id)).status_code for _ in range(5)]

        assert statuses[:2] == [200, 200]
        assert set(statuses[2:]) == {429}
        assert len(mocked_http.calls) == 2

    def test_one_accounts_spam_does_not_use_up_another_accounts_wears(
        self, bonk_session_client, skin, mocked_http, client, django_user_model
    ):
        mocked_http.post(BONK_AVATAR_UPDATE_URL, json=load_bonk_fixture("avatar_update_success"))
        for _ in range(5):
            bonk_session_client.post(_wear_url(skin.id))

        other = django_user_model.objects.create_user(username="other-player", password="pw")
        from django.test import Client

        other_client = Client()
        other_client.force_login(other)
        session = other_client.session
        session["bonk_token"] = "other-token"
        session["bonk_token_expires"] = time.time() + 3600
        session.save()

        assert other_client.post(_wear_url(skin.id)).status_code == 200

    def test_rate_limited_answer_says_how_long_to_wait(
        self, bonk_session_client, skin, mocked_http
    ):
        mocked_http.post(BONK_AVATAR_UPDATE_URL, json={"r": "fail", "e": "ratelimited"})

        response = bonk_session_client.post(_wear_url(skin.id))

        assert response.status_code == 503
        assert 0 < response.json()["retry_after"] <= 120
        assert response["Retry-After"] == str(response.json()["retry_after"])
