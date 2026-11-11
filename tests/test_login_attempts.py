"""Tests for Bonkverse's own limit on wrong bonk.io passwords (accounts/login_attempts.py).

Regression for 2026-11-09 and 11-10: one player's wrong passwords set off
bonk.io's "ratelimited", which paused logins for every Bonkverse user, twice
for over an hour. These pin that the player who keeps getting it wrong is held
here, before bonk.io sees the try, and that nobody else is.
"""

import logging

import pytest
import requests

from integrations.bonk_api import rate_limit_cooldowns
from accounts import login_attempts
from accounts.login_attempts import (
    ACCOUNT_FAILURES_ALLOWED,
    CLIENT_FAILURES_ALLOWED,
    HOLD_SECONDS,
    TOO_MANY_ATTEMPTS,
    TRIGGER_HOLD_SECONDS,
)
from tests.conftest import load_bonk_fixture

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
LOGIN_URL = "/login/"
WEAR_LOGIN_URL = "/api/bonk/login/"
HELD_MESSAGE_START = "Bonk.io login failed: Too many wrong passwords. Wait"

pytestmark = pytest.mark.django_db


def _post_login(client, username="TestPlayer", ip="203.0.113.7"):
    return client.post(LOGIN_URL, {"username": username, "password": "wrong"}, REMOTE_ADDR=ip)


def _bonk_says(mocked_http, fixture_or_body):
    body = (
        load_bonk_fixture(fixture_or_body) if isinstance(fixture_or_body, str) else fixture_or_body
    )
    return mocked_http.post(BONK_LOGIN_URL, json=body)


def _messages(response):
    return [str(m) for m in response.context["messages"]]


class TestPerAccount:
    def test_holds_the_account_after_its_wrong_passwords(self, client, mocked_http):
        bonk = _bonk_says(mocked_http, "login_wrong_password")
        for _ in range(ACCOUNT_FAILURES_ALLOWED):
            _post_login(client)

        response = _post_login(client)

        assert bonk.call_count == ACCOUNT_FAILURES_ALLOWED  # the held try never left
        assert _messages(response)[0].startswith(HELD_MESSAGE_START)
        assert response.context["retry_after"] == HOLD_SECONDS
        assert b'id="login-submit" disabled' in response.content

    def test_the_last_wrong_try_says_it_was_the_last(self, client, mocked_http):
        _bonk_says(mocked_http, "login_wrong_password")
        for _ in range(ACCOUNT_FAILURES_ALLOWED - 1):
            first = _post_login(client)

        last = _post_login(client)

        assert _messages(first) == ["Bonk.io login failed: Wrong password."]
        assert first.context["retry_after"] is None
        assert _messages(last) == [
            "Bonk.io login failed: Wrong password. That was your last try for now: wait "
            "about 15 minutes before trying again, so bonk.io doesn't block logins for "
            "everyone on Bonkverse."
        ]
        assert last.context["retry_after"] == HOLD_SECONDS

    def test_counts_the_name_case_insensitively(self, client, mocked_http):
        """bonk.io names are unique ignoring case, so these are one account."""
        bonk = _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client, username="TestPlayer")
        _post_login(client, username="testplayer ")

        _post_login(client, username="TESTPLAYER")

        assert bonk.call_count == 2

    def test_a_strangers_wrong_passwords_do_not_hold_the_player(self, client, mocked_http):
        """The count is per name AND visitor, so typing someone's name with
        wrong passwords holds only the person typing."""
        _bonk_says(mocked_http, "login_wrong_password")
        for _ in range(ACCOUNT_FAILURES_ALLOWED + 1):
            stranger = _post_login(client, username="TestPlayer", ip="198.51.100.66")
        assert _messages(stranger)[0].startswith(HELD_MESSAGE_START)
        bonk = mocked_http.replace("POST", BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        response = _post_login(client, username="TestPlayer", ip="203.0.113.7")

        assert bonk.call_count == 1
        assert response.status_code == 302

    def test_unknown_usernames_count_per_visitor_not_per_account(self, client, mocked_http):
        """bonk.io didn't limit 20 unknown usernames in a row (2026-11-10)."""
        bonk = _bonk_says(mocked_http, "login_unknown_username")
        for _ in range(ACCOUNT_FAILURES_ALLOWED):
            response = _post_login(client, username="Typo")

        assert bonk.call_count == ACCOUNT_FAILURES_ALLOWED
        assert response.context["retry_after"] is None  # not held after 2

    def test_other_accounts_still_reach_bonk(self, client, mocked_http):
        _bonk_says(mocked_http, "login_wrong_password")
        for _ in range(ACCOUNT_FAILURES_ALLOWED):
            _post_login(client, username="Typo Person")
        mocked_http.replace("POST", BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        response = _post_login(client, username="TestPlayer", ip="198.51.100.9")

        assert response.status_code == 302
        assert "_auth_user_id" in client.session

    def test_a_success_starts_the_count_over(self, client, mocked_http):
        _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client)
        mocked_http.replace("POST", BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))
        _post_login(client)
        client.logout()
        bonk = mocked_http.replace(
            "POST", BONK_LOGIN_URL, json=load_bonk_fixture("login_wrong_password")
        )

        for _ in range(ACCOUNT_FAILURES_ALLOWED):
            response = _post_login(client)

        assert bonk.call_count == ACCOUNT_FAILURES_ALLOWED
        assert response.context["retry_after"] == HOLD_SECONDS

    @pytest.mark.parametrize(
        "bonk_reply",
        [
            {"body": requests.ConnectionError("down")},
            {"json": {"r": "fail", "e": "ratelimited"}},
            {"json": {"r": "fail", "e": "something_new"}},
        ],
        ids=["network_error", "rate_limited", "unknown_refusal"],
    )
    def test_only_wrong_logins_count(self, client, mocked_http, bonk_reply):
        """Failures that aren't the player's fault don't use up their tries."""
        mocked_http.post(BONK_LOGIN_URL, **bonk_reply)
        for _ in range(ACCOUNT_FAILURES_ALLOWED + 1):
            rate_limit_cooldowns.reset()
            response = _post_login(client)

        assert not any(m.startswith(HELD_MESSAGE_START) for m in _messages(response))


class TestPerVisitor:
    def test_holds_a_visitor_cycling_through_names(self, client, mocked_http):
        bonk = _bonk_says(mocked_http, "login_unknown_username")
        for n in range(CLIENT_FAILURES_ALLOWED):
            _post_login(client, username=f"guess{n}")

        response = _post_login(client, username="fresh name")

        assert bonk.call_count == CLIENT_FAILURES_ALLOWED
        assert _messages(response)[0].startswith(HELD_MESSAGE_START)

    def test_other_visitors_are_not_held(self, client, mocked_http):
        bonk = _bonk_says(mocked_http, "login_unknown_username")
        for n in range(CLIENT_FAILURES_ALLOWED):
            _post_login(client, username=f"guess{n}")

        _post_login(client, username="fresh name", ip="198.51.100.20")

        assert bonk.call_count == CLIENT_FAILURES_ALLOWED + 1


class TestWhenBonkRateLimits:
    def test_holds_the_account_that_set_it_off_past_the_site_wide_pause(self, client, mocked_http):
        _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client)
        mocked_http.replace("POST", BONK_LOGIN_URL, json={"r": "fail", "e": "ratelimited"})
        _post_login(client)
        # bonk.io's pause ends; the next login bonk.io sees must not be theirs.
        rate_limit_cooldowns.reset()
        bonk = mocked_http.replace(
            "POST", BONK_LOGIN_URL, json=load_bonk_fixture("login_wrong_password")
        )

        response = _post_login(client)

        assert bonk.call_count == 0
        assert response.context["retry_after"] > HOLD_SECONDS
        assert response.context["retry_after"] <= TRIGGER_HOLD_SECONDS

    def test_does_not_hold_someone_with_no_wrong_passwords(self, client, mocked_http):
        _bonk_says(mocked_http, {"r": "fail", "e": "ratelimited"})
        _post_login(client)
        rate_limit_cooldowns.reset()
        bonk = mocked_http.replace("POST", BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        response = _post_login(client)

        assert bonk.call_count == 1
        assert response.status_code == 302

    def test_the_site_wide_pause_still_says_bonk_is_limiting(self, client, mocked_http):
        _bonk_says(mocked_http, {"r": "fail", "e": "ratelimited"})

        response = _post_login(client)

        assert _messages(response) == [
            "Bonk.io login failed: bonk.io is limiting logins from Bonkverse right now. "
            "Try again in about 17 minutes."
        ]
        assert response.context["retry_after"] == 1020


class TestLogs:
    def test_tags_each_attempt_without_the_name_or_ip(self, client, mocked_http, caplog):
        _bonk_says(mocked_http, "login_wrong_password")

        with caplog.at_level(logging.INFO, logger="skins.login"):
            _post_login(client, username="Secret Name", ip="203.0.113.99")

        line = next(
            r.getMessage() for r in caplog.records if "bonk login response" in r.getMessage()
        )
        assert "account=" in line and "client=" in line and "via=page" in line
        assert "Secret Name" not in line and "secret name" not in line
        assert "203.0.113.99" not in line

    def test_same_account_gets_the_same_tag(self, client, mocked_http, caplog):
        _bonk_says(mocked_http, "login_wrong_password")

        with caplog.at_level(logging.INFO, logger="skins.login"):
            _post_login(client, username="Same Person")
            _post_login(client, username="same person", ip="198.51.100.3")

        tags = [
            r.getMessage().split("account=")[1].split(" ")[0]
            for r in caplog.records
            if "bonk login response" in r.getMessage()
        ]
        assert len(tags) == 2 and tags[0] == tags[1]

    def test_held_attempts_are_logged(self, client, mocked_http, caplog):
        _bonk_says(mocked_http, "login_wrong_password")
        for _ in range(ACCOUNT_FAILURES_ALLOWED):
            _post_login(client)

        with caplog.at_level(logging.INFO, logger="skins.login"):
            _post_login(client)

        assert any("bonk login held" in r.getMessage() for r in caplog.records)


class TestWearLogin:
    def test_the_in_page_login_is_held_too(self, logged_in_client, mocked_http):
        bonk = _bonk_says(mocked_http, "login_wrong_password")
        form = {"bonk_username": "TestPlayer", "bonk_password": "wrong"}
        for _ in range(ACCOUNT_FAILURES_ALLOWED):
            logged_in_client.post(WEAR_LOGIN_URL, form)

        response = logged_in_client.post(WEAR_LOGIN_URL, form)

        assert bonk.call_count == ACCOUNT_FAILURES_ALLOWED
        assert response.status_code == 401
        body = response.json()
        assert "auth" not in body  # a credential problem, not an expired session
        assert body["error"] == TOO_MANY_ATTEMPTS
        assert body["retry_after"] == HOLD_SECONDS
        assert body["message"].startswith("Too many wrong passwords.")

    def test_page_and_wear_share_one_count(self, client, logged_in_client, mocked_http):
        bonk = _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client, username="TestPlayer", ip="198.51.100.4")
        logged_in_client.post(
            WEAR_LOGIN_URL,
            {"bonk_username": "TestPlayer", "bonk_password": "wrong"},
            REMOTE_ADDR="198.51.100.4",
        )

        response = _post_login(client, username="TestPlayer", ip="198.51.100.4")

        assert bonk.call_count == 2
        assert response.context["retry_after"] == HOLD_SECONDS


def test_a_broken_cache_never_stops_a_login(client, mocked_http, monkeypatch):
    """The limit is a courtesy to bonk.io; Redis being down must not lock players out."""

    class BrokenCache:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise ConnectionError("redis down")

            return fail

    monkeypatch.setattr(login_attempts, "cache", BrokenCache())
    bonk = _bonk_says(mocked_http, "login_wrong_password")

    for _ in range(ACCOUNT_FAILURES_ALLOWED + 2):
        _post_login(client)

    assert bonk.call_count == ACCOUNT_FAILURES_ALLOWED + 2
