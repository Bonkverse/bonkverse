"""A key's usage (public_api/usage.py) and its usage page
(/developers/keys/<prefix>/): every request with a valid key is counted by
day and endpoint, and the owner sees the limits right now and 30 days of use."""

import re
from datetime import timedelta
from unittest import mock

import pytest
from django.db import DatabaseError
from django.test import Client

from public_api import usage
from public_api.keys import create_key
from public_api.models import ApiKey, ApiKeyUsageDay
from public_api.tasks import prune_api_usage
from tests.factories import UserFactory
from tests.test_public_api import LOOKUP

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _replays_url(settings):
    settings.BONKVERSE_REPLAYS_URL = "http://replays.test"


@pytest.fixture
def owned(user):
    """(ApiKey, raw key) belonging to the signed-in test user."""
    return create_key(name="My bot", owner=user)


def call(client, raw, path="/api/v1/me/"):
    return client.get(path, HTTP_AUTHORIZATION=f"Bearer {raw}")


def page(client, api_key):
    return client.get(f"/developers/keys/{api_key.prefix}/")


# ── Counting ─────────────────────────────────────────────────────────────────


def test_requests_are_counted_by_day_and_endpoint(client, owned, mocked_http):
    api_key, raw = owned
    mocked_http.get(LOOKUP, json={"results": []})

    call(client, raw)
    call(client, raw)
    assert call(client, raw, "/api/v1/players/nobody/").status_code == 404

    rows = {r.endpoint: r for r in ApiKeyUsageDay.objects.filter(api_key=api_key)}
    assert (rows["me"].requests, rows["me"].errors, rows["me"].day) == (2, 0, usage.today())
    assert (rows["player"].requests, rows["player"].errors) == (1, 1)  # the 404


def test_rate_limited_requests_are_counted(client, owned, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "api": "1/m"}
    api_key, raw = owned

    call(client, raw)
    assert call(client, raw).status_code == 429

    row = ApiKeyUsageDay.objects.get(api_key=api_key, endpoint="me")
    assert (row.requests, row.rate_limited, row.errors) == (2, 1, 0)


def test_bad_keys_are_not_counted(client):
    call(client, "bvk_nope_nope")
    assert not ApiKeyUsageDay.objects.exists()


def test_counting_never_breaks_the_api(client, owned):
    _key, raw = owned
    with mock.patch.object(ApiKeyUsageDay.objects, "filter", side_effect=DatabaseError):
        assert call(client, raw).status_code == 200


# ── The summary ──────────────────────────────────────────────────────────────


def test_summary_fills_every_day_and_sorts_endpoints(owned):
    api_key, _raw = owned
    today = usage.today()
    ApiKeyUsageDay.objects.create(api_key=api_key, day=today, endpoint="me", requests=4)
    ApiKeyUsageDay.objects.create(
        api_key=api_key, day=today - timedelta(days=2), endpoint="player", requests=10, errors=3
    )
    # Too old for the page
    ApiKeyUsageDay.objects.create(
        api_key=api_key, day=today - timedelta(days=30), endpoint="me", requests=99
    )

    summary = usage.summary(api_key)

    assert len(summary["daily"]) == 30
    assert summary["daily"][-1] == {"day": today, "requests": 4, "height": 40}
    assert summary["daily"][-3]["height"] == 100
    assert summary["totals"] == {"requests": 14, "rate_limited": 0, "errors": 3}
    assert [row["label"] for row in summary["endpoints"]] == [
        "GET /api/v1/players/{username}/",
        "GET /api/v1/me/",
    ]


def test_old_usage_is_pruned_daily(owned):
    api_key, _raw = owned
    today = usage.today()
    for days_ago in (0, 29, 30, 45):
        ApiKeyUsageDay.objects.create(
            api_key=api_key, day=today - timedelta(days=days_ago), endpoint="me", requests=1
        )

    assert prune_api_usage() == {"deleted": 2}
    assert ApiKeyUsageDay.objects.count() == 2


# ── The page ─────────────────────────────────────────────────────────────────


def test_owner_sees_limits_left_this_minute_and_usage(logged_in_client, client, owned):
    api_key, raw = owned
    call(client, raw)

    html = page(logged_in_client, api_key).content.decode()

    assert "Limits right now" in html
    assert "<code>GET /api/v1/me/</code>" in html
    left = re.search(r"<code>GET /api/v1/me/</code></td>\s*<td[^>]*>60</td>\s*<td[^>]*>\s*(\d+)", html)
    assert left and left.group(1) == "59"  # 60 a minute, one used
    assert "1</strong> request" in html


def test_partner_keys_show_the_partner_rate(logged_in_client, user):
    api_key, _raw = create_key(name="League", owner=user, tier=ApiKey.TIER_PARTNER)

    html = page(logged_in_client, api_key).content.decode()

    assert 'data-label="Per minute">300</td>' in html
    assert "Partner" in html


def test_a_key_without_use_says_so(logged_in_client, owned):
    api_key, _raw = owned
    assert "No requests in the last 30 days." in page(logged_in_client, api_key).content.decode()


def test_revoked_keys_keep_their_history_without_limits(logged_in_client, owned):
    api_key, _raw = owned
    ApiKeyUsageDay.objects.create(api_key=api_key, day=usage.today(), endpoint="me", requests=3)
    api_key.revoke()

    html = page(logged_in_client, api_key).content.decode()

    assert "Limits right now" not in html
    assert "Revoked" in html
    assert "3</strong> request" in html


def test_only_the_owner_sees_a_key(logged_in_client):
    someone_elses, _raw = create_key(name="Theirs", owner=UserFactory())

    assert page(logged_in_client, someone_elses).status_code == 404
    response = page(Client(), someone_elses)
    assert response.status_code == 302 and response["Location"].startswith("/login/")


def test_keys_list_links_to_each_keys_usage(logged_in_client, owned):
    api_key, _raw = owned
    html = logged_in_client.get("/developers/keys/").content.decode()
    assert f'href="/developers/keys/{api_key.prefix}/"' in html
