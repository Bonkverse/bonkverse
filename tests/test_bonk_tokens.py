"""The token broker (accounts/bonk_tokens.py, RFC-0003 Part 2).

Wear and every later bonk.io action get their token here: the stored session
token while it's good, else a fresh one from bonk.io's login_auto.php with the
remember-me token "Keep me connected for Wear" stored. These tests pin what's
sent to bonk.io, what's stored, and when only the password will do.
"""

import logging
import time
from datetime import timedelta
from urllib.parse import parse_qs

import pytest
import requests
from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone

from accounts import bonk_tokens
from accounts.models import BonkAccountLink
from integrations.bonk_api import LOGIN_SCRIPT, rate_limit_cooldowns
from tests.conftest import connect_bonk, load_bonk_fixture, make_bonk_token
from tests.factories import SkinFactory

pytestmark = pytest.mark.django_db

LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
LOGIN_AUTO_URL = "https://bonk2.io/scripts/login_auto.php"
CLEARAUTO_URL = "https://bonk2.io/scripts/login_clearauto.php"
AVATAR_UPDATE_URL = "https://bonk2.io/scripts/avatar_update.php"

REMEMBER = "r" * 77


def _sent_form(call) -> dict:
    return {k: v[0] for k, v in parse_qs(call.request.body).items()}


def _auto_answer(exp=None, **changes) -> dict:
    """login_auto.php's success answer, with a real-looking token."""
    answer = load_bonk_fixture("login_auto_success")
    answer["token"] = make_bonk_token(exp=exp or time.time() + 86400)
    answer.update(changes)
    return answer


@pytest.fixture
def expired_link(logged_in_client, user):
    """A link whose session token ran out, with a remember-me token."""
    return connect_bonk(
        logged_in_client,
        user,
        token=make_bonk_token(exp=time.time() - 60),
        expires_in=-60,
        remember_token=REMEMBER,
    )


class TestUsableToken:
    def test_a_fresh_token_is_used_without_asking_bonk(self, logged_in_client, user, mocked_http):
        link = connect_bonk(logged_in_client, user, token="fresh", remember_token=REMEMBER)

        assert bonk_tokens.usable_token(link) == "fresh"
        assert len(mocked_http.calls) == 0

    def test_a_token_about_to_expire_is_refreshed_first(self, logged_in_client, user, mocked_http):
        link = connect_bonk(
            logged_in_client, user, token="nearly", expires_in=60, remember_token=REMEMBER
        )
        mocked_http.post(LOGIN_AUTO_URL, json=_auto_answer())

        assert bonk_tokens.usable_token(link) != "nearly"
        assert len(mocked_http.calls) == 1

    def test_an_expired_token_is_swapped_with_the_remember_me_token(
        self, expired_link, mocked_http
    ):
        exp = time.time() + 86400
        call = mocked_http.post(LOGIN_AUTO_URL, json=_auto_answer(exp=exp, activeAvatarNumber=4))

        token = bonk_tokens.usable_token(expired_link)

        assert token == make_bonk_token(exp=exp)
        assert _sent_form(call.calls[0]) == {"rememberToken": REMEMBER}
        link = BonkAccountLink.objects.get(pk=expired_link.pk)
        assert link.bonk_token() == token
        assert link.token_expires_at > timezone.now() + timedelta(hours=23)
        assert link.active_slot == 4
        assert link.last_refreshed_at is not None
        # bonk.io doesn't rotate it: the same remember-me token is kept.
        assert link.remember_token() == REMEMBER
        assert link.remember_status == BonkAccountLink.REMEMBER_ACTIVE

    def test_a_refresh_also_stores_xp(self, expired_link, mocked_http):
        mocked_http.post(LOGIN_AUTO_URL, json=_auto_answer(xp=4321))

        bonk_tokens.usable_token(expired_link)

        expired_link.bonk_player.refresh_from_db()
        assert expired_link.bonk_player.xp == 4321

    def test_without_a_remember_me_token_only_the_password_will_do(
        self, logged_in_client, user, mocked_http
    ):
        link = connect_bonk(logged_in_client, user, token=None)

        with pytest.raises(bonk_tokens.ReconnectNeeded):
            bonk_tokens.usable_token(link)
        assert len(mocked_http.calls) == 0

    def test_a_revoked_remember_me_token_is_marked_and_deleted(self, expired_link, mocked_http):
        mocked_http.post(LOGIN_AUTO_URL, json=load_bonk_fixture("login_auto_not_found"))

        with pytest.raises(bonk_tokens.ReconnectNeeded):
            bonk_tokens.usable_token(expired_link)

        link = BonkAccountLink.objects.get(pk=expired_link.pk)
        assert link.remember_token_encrypted is None
        assert link.remember_status == BonkAccountLink.REMEMBER_REVOKED

    def test_nothing_is_sent_during_the_login_pause(self, expired_link, mocked_http):
        """A request during bonk.io's login block seems to restart it."""
        rate_limit_cooldowns.for_script(LOGIN_SCRIPT).start(600)

        with pytest.raises(bonk_tokens.Paused) as paused:
            bonk_tokens.usable_token(expired_link)

        assert 500 < paused.value.seconds <= 600
        assert len(mocked_http.calls) == 0
        link = BonkAccountLink.objects.get(pk=expired_link.pk)
        assert link.remember_status == BonkAccountLink.REMEMBER_ACTIVE

    def test_bonk_down_keeps_the_remember_me_token(self, expired_link, mocked_http):
        mocked_http.post(LOGIN_AUTO_URL, body=requests.ConnectionError("down"))

        with pytest.raises(bonk_tokens.Unavailable):
            bonk_tokens.usable_token(expired_link)

        link = BonkAccountLink.objects.get(pk=expired_link.pk)
        assert link.remember_token() == REMEMBER

    def test_force_refresh_asks_bonk_even_for_a_fresh_token(
        self, logged_in_client, user, mocked_http
    ):
        link = connect_bonk(logged_in_client, user, token="refused", remember_token=REMEMBER)
        mocked_http.post(LOGIN_AUTO_URL, json=_auto_answer())

        assert bonk_tokens.usable_token(link, force_refresh=True) != "refused"
        assert len(mocked_http.calls) == 1

    def test_a_refresh_in_progress_elsewhere_is_waited_for_not_repeated(
        self, expired_link, mocked_http, monkeypatch
    ):
        monkeypatch.setattr(bonk_tokens, "REFRESH_LOCK_SECONDS", 0.3)
        monkeypatch.setattr(bonk_tokens, "REFRESH_WAIT_STEP", 0.05)
        key = f"bonk_tokens:refresh:{expired_link.pk}"
        cache.add(key, 1, timeout=60)
        # The other request's refresh stored this (the in-memory link is stale).
        BonkAccountLink.objects.filter(pk=expired_link.pk).update(
            token_encrypted=BonkAccountLink.encrypt_token("from-the-other-request"),
            token_expires_at=timezone.now() + timedelta(hours=20),
        )
        try:
            assert bonk_tokens.usable_token(expired_link) == "from-the-other-request"
        finally:
            cache.delete(key)
        assert len(mocked_http.calls) == 0

    def test_tokens_never_reach_the_logs(self, expired_link, mocked_http, caplog):
        exp = time.time() + 86400
        mocked_http.post(LOGIN_AUTO_URL, json=_auto_answer(exp=exp))

        with caplog.at_level(logging.DEBUG):
            bonk_tokens.usable_token(expired_link)

        assert REMEMBER not in caplog.text
        assert make_bonk_token(exp=exp) not in caplog.text


class TestStoreLoginAndDisconnect:
    def test_unticking_keep_me_connected_revokes_the_old_remember_me_token(
        self, expired_link, mocked_http
    ):
        from integrations.bonk_api import get_client

        mocked_http.post(LOGIN_URL, json=load_bonk_fixture("login_success"))
        clear = mocked_http.post(CLEARAUTO_URL, json=load_bonk_fixture("login_clearauto_success"))
        result = get_client().login("TestPlayer", "pw")

        bonk_tokens.store_login(expired_link, result, remember=False)

        assert _sent_form(clear.calls[0]) == {"rememberToken": REMEMBER}
        link = BonkAccountLink.objects.get(pk=expired_link.pk)
        assert link.remember_token_encrypted is None
        assert link.remember_status == BonkAccountLink.REMEMBER_NONE
        assert link.bonk_token() == "SCRUBBED-TEST-TOKEN-abc123"

    def test_disconnect_revokes_on_bonk_and_forgets_both_tokens(self, expired_link, mocked_http):
        clear = mocked_http.post(CLEARAUTO_URL, json=load_bonk_fixture("login_clearauto_success"))

        bonk_tokens.disconnect(expired_link)

        assert len(clear.calls) == 1
        link = BonkAccountLink.objects.get(pk=expired_link.pk)
        assert link.token_encrypted is None
        assert link.remember_token_encrypted is None
        # Who owns which bonk.io account stays.
        assert link.active

    def test_disconnect_forgets_the_token_even_if_bonk_is_down(self, expired_link, mocked_http):
        mocked_http.post(CLEARAUTO_URL, body=requests.ConnectionError("down"))

        bonk_tokens.disconnect(expired_link)

        assert BonkAccountLink.objects.get(pk=expired_link.pk).remember_token_encrypted is None


class TestRememberMeOnTheLoginForm:
    def _login(self, client, mocked_http, **extra):
        answer = load_bonk_fixture("login_success")
        answer["rememberToken"] = REMEMBER
        call = mocked_http.post(LOGIN_URL, json=answer)
        client.post("/login/", {"username": "TestPlayer", "password": "hunter2", **extra})
        return call

    def test_ticked_keeps_the_remember_me_token(self, client, mocked_http):
        call = self._login(client, mocked_http, remember="on")

        assert _sent_form(call.calls[0])["remember"] == "true"
        link = BonkAccountLink.objects.get(bonk_player__bonk_id=1234567)
        assert link.remember_token() == REMEMBER
        assert link.remember_status == BonkAccountLink.REMEMBER_ACTIVE

    def test_unticked_keeps_none(self, client, mocked_http):
        call = self._login(client, mocked_http)

        assert _sent_form(call.calls[0])["remember"] == "false"
        link = BonkAccountLink.objects.get(bonk_player__bonk_id=1234567)
        assert link.remember_token_encrypted is None

    def test_the_box_starts_ticked(self, client):
        page = client.get("/login/").content.decode()

        assert "Keep me connected for Wear" in page
        assert 'name="remember"' in page and "checked" in page


class TestWearWithTheBroker:
    def test_an_expired_token_is_refreshed_and_the_wear_goes_through(
        self, logged_in_client, expired_link, mocked_http
    ):
        mocked_http.post(LOGIN_AUTO_URL, json=_auto_answer())
        wear = mocked_http.post(AVATAR_UPDATE_URL, json=load_bonk_fixture("avatar_update_success"))

        response = logged_in_client.post(f"/api/skins/{SkinFactory().id}/wear/")

        assert response.json()["ok"] is True
        assert len(wear.calls) == 1

    def test_a_refused_token_is_refreshed_once_and_retried(
        self, logged_in_client, user, mocked_http
    ):
        connect_bonk(logged_in_client, user, token="refused", remember_token=REMEMBER)
        mocked_http.post(LOGIN_AUTO_URL, json=_auto_answer())
        wear = mocked_http.post(AVATAR_UPDATE_URL, json={"r": "fail", "e": "token"})
        wear_ok = mocked_http.post(
            AVATAR_UPDATE_URL, json=load_bonk_fixture("avatar_update_success")
        )

        response = logged_in_client.post(f"/api/skins/{SkinFactory().id}/wear/")

        assert response.json()["ok"] is True
        assert len(wear.calls) + len(wear_ok.calls) == 2
        assert _sent_form(mocked_http.calls[-1])["token"] != "refused"

    def test_during_the_login_pause_wear_waits_without_asking_bonk(
        self, logged_in_client, expired_link, mocked_http
    ):
        rate_limit_cooldowns.for_script(LOGIN_SCRIPT).start(600)

        response = logged_in_client.post(f"/api/skins/{SkinFactory().id}/wear/")

        assert response.status_code == 503
        assert 500 < response.json()["retry_after"] <= 600
        assert len(mocked_http.calls) == 0

    def test_a_revoked_remember_me_token_opens_the_login_popup(
        self, logged_in_client, expired_link, mocked_http
    ):
        mocked_http.post(LOGIN_AUTO_URL, json=load_bonk_fixture("login_auto_not_found"))

        response = logged_in_client.post(f"/api/skins/{SkinFactory().id}/wear/")

        assert response.status_code == 401
        assert response.json() == {"ok": False, "auth": "bonk"}


class TestDisconnectView:
    URL = "/settings/bonk/disconnect/"

    def test_disconnects_the_active_link(self, logged_in_client, expired_link, mocked_http):
        mocked_http.post(CLEARAUTO_URL, json=load_bonk_fixture("login_clearauto_success"))

        response = logged_in_client.post(self.URL)

        assert response.status_code == 302
        link = BonkAccountLink.objects.get(pk=expired_link.pk)
        assert link.token_encrypted is None and link.remember_token_encrypted is None

    def test_get_changes_nothing(self, logged_in_client, expired_link):
        assert logged_in_client.get(self.URL).status_code == 405
        assert BonkAccountLink.objects.get(pk=expired_link.pk).remember_token() == REMEMBER

    def test_signed_out_is_sent_to_sign_in(self, client):
        response = client.post(self.URL)

        assert response.status_code == 302
        assert response["Location"].startswith("/login/")


class TestRevokeCommand:
    def test_dry_run_changes_nothing(self, expired_link, mocked_http):
        call_command("revoke_bonk_remember_tokens")

        assert len(mocked_http.calls) == 0
        assert BonkAccountLink.objects.get(pk=expired_link.pk).remember_token() == REMEMBER

    def test_run_revokes_every_remember_me_token(self, expired_link, mocked_http, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda _s: None)
        clear = mocked_http.post(CLEARAUTO_URL, json=load_bonk_fixture("login_clearauto_success"))

        call_command("revoke_bonk_remember_tokens", "--run")

        assert len(clear.calls) == 1
        link = BonkAccountLink.objects.get(pk=expired_link.pk)
        assert link.remember_token_encrypted is None
        # The session token stays; only remember-me tokens are revoked.
        assert link.token_encrypted is not None

    def test_run_waits_out_a_login_pause_instead_of_skipping_the_revoke(
        self, expired_link, mocked_http, monkeypatch
    ):
        """A revoke not sent would leave bonk.io's copy working."""
        rate_limit_cooldowns.for_script(LOGIN_SCRIPT).start(600)
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            rate_limit_cooldowns.reset()

        monkeypatch.setattr(time, "sleep", sleep)
        clear = mocked_http.post(CLEARAUTO_URL, json=load_bonk_fixture("login_clearauto_success"))

        call_command("revoke_bonk_remember_tokens", "--run")

        assert waits[0] == 60
        assert len(clear.calls) == 1
