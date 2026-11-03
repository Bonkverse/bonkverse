"""Shared pytest fixtures for the Bonkverse Django test suite.

Owns: test-wide settings overrides, the HTTP-mocking guard that keeps tests
from ever reaching bonk.io, and small fixtures for users and skins.
Does not own: model factories (see tests/factories.py) or recorded bonk.io
payloads (see tests/fixtures/bonk/).
"""

import json
import time
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
def _no_background_friend_sync(monkeypatch):
    """Login normally starts a background thread for friend sync; keep tests synchronous."""
    monkeypatch.setattr("skins.login.SYNC_FRIENDS_ON_LOGIN", False)


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
def bonk_session_client(logged_in_client):
    """A logged-in client whose session also holds a live bonk.io token."""
    session = logged_in_client.session
    session["bonk_token"] = "test-bonk-token"
    session["bonk_token_expires"] = time.time() + 3600
    session["bonk_active_slot"] = 2
    session.save()
    return logged_in_client
