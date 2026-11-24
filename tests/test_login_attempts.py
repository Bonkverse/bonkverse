"""Tests for Bonkverse's guards on bonk.io password logins (accounts/login_attempts.py).

Every login leaves from the server's one IP, and bonk.io blocks that IP for
everyone after about 3 wrong passwords or a fast burst of logins. Regressions:
- 2026-11-09 and 11-10: one player's wrong passwords set off bonk.io's
  "ratelimited", pausing logins for everyone, twice for over an hour.
- 2026-11-10 (RFC-0003 Part 1): 5 site-wide pauses in 6.5 hours. Three came
  after exactly 3 wrong passwords from different visitors (one a double
  submit 0.86 s apart); one came from a bot logging in 10 alts 17 times in
  100 s from rotating IPs, with no wrong password; and the trigger hold
  punished whoever happened to be next instead of who spent the budget.
"""

import logging

import pytest
import requests

from accounts import login_attempts
from accounts.login_attempts import (
    AFTER_PAUSE_SECONDS,
    BUSY,
    FAILURE_WINDOW,
    HOLD_SECONDS,
    IN_PROGRESS,
    SITE_WAIT,
    TOO_MANY_ATTEMPTS,
)
from core.pseudonym import pseudonym
from integrations.bonk_api import LOGIN_RATE_LIMIT_PAUSE, rate_limit_cooldowns
from tests.conftest import load_bonk_fixture

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
LOGIN_URL = "/login/"
WEAR_LOGIN_URL = "/api/bonk/login/"
HELD_MESSAGE_START = "Bonk.io login failed: Too many wrong passwords. Wait"
# A minute boundary, so the one-minute caps' buckets are predictable.
START = 1_800_000_000.0

pytestmark = pytest.mark.django_db


class Clock:
    def __init__(self):
        self.now = START + 5

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """The guards' clock, pinned so a test never straddles a minute bucket."""
    fake = Clock()
    monkeypatch.setattr(login_attempts, "_now", fake)
    return fake


@pytest.fixture
def limits(settings):
    """Change one guard for a test: `limits(site_per_minute=0)`. 0 turns a
    site-wide guard or cap off."""

    def set_limits(**changes):
        settings.BONK_LOGIN_LIMITS = {**settings.BONK_LOGIN_LIMITS, **changes}

    return set_limits


@pytest.fixture
def only_personal_limits(limits):
    """Just the per-account and per-visitor allowances: the site-wide guards
    off, for tests about one person's tries."""
    limits(site_per_minute=0, account_per_minute=0, site_wrong_passwords=0)


def _post_login(client, username="TestPlayer", ip="203.0.113.7"):
    return client.post(LOGIN_URL, {"username": username, "password": "wrong"}, REMOTE_ADDR=ip)


def _bonk_says(mocked_http, fixture_or_body):
    body = (
        load_bonk_fixture(fixture_or_body) if isinstance(fixture_or_body, str) else fixture_or_body
    )
    return mocked_http.post(BONK_LOGIN_URL, json=body)


def _bonk_now_says(mocked_http, fixture_or_body):
    body = (
        load_bonk_fixture(fixture_or_body) if isinstance(fixture_or_body, str) else fixture_or_body
    )
    return mocked_http.replace("POST", BONK_LOGIN_URL, json=body)


def _messages(response):
    return [str(m) for m in response.context["messages"]]


@pytest.mark.usefixtures("only_personal_limits")
class TestPerAccount:
    def test_holds_the_account_after_its_wrong_passwords(self, client, mocked_http, settings):
        allowed = settings.BONK_LOGIN_LIMITS["account_wrong_passwords"]
        bonk = _bonk_says(mocked_http, "login_wrong_password")
        for _ in range(allowed):
            _post_login(client)

        response = _post_login(client)

        assert bonk.call_count == allowed  # the held try never left
        assert _messages(response)[0].startswith(HELD_MESSAGE_START)
        assert response.context["retry_after"] == HOLD_SECONDS
        assert b'id="login-submit" disabled' in response.content
        assert b"button stays off" not in response.content  # template comment stays hidden

    def test_the_last_wrong_try_says_it_was_the_last(self, client, mocked_http):
        _bonk_says(mocked_http, "login_wrong_password")
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

    def test_counts_the_name_case_insensitively(self, client, mocked_http, limits):
        """bonk.io names are unique ignoring case, so these are one account."""
        limits(visitor_wrong_passwords=10)
        bonk = _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client, username="TestPlayer")
        _post_login(client, username="testplayer ")

        _post_login(client, username="TESTPLAYER")

        assert bonk.call_count == 2

    def test_a_strangers_wrong_passwords_do_not_hold_the_player(self, client, mocked_http):
        """The count is per name AND visitor, so typing someone's name with
        wrong passwords holds only the person typing."""
        _bonk_says(mocked_http, "login_wrong_password")
        for _ in range(3):
            stranger = _post_login(client, username="TestPlayer", ip="198.51.100.66")
        assert _messages(stranger)[0].startswith(HELD_MESSAGE_START)
        bonk = _bonk_now_says(mocked_http, "login_success")

        response = _post_login(client, username="TestPlayer", ip="203.0.113.7")

        assert bonk.call_count == 1
        assert response.status_code == 302

    def test_a_success_starts_the_count_over(self, client, mocked_http):
        _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client)
        _bonk_now_says(mocked_http, "login_success")
        _post_login(client)
        client.logout()
        # The visitor's count is separate; this test is about the account's.
        login_attempts._Tracker("client", pseudonym("client", "203.0.113.7"), 1).clear()
        bonk = _bonk_now_says(mocked_http, "login_wrong_password")

        for _ in range(2):
            response = _post_login(client)

        assert bonk.call_count == 2
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
        for _ in range(3):
            rate_limit_cooldowns.reset()
            response = _post_login(client)

        assert not any(m.startswith(HELD_MESSAGE_START) for m in _messages(response))


@pytest.mark.usefixtures("only_personal_limits")
class TestPerVisitor:
    def test_holds_a_visitor_after_two_wrong_passwords_across_names(self, client, mocked_http):
        """RFC-0003 Part 1, item 3: on Railway's IP bonk.io trips after 3, so
        one visitor's old allowance of 3 could lock everyone out alone."""
        bonk = _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client, username="first name")
        _post_login(client, username="second name")

        response = _post_login(client, username="third name")

        assert bonk.call_count == 2
        assert _messages(response)[0].startswith(HELD_MESSAGE_START)

    def test_unknown_usernames_have_their_own_looser_count(self, client, mocked_http, settings):
        """bonk.io doesn't count unknown usernames (20 in a row, 2026-11-10)."""
        allowed = settings.BONK_LOGIN_LIMITS["visitor_unknown_usernames"]
        bonk = _bonk_says(mocked_http, "login_unknown_username")
        for n in range(allowed - 1):
            response = _post_login(client, username=f"guess{n}")
        assert response.context["retry_after"] is None

        _post_login(client, username="one more guess")
        response = _post_login(client, username="fresh name")

        assert bonk.call_count == allowed
        assert _messages(response)[0].startswith(HELD_MESSAGE_START)

    def test_unknown_usernames_do_not_use_up_wrong_passwords(self, client, mocked_http):
        _bonk_says(mocked_http, "login_unknown_username")
        _post_login(client, username="typo one")
        _post_login(client, username="typo two")
        bonk = _bonk_now_says(mocked_http, "login_wrong_password")

        _post_login(client, username="TestPlayer")

        assert bonk.call_count == 1

    def test_other_visitors_are_not_held(self, client, mocked_http):
        bonk = _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client, username="first name")
        _post_login(client, username="second name")

        _post_login(client, username="fresh name", ip="198.51.100.20")

        assert bonk.call_count == 3


class TestSiteWrongPasswordBudget:
    """RFC-0003 Part 1, item 2: three trips on 2026-11-10 came after exactly
    3 wrong passwords from different visitors."""

    def _spend_the_budget(self, client, mocked_http):
        _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client, username="first person", ip="198.51.100.1")
        _post_login(client, username="second person", ip="198.51.100.2")

    def test_new_logins_wait_instead_of_spending_the_third(self, client, mocked_http):
        self._spend_the_budget(client, mocked_http)
        bonk = _bonk_now_says(mocked_http, "login_success")

        response = _post_login(client, username="TestPlayer", ip="203.0.113.50")

        assert bonk.call_count == 0
        assert response.status_code == 200
        assert response.context["retry_after"] == FAILURE_WINDOW
        assert _messages(response) == [
            "Bonk.io login failed: A few wrong passwords were typed on Bonkverse just now. "
            "One more would make bonk.io pause logins for everyone, so new logins wait "
            "about 15 minutes. This isn't your fault."
        ]

    def test_logins_go_again_once_the_oldest_ages_out(self, client, mocked_http, clock):
        self._spend_the_budget(client, mocked_http)
        bonk = _bonk_now_says(mocked_http, "login_success")

        clock.advance(FAILURE_WINDOW + 1)
        response = _post_login(client, username="TestPlayer", ip="203.0.113.50")

        assert bonk.call_count == 1
        assert response.status_code == 302

    def test_the_wait_counts_down_from_the_oldest(self, client, mocked_http, clock):
        _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client, username="first person", ip="198.51.100.1")
        clock.advance(300)
        _post_login(client, username="second person", ip="198.51.100.2")
        clock.advance(60)

        response = _post_login(client, username="TestPlayer", ip="203.0.113.50")

        assert response.context["retry_after"] == FAILURE_WINDOW - 360

    def test_unknown_usernames_do_not_count(self, client, mocked_http):
        _bonk_says(mocked_http, "login_unknown_username")
        for n in range(3):
            _post_login(client, username=f"nobody {n}", ip=f"198.51.100.{n + 1}")
        bonk = _bonk_now_says(mocked_http, "login_success")

        response = _post_login(client, username="TestPlayer", ip="203.0.113.50")

        assert bonk.call_count == 1
        assert response.status_code == 302

    def test_the_wear_login_waits_too(self, client, logged_in_client, mocked_http):
        self._spend_the_budget(client, mocked_http)
        bonk = _bonk_now_says(mocked_http, "login_success")

        response = logged_in_client.post(
            WEAR_LOGIN_URL, {"bonk_username": "TestPlayer", "bonk_password": "pw"}
        )

        assert bonk.call_count == 0
        assert response.status_code == 401
        body = response.json()
        assert "auth" not in body
        assert body["error"] == SITE_WAIT
        assert body["retry_after"] == FAILURE_WINDOW


class TestCaps:
    """RFC-0003 Part 1, item 1: on 2026-11-10 a bot sent 17 logins in 100 s
    from rotating IPs with no wrong password, and bonk.io paused everyone."""

    def test_the_site_sends_at_most_its_cap_a_minute(self, client, mocked_http, settings):
        cap = settings.BONK_LOGIN_LIMITS["site_per_minute"]
        bonk = _bonk_says(mocked_http, "login_unknown_username")
        for n in range(cap):
            _post_login(client, username=f"alt {n}", ip=f"198.51.100.{n + 1}")

        response = _post_login(client, username="one too many", ip="198.51.100.99")

        assert bonk.call_count == cap
        assert response.context["retry_after"] == 55  # to the next minute
        assert _messages(response) == [
            "Bonk.io login failed: Lots of logins right now. Try again in 55 seconds."
        ]

    def test_the_next_minute_has_room_again(self, client, mocked_http, settings, clock):
        cap = settings.BONK_LOGIN_LIMITS["site_per_minute"]
        bonk = _bonk_says(mocked_http, "login_unknown_username")
        for n in range(cap + 1):
            _post_login(client, username=f"alt {n}", ip=f"198.51.100.{n + 1}")

        clock.advance(60)
        _post_login(client, username="next minute", ip="198.51.100.99")

        assert bonk.call_count == cap + 1

    def test_one_account_logs_in_at_most_once_a_minute(self, client, mocked_http, limits):
        limits(site_wrong_passwords=0)
        bonk = _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client, username="TestPlayer", ip="198.51.100.1")

        response = _post_login(client, username="testplayer", ip="198.51.100.2")

        assert bonk.call_count == 1
        assert response.context["retry_after"] == 55
        assert _messages(response)[0] == (
            "Bonk.io login failed: Lots of logins right now. Try again in 55 seconds."
        )

    def test_logins_turned_away_by_the_account_cap_leave_room_for_others(
        self, client, mocked_http, settings, limits
    ):
        limits(site_wrong_passwords=0)
        cap = settings.BONK_LOGIN_LIMITS["site_per_minute"]
        bonk = _bonk_says(mocked_http, "login_unknown_username")
        for n in range(5):
            _post_login(client, username="same alt", ip=f"198.51.100.{n + 1}")

        for n in range(cap - 1):
            _post_login(client, username=f"someone {n}", ip=f"203.0.113.{n + 1}")

        assert bonk.call_count == cap

    def test_during_bonks_pause_tries_do_not_use_up_the_caps(self, client, mocked_http, settings):
        _bonk_says(mocked_http, {"r": "fail", "e": "ratelimited"})
        cap = settings.BONK_LOGIN_LIMITS["site_per_minute"]
        for n in range(cap + 2):
            _post_login(client, username=f"waiting {n}", ip=f"198.51.100.{n + 1}")
        rate_limit_cooldowns.reset()
        bonk = _bonk_now_says(mocked_http, "login_success")

        response = _post_login(client, username="TestPlayer", ip="203.0.113.50")

        assert bonk.call_count == 1
        assert response.status_code == 302


class TestOneAtATime:
    def test_a_second_login_while_the_first_waits_on_bonk_is_turned_away(self, client, mocked_http):
        """2026-11-10: a double submit 0.86 s apart spent 2 of the site's 3
        wrong passwords at once."""
        bonk = _bonk_says(mocked_http, "login_wrong_password")
        key = pseudonym("account_client", "testplayer\n203.0.113.7")
        with login_attempts._in_flight(key):
            response = _post_login(client)

        assert bonk.call_count == 0
        assert _messages(response) == [
            "Bonk.io login failed: Your last login is still going. Give it a few seconds."
        ]

    def test_the_lock_is_let_go_after_the_login(self, client, mocked_http, limits):
        limits(account_per_minute=0)
        bonk = _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client)

        _post_login(client)

        assert bonk.call_count == 2

    def test_the_in_page_login_answers_in_progress_without_auth(
        self, logged_in_client, mocked_http
    ):
        _bonk_says(mocked_http, "login_success")
        key = pseudonym("account_client", "testplayer\n127.0.0.1")
        with login_attempts._in_flight(key):
            response = logged_in_client.post(
                WEAR_LOGIN_URL, {"bonk_username": "TestPlayer", "bonk_password": "pw"}
            )

        assert response.status_code == 401
        assert response.json()["error"] == IN_PROGRESS


class TestWhenBonkRateLimits:
    def _two_people_spend_wrong_passwords(self, client, mocked_http, limits):
        # Room for a third wrong password, as bonk.io's real count may be lower.
        limits(site_wrong_passwords=0)
        _bonk_says(mocked_http, "login_wrong_password")
        _post_login(client, username="first person", ip="198.51.100.1")
        _post_login(client, username="second person", ip="198.51.100.2")

    def test_holds_everyone_with_a_recent_wrong_password(self, client, mocked_http, limits):
        """RFC-0003 Part 1, item 4: the login that got "ratelimited" was often
        an innocent one; the visitors who spent the budget weren't held."""
        self._two_people_spend_wrong_passwords(client, mocked_http, limits)
        _bonk_now_says(mocked_http, {"r": "fail", "e": "ratelimited"})
        _post_login(client, username="innocent", ip="203.0.113.50")
        rate_limit_cooldowns.reset()  # bonk.io's pause ends
        bonk = _bonk_now_says(mocked_http, "login_success")

        first = _post_login(client, username="other name", ip="198.51.100.1")
        second = _post_login(client, username="another name", ip="198.51.100.2")

        assert bonk.call_count == 0
        expected = LOGIN_RATE_LIMIT_PAUSE + AFTER_PAUSE_SECONDS
        assert first.context["retry_after"] == expected
        assert second.context["retry_after"] == expected

    def test_does_not_hold_the_innocent_login_that_got_it(self, client, mocked_http, limits, clock):
        self._two_people_spend_wrong_passwords(client, mocked_http, limits)
        _bonk_now_says(mocked_http, {"r": "fail", "e": "ratelimited"})
        _post_login(client, username="innocent", ip="203.0.113.50")
        rate_limit_cooldowns.reset()
        clock.advance(60)  # past the account's one-a-minute cap
        bonk = _bonk_now_says(mocked_http, "login_success")

        response = _post_login(client, username="innocent", ip="203.0.113.50")

        assert bonk.call_count == 1
        assert response.status_code == 302

    def test_with_no_wrong_passwords_nobody_is_held(self, client, mocked_http, clock):
        _bonk_says(mocked_http, {"r": "fail", "e": "ratelimited"})
        _post_login(client)
        rate_limit_cooldowns.reset()
        clock.advance(60)  # past the account's one-a-minute cap
        bonk = _bonk_now_says(mocked_http, "login_success")

        response = _post_login(client)

        assert bonk.call_count == 1
        assert response.status_code == 302

    def test_the_pause_says_it_is_for_everyone_and_not_their_fault(self, client, mocked_http):
        _bonk_says(mocked_http, {"r": "fail", "e": "ratelimited"})

        response = _post_login(client)

        assert _messages(response) == [
            "Bonk.io login failed: bonk.io has paused logins from Bonkverse for everyone, "
            "so this isn't your fault. Try again in about 17 minutes."
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

    def test_same_account_gets_the_same_tag(self, client, mocked_http, caplog, limits):
        limits(account_per_minute=0)
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

    @pytest.mark.parametrize(
        ("setup", "line"),
        [
            ("held", "bonk login held"),
            ("site_wait", "bonk login waiting for the site budget"),
            ("busy", "bonk login busy"),
        ],
    )
    def test_turned_away_attempts_are_logged(self, client, mocked_http, caplog, setup, line):
        _bonk_says(mocked_http, "login_wrong_password")
        if setup == "held":
            _post_login(client, username="a", ip="198.51.100.1")
            _post_login(client, username="b", ip="198.51.100.1")
        elif setup == "site_wait":
            _post_login(client, username="a", ip="198.51.100.1")
            _post_login(client, username="b", ip="198.51.100.2")
        else:
            _post_login(client, username="a", ip="198.51.100.1")

        with caplog.at_level(logging.INFO, logger="skins.login"):
            _post_login(client, username="a", ip="198.51.100.1")

        assert any(line in r.getMessage() for r in caplog.records)


@pytest.mark.usefixtures("only_personal_limits")
class TestWearLogin:
    def test_the_in_page_login_is_held_too(self, logged_in_client, mocked_http):
        bonk = _bonk_says(mocked_http, "login_wrong_password")
        form = {"bonk_username": "TestPlayer", "bonk_password": "wrong"}
        for _ in range(2):
            logged_in_client.post(WEAR_LOGIN_URL, form)

        response = logged_in_client.post(WEAR_LOGIN_URL, form)

        assert bonk.call_count == 2
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

    def test_busy_answers_without_auth(self, logged_in_client, mocked_http, limits):
        limits(account_per_minute=1)
        _bonk_says(mocked_http, "login_wrong_password")
        form = {"bonk_username": "TestPlayer", "bonk_password": "wrong"}
        logged_in_client.post(WEAR_LOGIN_URL, form)

        response = logged_in_client.post(WEAR_LOGIN_URL, form)

        assert response.status_code == 401
        assert response.json()["error"] == BUSY


def test_a_broken_cache_never_stops_a_login(client, mocked_http, monkeypatch):
    """The guards are a courtesy to bonk.io; Redis being down must not lock players out."""

    class BrokenCache:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise ConnectionError("redis down")

            return fail

    monkeypatch.setattr(login_attempts, "cache", BrokenCache())
    bonk = _bonk_says(mocked_http, "login_wrong_password")

    for _ in range(6):
        _post_login(client)

    assert bonk.call_count == 6
