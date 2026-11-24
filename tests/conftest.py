"""Shared pytest fixtures for the Bonkverse Django test suite.

Owns: test-wide settings overrides, the HTTP-mocking guard that keeps tests
from ever reaching bonk.io, and small fixtures for users and skins.
Does not own: model factories (see tests/factories.py) or recorded bonk.io
payloads (see tests/fixtures/bonk/).
"""

import base64
import json
from pathlib import Path

import pytest

import responses
from django.core.cache import cache

from tests.factories import SkinFactory, UserFactory

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _test_settings(settings):
    """Isolate every test from shared state and from production services.

    - LocMem cache, so tests never flush a developer's local Redis, and rate-limit
      counters start at zero for every test.
    - Plain static storage, so templates render without running collectstatic.
    """
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "bonkverse-tests",
        }
    }
    # django-ratelimit refuses non-shared caches by default; tests are single-process.
    settings.SILENCED_SYSTEM_CHECKS = ["django_ratelimit.E003", "django_ratelimit.W001"]
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _no_real_http():
    """Fail any test that makes an un-mocked outbound HTTP request.

    Tests that need bonk.io register responses on the `mocked_http` fixture,
    which is this same RequestsMock.
    """
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture
def mocked_http(_no_real_http):
    """The active `responses` mock; register fake bonk.io replies on it."""
    return _no_real_http


@pytest.fixture(autouse=True)
def _rate_limit_windows_stand_still(monkeypatch):
    """django-ratelimit uses fixed windows that end on the clock (every 10 s
    for "2/10s"). A test that sends a quick burst could straddle a window's
    end and see the count reset partway through, so in tests the limiter's
    clock is pinned: a test's requests always land in one window.

    Regression: tests/test_wear.py's burst test failed in CI on 2026-11-22
    when its five requests crossed a 10-second window edge."""
    import types

    import django_ratelimit.core

    monkeypatch.setattr(
        django_ratelimit.core, "time", types.SimpleNamespace(time=lambda: 1_800_000_000.0)
    )


@pytest.fixture(autouse=True)
def _no_bonk_rate_limit_cooldown():
    """The bonk.io cooldown is process-wide; never let one test's 429 leak into the next."""
    from integrations.bonk_api import rate_limit_cooldowns

    rate_limit_cooldowns.reset()
    yield
    rate_limit_cooldowns.reset()


@pytest.fixture(autouse=True)
def _tasks_run_inline(settings):
    """Anything queued with core.background.enqueue runs inside the test, errors included.

    Tests never need Redis or a worker. Set through Django settings: the Celery
    app reads CELERY_* settings live, and they win over `app.conf.x = ...`
    (setting app.conf here silently did nothing; test_background checks this).
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.fixture(autouse=True)
def _no_background_friend_sync(settings):
    """Login normally queues a friend sync (bonk.io friends.php); tests that
    want it turn it on (tests/test_friend_sync_task.py)."""
    settings.SYNC_FRIENDS_ON_LOGIN = False


def load_bonk_fixture(name: str) -> dict:
    """Load a recorded (token-scrubbed) bonk.io response from tests/fixtures/bonk/."""
    return json.loads((FIXTURES_DIR / "bonk" / f"{name}.json").read_text())


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def staff_user(db):
    return UserFactory(is_staff=True)


@pytest.fixture
def skin(db):
    return SkinFactory()


@pytest.fixture
def logged_in_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def staff_client(client, staff_user):
    client.force_login(staff_user)
    return client


def make_bonk_token(*, exp: float, **fields) -> str:
    """A made-up bonk.io session token (a JWT) with the given `exp`.

    The signature is junk: Bonkverse only reads the payload, and bonk.io is
    mocked in tests.
    """

    def part(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    payload = {"uid": 1, "un": "TestPlayer", "g": "b", **fields, "exp": int(exp)}
    return f"{part({'alg': 'HS256', 'typ': 'JWT'})}.{part(payload)}.not-a-real-signature"


def connect_bonk(
    client,
    user,
    *,
    player=None,
    token="test-bonk-token",
    slot=2,
    expires_in=3600,
    remember_token=None,
):
    """Give `user` a bonk.io connection the token broker can use: an account
    link holding `token` (good for `expires_in` seconds; None for no session
    token) and, optionally, a remember-me token; and point `client`'s
    session at that account (accounts/bonk_tokens.py, RFC-0003 Part 2).

    Returns the link.
    """
    from datetime import timedelta

    from django.utils import timezone

    from accounts.models import BonkAccountLink
    from tests.factories import BonkPlayerFactory

    player = player or BonkPlayerFactory()
    link, _ = BonkAccountLink.objects.update_or_create(
        user=user,
        bonk_player=player,
        defaults={
            "token_encrypted": BonkAccountLink.encrypt_token(token) if token else None,
            "token_expires_at": timezone.now() + timedelta(seconds=expires_in) if token else None,
            "active_slot": slot,
            "remember_token_encrypted": (
                BonkAccountLink.encrypt_token(remember_token) if remember_token else None
            ),
            "remember_status": (
                BonkAccountLink.REMEMBER_ACTIVE if remember_token else BonkAccountLink.REMEMBER_NONE
            ),
        },
    )
    session = client.session
    session["bonk_user_id"] = player.bonk_id
    session["bonk_username"] = player.username
    if slot is not None:
        session["bonk_active_slot"] = slot
    session.save()
    return link


@pytest.fixture
def bonk_session_client(logged_in_client, user):
    """A logged-in client with a live bonk.io connection (an account link
    whose token is good for an hour; active slot 2). `.link` and `.player`
    are the link and its BonkPlayer."""
    link = connect_bonk(logged_in_client, user)
    logged_in_client.link = link
    logged_in_client.player = link.bonk_player
    return logged_in_client
