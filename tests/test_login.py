"""Tests for the bonk.io-backed login flow (skins/login.py).

The bonk.io call goes through integrations/bonk_api.py (tested on its own in
test_bonk_api.py); these pin what users see. bonk.io is always faked with
`responses`; see tests/fixtures/bonk/.
"""

import logging

import pytest
import requests
from django.urls import reverse

from skins.models import BonkAccountLink, BonkPlayer, BonkUser, Skin, UserEvent
from tests.conftest import load_bonk_fixture
from tests.factories import UserFactory

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
LOGIN_URL = "/login/"

pytestmark = pytest.mark.django_db


def _post_login(client, username="TestPlayer", password="hunter2", **extra):
    return client.post(LOGIN_URL, {"username": username, "password": password, **extra})


class TestSuccessfulLogin:
    @pytest.fixture(autouse=True)
    def _bonk_accepts(self, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

    def test_redirects_to_profile(self, client):
        response = _post_login(client)

        assert response.status_code == 302
        assert response.url == reverse("my_profile")

    def test_logs_user_in_and_creates_site_account(self, client):
        _post_login(client)

        user = BonkUser.objects.get(username="TestPlayer")
        assert client.session["_auth_user_id"] == str(user.pk)
        assert UserEvent.objects.filter(user=user, event_type="user_logged_in").exists()

    def test_stores_bonk_session_from_response(self, client):
        _post_login(client)

        session = client.session
        assert session["bonk_token"] == "SCRUBBED-TEST-TOKEN-abc123"
        assert session["bonk_username"] == "TestPlayer"
        assert session["bonk_user_id"] == 1234567
        assert session["bonk_active_slot"] == 2
        assert session["bonk_token_expires"] > 0

    def test_never_stores_password_in_session(self, client):
        _post_login(client, password="hunter2")

        assert "hunter2" not in str(dict(client.session.items()))

    def test_links_site_account_to_bonk_player(self, client):
        _post_login(client)

        player = BonkPlayer.objects.get(bonk_id=1234567)
        assert player.username == "TestPlayer"
        link = BonkAccountLink.objects.get(user__username="TestPlayer", bonk_player=player)
        assert link.active is True
        # The token is stored signed, never raw.
        assert "SCRUBBED-TEST-TOKEN-abc123" not in link.token_encrypted

    def test_uses_username_returned_by_bonk_not_typed_one(self, client, mocked_http):
        # BONK: bonk.io returns the canonical username; it can differ from what was typed.
        mocked_http.replace(
            "POST",
            BONK_LOGIN_URL,
            json={**load_bonk_fixture("login_success"), "username": "Canonical Name"},
        )

        _post_login(client, username="canonical name")

        assert BonkUser.objects.filter(username="Canonical Name").exists()
        assert not BonkUser.objects.filter(username="canonical name").exists()

    def test_logs_outcome_but_no_player_details(self, client, caplog):
        """Regression: the full bonk.io response (username, id, XP, avatar) was
        logged on every login. Only the outcome belongs in the logs."""
        with caplog.at_level(logging.DEBUG, logger="skins.login"):
            _post_login(client)

        [line] = [r.getMessage() for r in caplog.records if "bonk login response" in r.getMessage()]
        assert "result=success" in line
        for detail in ("TestPlayer", "1234567", "4200"):
            assert detail not in line, detail
        assert "SCRUBBED-TEST-TOKEN-abc123" not in caplog.text

    def test_new_site_account_has_no_usable_password(self, client):
        _post_login(client)

        assert not BonkUser.objects.get(username="TestPlayer").has_usable_password()

    def test_flash_friends_from_login_response_are_stored(self, client, mocked_http):
        mocked_http.replace(
            "POST",
            BONK_LOGIN_URL,
            json={**load_bonk_fixture("login_success"), "legacyFriends": "Old Pal# Spaced"},
        )

        _post_login(client)

        user = BonkUser.objects.get(username="TestPlayer")
        names = set(user.flash_friendships.values_list("flash_friend__name", flat=True))
        assert names == {"Old Pal", " Spaced"}

    def test_follows_safe_next_url(self, client):
        response = _post_login(client, next="/categories/")

        assert response.url == "/categories/"

    def test_ignores_offsite_next_url(self, client):
        response = _post_login(client, next="https://evil.example.com/")

        assert response.url == reverse("my_profile")


class TestSiteAccountMatching:
    """bonk.io names are unique case-insensitively (docs/bonk/accounts.md), so
    a login finds the existing site account whatever its stored capitalization."""

    @pytest.fixture(autouse=True)
    def _bonk_accepts(self, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

    def test_reuses_account_stored_with_other_capitalization(self, client):
        existing = UserFactory(username="testplayer")
        Skin.objects.create(name="Mine", creator="testplayer", skin_code="X")

        _post_login(client)

        assert client.session["_auth_user_id"] == str(existing.pk)
        assert BonkUser.objects.count() == 1
        # The stored spelling is kept so rows that name it still match.
        existing.refresh_from_db()
        assert existing.username == "testplayer"

    def test_exact_spelling_wins_when_old_data_has_both(self, client):
        UserFactory(username="testplayer")
        exact = UserFactory(username="TestPlayer")

        _post_login(client)

        assert client.session["_auth_user_id"] == str(exact.pk)

    def test_spaces_still_distinguish_accounts(self, client):
        UserFactory(username=" TestPlayer")

        _post_login(client)

        assert BonkUser.objects.filter(username="TestPlayer").exists()
        assert BonkUser.objects.count() == 2


class TestFailedLogin:
    def test_wrong_password_rerenders_form_without_logging_in(self, client, mocked_http):
        # BONK: login_legacy.php answers HTTP 200 even when the login fails.
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_wrong_password"))

        response = _post_login(client)

        assert response.status_code == 200
        assert "_auth_user_id" not in client.session
        assert "bonk_token" not in client.session
        assert not BonkUser.objects.exists()

    @pytest.mark.parametrize(
        "fixture,message",
        [
            ("login_wrong_password", "Bonk.io login failed: Wrong password."),
            (
                "login_unknown_username",
                "Bonk.io login failed: No bonk.io account has that username.",
            ),
        ],
    )
    def test_says_what_was_wrong(self, client, mocked_http, fixture, message):
        """Regression: bonk.io's code is in "e", but the view read "error", so
        every failure said "Bonk.io login failed: fail"."""
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture(fixture))

        response = _post_login(client)

        assert [str(m) for m in response.context["messages"]] == [message]

    def test_rate_limited_says_so(self, client, mocked_http):
        """bonk.io rate-limited Bonkverse for hours on 2026-11-05; players saw
        "bonk.io didn't accept that login", which sounds like their fault."""
        mocked_http.post(BONK_LOGIN_URL, json={"r": "fail", "e": "ratelimited"})

        response = _post_login(client)

        assert [str(m) for m in response.context["messages"]] == [
            "Bonk.io login failed: bonk.io is limiting logins from Bonkverse right now. "
            "Try again in about 17 minutes."
        ]

    def test_rate_limited_page_holds_the_login_button(self, client, mocked_http):
        """Regression for 2026-11-09: one player resubmitted six times in a
        minute into bonk.io's pause."""
        mocked_http.post(BONK_LOGIN_URL, json={"r": "fail", "e": "ratelimited"})

        response = _post_login(client)

        assert response.context["retry_after"] == 1020
        assert b'id="login-submit" disabled data-retry-after="1020"' in response.content

    def test_wrong_password_page_does_not_hold_the_button(self, client, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, json={"r": "fail", "e": "password"})

        response = _post_login(client)

        assert response.context["retry_after"] is None
        assert b'id="login-submit">Log in</button>' in response.content

    def test_network_error_shows_message_instead_of_500(self, client, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, body=requests.ConnectionError("bonk.io down"))

        response = _post_login(client)

        assert response.status_code == 200
        assert "_auth_user_id" not in client.session
        messages = [str(m) for m in response.context["messages"]]
        assert any("Network error" in m for m in messages)

    def test_non_json_response_is_handled(self, client, mocked_http):
        mocked_http.post(BONK_LOGIN_URL, body="<html>Cloudflare challenge</html>", status=503)

        response = _post_login(client)

        assert response.status_code == 200
        assert "_auth_user_id" not in client.session


def test_login_page_renders(client):
    response = client.get(LOGIN_URL)

    assert response.status_code == 200


def test_logout_clears_bonk_session(bonk_session_client):
    response = bonk_session_client.post("/logout/")

    assert response.status_code == 302
    assert "bonk_token" not in bonk_session_client.session
    assert "_auth_user_id" not in bonk_session_client.session


def test_logout_is_post_only(bonk_session_client):
    """A GET (a link or an <img> on another site) doesn't sign anyone out."""
    response = bonk_session_client.get("/logout/")

    assert response.status_code == 405
    assert "_auth_user_id" in bonk_session_client.session


@pytest.mark.django_db
def test_login_required_pages_send_visitors_to_the_login_page(client):
    """Regression: LOGIN_URL was Django's default /accounts/login/, a 404 here,
    so signed-out visitors to e.g. profile settings hit a dead page."""
    response = client.get(reverse("profile_settings"))
    assert response.status_code == 302
    assert response["Location"] == "/login/?next=/settings/profile/"
