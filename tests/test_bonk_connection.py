"""RFC-0003 phase 2: stop wasting what bonk.io gives us.

- The account link stores when its token really expires (its `exp`, about a
  day after login) and the account's active slot, and never hands out an
  expired token, so the worker doesn't spend a bonk.io call to find out.
- The in-page login on wear refreshes the link too.
- A Bonkverse sign-in lasts 90 days from the last visit, so getting back in
  rarely costs a bonk.io password.
- Settings show how long the bonk.io connection lasts.
"""

import time
from datetime import timedelta

import pytest
from django.utils import timezone

from accounts import sessions
from accounts.models import BonkAccountLink
from core import token_crypto
from core.bonk.session import EXPIRY_MARGIN_SECONDS
from players.models import BonkPlayer
from tests.conftest import load_bonk_fixture, make_bonk_token
from tests.factories import UserFactory

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
WEAR_LOGIN_URL = "/api/bonk/login/"
SETTINGS_URL = "/settings/profile/"

pytestmark = pytest.mark.django_db


def _login_answer(exp, slot=2):
    return {
        **load_bonk_fixture("login_success"),
        "token": make_bonk_token(exp=exp),
        "activeAvatarNumber": slot,
    }


class TestLinkAtLogin:
    @pytest.fixture(autouse=True)
    def _no_friend_sync(self, settings):
        settings.SYNC_FRIENDS_ON_LOGIN = False

    def test_stores_the_tokens_own_expiry_and_the_active_slot(self, client, mocked_http):
        exp = time.time() + 86400
        mocked_http.post(BONK_LOGIN_URL, json=_login_answer(exp, slot=4))

        client.post("/login/", {"username": "TestPlayer", "password": "x"})

        link = BonkAccountLink.objects.get(bonk_player__bonk_id=1234567)
        assert abs(link.token_expires_at.timestamp() - (exp - EXPIRY_MARGIN_SECONDS)) < 1
        assert link.active_slot == 4

    def test_a_token_without_readable_exp_has_no_stored_expiry(self, client, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        client.post("/login/", {"username": "TestPlayer", "password": "x"})

        link = BonkAccountLink.objects.get(bonk_player__bonk_id=1234567)
        assert link.token_expires_at is None
        assert link.bonk_token() == "SCRUBBED-TEST-TOKEN-abc123"


class TestExpiredLinkToken:
    def _link(self, token, expires_at=None):
        player = BonkPlayer.objects.create(bonk_id=42, username="Someone")
        return BonkAccountLink.objects.create(
            user=UserFactory(),
            bonk_player=player,
            token_encrypted=BonkAccountLink.encrypt_token(token),
            token_expires_at=expires_at,
        )

    def test_past_its_stored_expiry_reads_as_none(self):
        link = self._link("tok", expires_at=timezone.now() - timedelta(minutes=1))
        assert link.bonk_token() is None

    def test_past_its_own_exp_reads_as_none_for_links_saved_before(self):
        link = self._link(make_bonk_token(exp=time.time() - 10))
        assert link.bonk_token() is None

    def test_a_live_token_reads(self):
        token = make_bonk_token(exp=time.time() + 3600)
        link = self._link(token, expires_at=timezone.now() + timedelta(minutes=50))
        assert link.bonk_token() == token

    def test_the_worker_does_not_call_bonk_with_it(self, mocked_http):
        from players.friends_sync import NO_TOKEN, sync_friends_for_link

        link = self._link("tok", expires_at=timezone.now() - timedelta(minutes=1))

        assert sync_friends_for_link(link).error == NO_TOKEN
        assert len(mocked_http.calls) == 0


class TestWearLoginRefreshesTheLink:
    def test_updates_the_users_own_link(self, logged_in_client, user, mocked_http):
        player = BonkPlayer.objects.create(bonk_id=1234567, username="TestPlayer")
        link = BonkAccountLink.objects.create(
            user=user, bonk_player=player, token_encrypted=BonkAccountLink.encrypt_token("old")
        )
        exp = time.time() + 86400
        mocked_http.post(BONK_LOGIN_URL, json=_login_answer(exp, slot=5))

        response = logged_in_client.post(
            WEAR_LOGIN_URL, {"bonk_username": "TestPlayer", "bonk_password": "pw"}
        )

        assert response.status_code == 200
        link.refresh_from_db()
        assert link.bonk_token() == make_bonk_token(exp=exp)
        assert link.active_slot == 5
        assert link.token_expires_at is not None

    def test_never_creates_a_link(self, logged_in_client, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, json=_login_answer(time.time() + 86400))

        logged_in_client.post(
            WEAR_LOGIN_URL, {"bonk_username": "TestPlayer", "bonk_password": "pw"}
        )

        assert not BonkAccountLink.objects.exists()


class TestNinetyDaySignIn:
    def test_sessions_last_ninety_days(self, settings):
        assert settings.SESSION_COOKIE_AGE == 90 * 24 * 60 * 60

    def test_logging_in_counts_as_the_days_renewal(self, logged_in_client):
        """The login saved the session already; the first page mustn't write again."""
        renewed = logged_in_client.session.get(sessions.RENEWED_AT)

        response = logged_in_client.get(SETTINGS_URL)

        assert isinstance(renewed, float)
        assert logged_in_client.session[sessions.RENEWED_AT] == renewed
        assert "sessionid" not in response.cookies

    def test_a_visit_a_day_later_renews_the_session(self, logged_in_client):
        session = logged_in_client.session
        session[sessions.RENEWED_AT] = time.time() - sessions.RENEW_EVERY_SECONDS - 1
        session.save()

        response = logged_in_client.get(SETTINGS_URL)

        assert time.time() - logged_in_client.session[sessions.RENEWED_AT] < 60
        cookie = response.cookies.get("sessionid")
        assert cookie is not None and int(cookie["max-age"]) == 90 * 24 * 60 * 60

    def test_renews_at_most_once_a_day(self, logged_in_client):
        session = logged_in_client.session
        session[sessions.RENEWED_AT] = time.time() - sessions.RENEW_EVERY_SECONDS - 1
        session.save()
        logged_in_client.get(SETTINGS_URL)
        first = logged_in_client.session[sessions.RENEWED_AT]

        response = logged_in_client.get(SETTINGS_URL)

        assert logged_in_client.session[sessions.RENEWED_AT] == first
        assert "sessionid" not in response.cookies

    def test_signed_out_visitors_get_no_session(self, client):
        response = client.get("/")

        assert "sessionid" not in response.cookies


class TestSettingsShowsTheConnection:
    def test_connected_says_until_when(self, logged_in_client):
        session = logged_in_client.session
        exp = time.time() + 6 * 3600
        session["bonk_token"] = token_crypto.encrypt(make_bonk_token(exp=exp))
        session["bonk_token_expires"] = exp - EXPIRY_MARGIN_SECONDS
        session["bonk_username"] = "TestPlayer"
        session.save()

        page = logged_in_client.get(SETTINGS_URL).content.decode()

        assert "bonk.io connection" in page
        assert "Connected as <strong>TestPlayer</strong>" in page
        assert "data-local-time" in page
        assert "Reconnect now" in page

    def test_not_connected_says_so(self, logged_in_client):
        page = logged_in_client.get(SETTINGS_URL).content.decode()

        assert "Not connected." in page
        assert "Connect bonk.io" in page
        assert "next=/settings/profile/" in page
