"""Tests for the bonk.io account API client (integrations/bonk_api.py).

bonk.io is faked with `responses` using the bodies in tests/fixtures/bonk/.
These tests pin the request shape we send and how every kind of answer
(success, refusal, outage) becomes a typed result.
"""

import logging
from urllib.parse import parse_qs

import pytest
import requests

from core.bonk import AvatarSlot
from integrations.bonk_api import (
    BROWSER_HEADERS,
    AVATAR_UPDATE_SCRIPT,
    FRIENDS_SCRIPT,
    LOGIN_RATE_LIMIT_PAUSE,
    LOGIN_SCRIPT,
    RATE_LIMIT_COOLDOWN_MAX,
    BonkApi,
    BonkError,
    BonkFriend,
    _Cooldowns,
    backoff_seconds,
    get_client,
    redact,
)
from tests.conftest import load_bonk_fixture

BASE = "https://bonk2.io/scripts"
LOGIN = f"{BASE}/login_legacy.php"
FRIENDS = f"{BASE}/friends.php"
AVATAR = f"{BASE}/avatar_update.php"


@pytest.fixture
def api():
    return BonkApi(BASE)


def _sent_form(call) -> dict:
    return {k: v[0] for k, v in parse_qs(call.request.body).items()}


class TestLogin:
    def test_success_is_typed(self, api, mocked_http):
        mocked_http.post(LOGIN, json=load_bonk_fixture("login_success"))

        result = api.login("testplayer", "hunter2")

        assert result.ok is True
        assert result.token == "SCRUBBED-TEST-TOKEN-abc123"
        assert result.username.value == "TestPlayer"
        assert result.bonk_id == 1234567
        assert result.active_slot == AvatarSlot(2)
        assert result.error is None

    def test_sends_the_web_clients_request_shape(self, api, mocked_http):
        """The one request shape for login (RFC-0001 Phase 2.2): the fields
        bonk.io's own web client sends, plus its Origin/Referer."""
        call = mocked_http.post(LOGIN, json=load_bonk_fixture("login_success"))

        api.login("TestPlayer", "hunter2")

        assert _sent_form(call.calls[0]) == {
            "username": "TestPlayer",
            "password": "hunter2",
            "remember": "false",
        }
        headers = call.calls[0].request.headers
        assert headers["Origin"] == "https://bonk.io"
        assert headers["Referer"] == "https://bonk.io/"

    def test_typed_username_is_sent_unchanged(self, api, mocked_http):
        call = mocked_http.post(LOGIN, json=load_bonk_fixture("login_success"))

        api.login(" Spaced  Name ", "pw")

        assert _sent_form(call.calls[0])["username"] == " Spaced  Name "

    def test_falls_back_to_typed_username_if_bonk_omits_it(self, api, mocked_http):
        body = load_bonk_fixture("login_success")
        del body["username"]
        mocked_http.post(LOGIN, json=body)

        assert api.login("Typed Name", "pw").username.value == "Typed Name"

    def test_lowercase_active_slot_key_is_accepted(self, api, mocked_http):
        body = load_bonk_fixture("login_success")
        body["activeavatarnumber"] = body.pop("activeAvatarNumber")
        mocked_http.post(LOGIN, json=body)

        assert api.login("TestPlayer", "pw").active_slot == AvatarSlot(2)

    def test_carries_legacy_friends(self, api, mocked_http):
        mocked_http.post(LOGIN, json={**load_bonk_fixture("login_success"), "legacyFriends": "A#B"})

        assert api.login("TestPlayer", "pw").legacy_friends == "A#B"

    @pytest.mark.parametrize(
        "fixture,error,bonk_error",
        [
            ("login_wrong_password", BonkError.WRONG_PASSWORD, "password"),
            ("login_unknown_username", BonkError.UNKNOWN_USERNAME, "username_fail"),
        ],
    )
    def test_known_refusals(self, api, mocked_http, fixture, error, bonk_error):
        mocked_http.post(LOGIN, json=load_bonk_fixture(fixture))

        result = api.login("TestPlayer", "wrong")

        assert result.ok is False
        assert result.error == error
        assert result.bonk_error == bonk_error
        assert result.token is None

    def test_unknown_refusal_keeps_bonk_code(self, api, mocked_http):
        mocked_http.post(LOGIN, json={"r": "fail", "e": "something_new"})

        result = api.login("TestPlayer", "pw")

        assert result.error == BonkError.REJECTED
        assert result.bonk_error == "something_new"

    def test_success_without_token_is_a_refusal(self, api, mocked_http):
        mocked_http.post(LOGIN, json={"r": "success"})

        assert api.login("TestPlayer", "pw").ok is False

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"body": requests.ConnectionError("down")},
            {"body": requests.Timeout("slow")},
            {"body": "<html>Cloudflare challenge</html>", "status": 503},
            {"body": "<html>not json</html>", "status": 200},
            {"json": ["not", "an", "object"]},
            {"json": {"r": "fail"}, "status": 500},
        ],
    )
    def test_no_usable_answer_is_unavailable(self, api, mocked_http, kwargs):
        mocked_http.post(LOGIN, **kwargs)

        result = api.login("TestPlayer", "pw")

        assert result.ok is False
        assert result.error == BonkError.UNAVAILABLE

    def test_password_and_token_never_logged(self, api, mocked_http, caplog):
        mocked_http.post(
            LOGIN,
            body='{"r":"success","token":"SECRET-TOKEN-xyz", oops',
            status=200,
        )
        with caplog.at_level(logging.DEBUG, logger="integrations.bonk_api"):
            api.login("TestPlayer", "hunter2")

        assert "SECRET-TOKEN-xyz" not in caplog.text
        assert "hunter2" not in caplog.text

    def test_repr_hides_token(self, api, mocked_http):
        mocked_http.post(LOGIN, json=load_bonk_fixture("login_success"))

        assert "SCRUBBED-TEST-TOKEN" not in repr(api.login("TestPlayer", "pw"))


class TestGetFriends:
    def test_parses_friends_and_requests(self, api, mocked_http):
        call = mocked_http.post(FRIENDS, json=load_bonk_fixture("friends_success"))

        result = api.get_friends("tok")

        assert result.ok is True
        assert result.friends == (
            BonkFriend(2000001, "Friend One"),
            BonkFriend(2000002, " Spaced  Name "),  # never trimmed
            BonkFriend(2000003, None),  # blank name: kept, so it still counts
        )
        assert result.requests == (BonkFriend(2000004, "Wants To Be Friends"),)
        assert _sent_form(call.calls[0]) == {"token": "tok", "task": "getfriends"}

    def test_refusal(self, api, mocked_http):
        mocked_http.post(FRIENDS, json=load_bonk_fixture("friends_token_expired"))

        result = api.get_friends("tok")

        assert (result.ok, result.error, result.bonk_error) == (
            False,
            BonkError.TOKEN_REJECTED,
            "token",
        )

    def test_outage(self, api, mocked_http):
        mocked_http.post(FRIENDS, body=requests.Timeout("slow"))

        assert api.get_friends("tok").error == BonkError.UNAVAILABLE


class TestUpdateAvatar:
    def test_success_and_request_shape(self, api, mocked_http):
        call = mocked_http.post(AVATAR, json=load_bonk_fixture("avatar_update_success"))

        result = api.update_avatar("tok", AvatarSlot(4), "CODE")

        assert result.ok is True
        assert _sent_form(call.calls[0]) == {
            "task": "updateavatar",
            "token": "tok",
            "newavatarslot": "4",
            "newavatar": "CODE",
        }

    @pytest.mark.parametrize(
        "body,error",
        [
            (load_bonk_fixture("avatar_update_token_expired"), BonkError.TOKEN_REJECTED),
            (load_bonk_fixture("avatar_update_too_big"), BonkError.AVATAR_TOO_BIG),
            (load_bonk_fixture("ratelimited"), BonkError.RATE_LIMITED),
            ({"r": "fail", "e": "something_new"}, BonkError.REJECTED),
        ],
    )
    def test_each_refusal_code(self, api, mocked_http, body, error):
        mocked_http.post(AVATAR, json=body)

        result = api.update_avatar("tok", AvatarSlot(1), "CODE")

        assert (result.ok, result.error, result.bonk_error) == (False, error, body["e"])

    def test_outage_is_unavailable_not_rejected(self, api, mocked_http):
        """An outage must not look like a stale token, or the wear flow asks
        the player to log in to bonk.io again for nothing."""
        mocked_http.post(AVATAR, body=requests.ConnectionError("down"))

        assert api.update_avatar("tok", AvatarSlot(1), "CODE").error == BonkError.UNAVAILABLE


def test_get_client_reads_settings(settings):
    settings.BONK_API_BASE_URL = "https://bonk.example/scripts"
    settings.BONK_CONNECT_TIMEOUT = 1.5
    settings.BONK_READ_TIMEOUT = 2.5

    client = get_client()

    assert client.base_url == "https://bonk.example/scripts"
    assert client.timeout == (1.5, 2.5)


def test_every_call_sends_browser_headers(api, mocked_http):
    call = mocked_http.post(AVATAR, json={"r": "success"})

    api.update_avatar("tok", AvatarSlot(1), "CODE")

    for key, value in BROWSER_HEADERS.items():
        assert call.calls[0].request.headers[key] == value


def test_redact_removes_tokens_from_cut_off_json():
    assert redact('{"r":"success","token":"abc.def"') == '{"r":"success","token":"***REDACTED***"'


class TestRateLimitCooldown:
    """After bonk.io says "ratelimited" for a script, Bonkverse stops calling
    that script for a while rather than adding requests while bonk.io is
    limiting the server's IP."""

    def test_ratelimited_script_is_paused(self, api, mocked_http):
        mocked_http.post(AVATAR, json={"r": "fail", "e": "ratelimited"})

        first = api.update_avatar("tok", AvatarSlot(1), "CODE")
        second = api.update_avatar("other", AvatarSlot(2), "CODE")

        assert (first.error, first.bonk_error) == (BonkError.RATE_LIMITED, "ratelimited")
        assert (second.error, second.bonk_error) == (BonkError.RATE_LIMITED, None)
        assert len(mocked_http.calls) == 1  # the second was answered locally

    def test_a_wear_limit_does_not_block_logins(self, api, mocked_http):
        """Regression for 2026-11-09: bonk.io accepted a login one second
        before limiting a wear, while the old shared pause had refused six of
        that player's logins."""
        mocked_http.post(AVATAR, json={"r": "fail", "e": "ratelimited"})
        mocked_http.post(LOGIN, json=load_bonk_fixture("login_success"))

        api.update_avatar("tok", AvatarSlot(1), "CODE")
        login = api.login("TestPlayer", "pw")

        assert login.ok is True

    def test_calls_resume_after_the_cooldown(self, mocked_http):
        now = [1000.0]
        api = BonkApi(BASE, cooldowns=_Cooldowns(clock=lambda: now[0]))
        mocked_http.post(LOGIN, json={"r": "fail", "e": "ratelimited"})
        api.login("TestPlayer", "pw")

        now[0] += LOGIN_RATE_LIMIT_PAUSE - 1
        assert api.login("TestPlayer", "pw").bonk_error is None  # still paused
        now[0] += 2
        mocked_http.replace("POST", LOGIN, json=load_bonk_fixture("login_success"))
        assert api.login("TestPlayer", "pw").ok is True

    def test_other_refusals_do_not_pause(self, api, mocked_http):
        mocked_http.post(AVATAR, json={"r": "fail", "e": "avatar_too_big"})

        api.update_avatar("tok", AvatarSlot(1), "CODE")
        api.update_avatar("tok", AvatarSlot(1), "CODE")

        assert len(mocked_http.calls) == 2


class TestLoginPause:
    """Measured 2026-11-10 (docs/bonk/login-rate-limit.md): bonk.io's login
    block lasts ~15 min after the last request it saw, and any request during
    it restarts the 15 min. The old 2/4/8/16-min checks kept restarting it."""

    def test_login_pauses_once_for_17_minutes_however_many_in_a_row(self, mocked_http):
        now = [1000.0]
        cooldowns = _Cooldowns(clock=lambda: now[0])
        api = BonkApi(BASE, cooldowns=cooldowns)
        mocked_http.post(LOGIN, json={"r": "fail", "e": "ratelimited"})

        for _ in range(3):
            api.login("TestPlayer", "pw")
            assert cooldowns.remaining(LOGIN_SCRIPT) == LOGIN_RATE_LIMIT_PAUSE == 17 * 60
            now[0] += LOGIN_RATE_LIMIT_PAUSE + 1

    def test_nothing_reaches_bonk_during_the_login_pause(self, mocked_http):
        now = [1000.0]
        api = BonkApi(BASE, cooldowns=_Cooldowns(clock=lambda: now[0]))
        bonk = mocked_http.post(LOGIN, json={"r": "fail", "e": "ratelimited"})
        api.login("TestPlayer", "pw")

        for minutes in (2, 4, 8, 16):
            now[0] = 1000.0 + minutes * 60
            api.login("TestPlayer", "pw")

        assert bonk.call_count == 1

    def test_other_scripts_keep_the_doubling_pause(self):
        assert backoff_seconds(1, LOGIN_SCRIPT) == backoff_seconds(5, LOGIN_SCRIPT) == 1020
        assert backoff_seconds(1, AVATAR_UPDATE_SCRIPT) == 120
        assert backoff_seconds(2, FRIENDS_SCRIPT) == 240


class TestBackoff:
    """Regression for 2026-11-09: a flat 2-minute pause let the first wear
    after each pause reach bonk.io and be limited again, five times in a row."""

    def test_pause_doubles_up_to_the_cap(self):
        assert [backoff_seconds(n) for n in range(1, 7)] == [120, 240, 480, 960, 1800, 1800]
        assert RATE_LIMIT_COOLDOWN_MAX == 1800

    def test_limits_in_a_row_pause_longer(self, mocked_http):
        now = [1000.0]
        cooldowns = _Cooldowns(clock=lambda: now[0])
        api = BonkApi(BASE, cooldowns=cooldowns)
        mocked_http.post(AVATAR, json={"r": "fail", "e": "ratelimited"})

        api.update_avatar("tok", AvatarSlot(1), "CODE")
        assert cooldowns.remaining(AVATAR_UPDATE_SCRIPT) == 120
        now[0] += 121
        api.update_avatar("tok", AvatarSlot(1), "CODE")
        assert cooldowns.remaining(AVATAR_UPDATE_SCRIPT) == 240
        now[0] += 241
        api.update_avatar("tok", AvatarSlot(1), "CODE")
        assert cooldowns.remaining(AVATAR_UPDATE_SCRIPT) == 480

    def test_a_normal_answer_starts_the_backoff_over(self, mocked_http):
        now = [1000.0]
        cooldowns = _Cooldowns(clock=lambda: now[0])
        api = BonkApi(BASE, cooldowns=cooldowns)
        mocked_http.post(AVATAR, json={"r": "fail", "e": "ratelimited"})
        api.update_avatar("tok", AvatarSlot(1), "CODE")
        now[0] += 121

        mocked_http.replace("POST", AVATAR, json=load_bonk_fixture("avatar_update_success"))
        assert api.update_avatar("tok", AvatarSlot(1), "CODE").ok is True
        mocked_http.replace("POST", AVATAR, json={"r": "fail", "e": "ratelimited"})
        api.update_avatar("tok", AvatarSlot(1), "CODE")

        assert cooldowns.remaining(AVATAR_UPDATE_SCRIPT) == 120

    def test_the_rate_limit_log_says_how_long(self, api, mocked_http, caplog):
        mocked_http.post(AVATAR, json={"r": "fail", "e": "ratelimited"})

        with caplog.at_level(logging.INFO, logger="integrations.bonk_api"):
            api.update_avatar("tok", AvatarSlot(1), "CODE")
            api.update_avatar("tok", AvatarSlot(1), "CODE")

        messages = [r.getMessage() for r in caplog.records]
        assert (
            "bonk.io rate-limited avatar_update.php (1 in a row); "
            "pausing avatar_update.php calls for 120s"
        ) in messages
        assert any("answered rate_limited without calling it" in m for m in messages)


class TestSharedCooldown:
    """Regression for 2026-11-09: the pause lived in one gunicorn worker, so
    the others kept calling bonk.io and extended its limit."""

    def test_a_pause_started_in_one_process_stops_another(self, mocked_http):
        from django.core.cache import cache

        now = [1000.0]
        worker_a = BonkApi(BASE, cooldowns=_Cooldowns(clock=lambda: now[0], store=cache))
        worker_b = BonkApi(BASE, cooldowns=_Cooldowns(clock=lambda: now[0], store=cache))
        mocked_http.post(AVATAR, json={"r": "fail", "e": "ratelimited"})

        worker_a.update_avatar("tok", AvatarSlot(1), "CODE")
        result = worker_b.update_avatar("tok", AvatarSlot(1), "CODE")

        assert result.error == BonkError.RATE_LIMITED
        assert result.bonk_error is None  # answered locally by worker B
        assert len(mocked_http.calls) == 1

    def test_the_backoff_count_is_shared_too(self, mocked_http):
        from django.core.cache import cache

        now = [1000.0]
        a = _Cooldowns(clock=lambda: now[0], store=cache)
        b = _Cooldowns(clock=lambda: now[0], store=cache)
        mocked_http.post(AVATAR, json={"r": "fail", "e": "ratelimited"})

        BonkApi(BASE, cooldowns=a).update_avatar("tok", AvatarSlot(1), "CODE")
        now[0] += 121
        BonkApi(BASE, cooldowns=b).update_avatar("tok", AvatarSlot(1), "CODE")

        assert b.remaining(AVATAR_UPDATE_SCRIPT) == 240  # second in a row, though b saw one

    def test_store_failure_falls_back_to_this_process(self, mocked_http):
        class Broken:
            def __getattr__(self, name):
                def fail(*a, **k):
                    raise ConnectionError

                return fail

        api = BonkApi(BASE, cooldowns=_Cooldowns(store=Broken()))
        mocked_http.post(AVATAR, json={"r": "fail", "e": "ratelimited"})

        api.update_avatar("tok", AvatarSlot(1), "CODE")
        second = api.update_avatar("tok", AvatarSlot(1), "CODE")

        assert second.bonk_error is None
        assert len(mocked_http.calls) == 1
