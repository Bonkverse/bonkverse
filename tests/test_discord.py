"""Discord invite lookups: the client (integrations/discord_api.py), the
submit service and view (communities/services.py, communities/views/submit.py)
and the hourly refresh (communities/tasks.py).

Discord is faked with `responses`. Bodies follow Discord's documented invite
object plus the undocumented `profile` block Bonkverse has always read.
"""

import logging

import pytest
import requests

from integrations.discord_api import InviteError, fetch_invite
from skins.models import DiscordServer, DiscordServerSnapshot, DiscordTag
from communities.tasks import refresh_discord_servers

API = "https://discord.com/api/v10/invites"
SUBMIT_URL = "/api/discords/submit/"


def _invite_body(guild_id="111", *, members=120, online=30, expires_at=None, profile=True):
    body = {
        "code": "abc",
        "expires_at": expires_at,
        "guild": {
            "id": guild_id,
            "name": "Bonk Club",
            "description": "We play bonk",
            "icon": "iconhash",
            "splash": None,
        },
        "approximate_member_count": members + 1,
        "approximate_presence_count": online + 1,
    }
    if profile:
        body["profile"] = {"member_count": members, "online_count": online}
    return body


# ---------- client ----------


def test_parses_invite(mocked_http):
    call = mocked_http.get(f"{API}/abc", json=_invite_body())

    result = fetch_invite("abc")

    invite = result.invite
    assert result.error is None
    assert (invite.guild_id, invite.name, invite.icon_hash) == ("111", "Bonk Club", "iconhash")
    assert (invite.member_count, invite.online_count) == (120, 30)  # profile preferred
    assert invite.expires_at is None
    assert call.calls[0].request.params == {"with_counts": "true", "with_expiration": "true"}


def test_falls_back_to_documented_counts(mocked_http):
    mocked_http.get(f"{API}/abc", json=_invite_body(profile=False))

    invite = fetch_invite("abc").invite

    assert (invite.member_count, invite.online_count) == (121, 31)


@pytest.mark.parametrize("code", ["", "../../users/@me", "abc?x=1", "a" * 33, "has space"])
def test_bad_codes_are_never_sent(mocked_http, code):
    """The code goes into the URL path, so it is checked before any request."""
    assert fetch_invite(code).error == InviteError.INVALID_CODE
    assert len(mocked_http.calls) == 0


def test_unknown_invite(mocked_http):
    mocked_http.get(f"{API}/gone", json={"message": "Unknown Invite", "code": 10006}, status=404)

    assert fetch_invite("gone").error == InviteError.NOT_FOUND


def test_rate_limited_reads_retry_after(mocked_http):
    mocked_http.get(f"{API}/abc", json={"retry_after": 2.5, "global": False}, status=429)

    result = fetch_invite("abc")

    assert (result.error, result.retry_after) == (InviteError.RATE_LIMITED, 2.5)


@pytest.mark.parametrize(
    "kwargs",
    [{"body": requests.ConnectionError("down")}, {"body": "<html>", "status": 502}],
)
def test_no_usable_answer(mocked_http, kwargs):
    mocked_http.get(f"{API}/abc", **kwargs)

    assert fetch_invite("abc").error == InviteError.UNAVAILABLE


# ---------- submit view ----------


def _submit(client, invite="https://discord.gg/abc", tags=()):
    return client.post(SUBMIT_URL, {"invite": invite, "tags": list(tags)}, follow=True)


def _messages(response):
    return [str(m) for m in response.context["messages"]]


@pytest.mark.django_db
def test_submit_creates_server_with_tags_and_snapshot(client, mocked_http):
    mocked_http.get(f"{API}/abc", json=_invite_body())
    DiscordTag.objects.create(name="Competitive", category="style")

    response = _submit(client, tags=["Competitive", "Not A Real Tag"])

    server = DiscordServer.objects.get()
    assert (server.guild_id, server.invite_code, server.member_count) == ("111", "abc", 120)
    assert list(server.tags.values_list("name", flat=True)) == ["Competitive"]
    assert DiscordServerSnapshot.objects.filter(server=server).count() == 1
    assert "✅ Discord server submitted successfully!" in _messages(response)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "setup,message",
    [
        (
            {"json": {"message": "Unknown Invite", "code": 10006}, "status": 404},
            "❌ Invalid or inaccessible Discord invite.",
        ),
        (
            {"body": requests.Timeout("slow")},
            "❌ Couldn't reach Discord right now. Try again in a minute.",
        ),
        (
            {"json": {"retry_after": 30}, "status": 429},
            "❌ Couldn't reach Discord right now. Try again in a minute.",
        ),
        (
            {"json": _invite_body(expires_at="2026-12-01T00:00:00+00:00")},
            "❌ Invite must be permanent",
        ),
    ],
)
def test_submit_failures(client, mocked_http, setup, message):
    mocked_http.get(f"{API}/abc", **setup)

    response = _submit(client)

    assert _messages(response)[0].startswith(message)
    assert not DiscordServer.objects.exists()


@pytest.mark.django_db
def test_submit_rejects_path_tricks_without_calling_discord(client, mocked_http):
    response = _submit(client, invite="https://discord.gg/abc%2F..%2Fusers")

    assert _messages(response) == ["❌ Invalid Discord invite format."]
    assert len(mocked_http.calls) == 0


@pytest.mark.django_db
def test_submit_same_server_twice_keeps_one(client, mocked_http):
    mocked_http.get(f"{API}/abc", json=_invite_body())
    mocked_http.get(f"{API}/other", json=_invite_body())

    _submit(client)
    response = _submit(client, invite="other")

    assert DiscordServer.objects.count() == 1
    assert "⚠️ This Discord server has already been submitted." in _messages(response)


# ---------- hourly refresh ----------


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr("communities.tasks.time.sleep", calls.append)
    return calls


def _server(code, guild_id, last_fetched_at=None):
    return DiscordServer.objects.create(
        guild_id=guild_id,
        invite_code=code,
        invite_url=f"https://discord.gg/{code}",
        name=code,
        last_fetched_at=last_fetched_at,
    )


@pytest.mark.django_db
def test_refresh_updates_counts_and_paces_one_per_second(mocked_http, sleeps):
    a, b = _server("aaa", "1"), _server("bbb", "2")
    mocked_http.get(f"{API}/aaa", json=_invite_body("1", members=10, online=1))
    mocked_http.get(f"{API}/bbb", json=_invite_body("2", members=20, online=2))

    stats = refresh_discord_servers()

    a.refresh_from_db()
    b.refresh_from_db()
    assert (a.member_count, b.member_count) == (10, 20)
    assert DiscordServerSnapshot.objects.count() == 2
    assert stats["refreshed"] == 2
    assert sleeps == [1.0, 1.0]  # was 1/40 s


@pytest.mark.django_db
def test_refresh_logs_failures_and_keeps_going(mocked_http, sleeps, caplog):
    """Regression: failures went to print() and vanished."""
    _server("aaa", "1")
    _server("bbb", "2")
    mocked_http.get(f"{API}/aaa", body=requests.ConnectionError("down"))
    mocked_http.get(f"{API}/bbb", json=_invite_body("2"))

    with caplog.at_level(logging.WARNING, logger="communities.tasks"):
        stats = refresh_discord_servers()

    assert (stats["failed"], stats["refreshed"]) == (1, 1)
    assert "discord refresh failed for server id=" in caplog.text


@pytest.mark.django_db
def test_refresh_waits_out_a_429_then_continues(mocked_http, sleeps):
    _server("aaa", "1")
    mocked_http.get(f"{API}/aaa", json={"retry_after": 3.0}, status=429)
    mocked_http.get(f"{API}/aaa", json=_invite_body("1"))

    stats = refresh_discord_servers()

    assert stats["refreshed"] == 1
    assert sleeps[0] == 3.0


@pytest.mark.django_db
def test_refresh_stops_when_still_rate_limited(mocked_http, sleeps):
    _server("aaa", "1")
    _server("bbb", "2")
    for code in ("aaa", "bbb"):
        mocked_http.get(f"{API}/{code}", json={"retry_after": 600}, status=429)

    stats = refresh_discord_servers()

    assert stats["stopped_rate_limited"] is True
    assert sleeps == [60.0]  # capped wait, then stop
    assert len(mocked_http.calls) == 2  # first server twice; the second never tried
    assert not DiscordServerSnapshot.objects.exists()


@pytest.mark.django_db
def test_refresh_goes_stalest_first(mocked_http, sleeps):
    """A run stopped by a rate limit shouldn't keep skipping the same servers."""
    from datetime import datetime, timezone

    _server("fresh", "1", last_fetched_at=datetime(2026, 11, 5, 12, tzinfo=timezone.utc))
    _server("old", "2", last_fetched_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    _server("never", "3")
    for code, guild in (("fresh", "1"), ("old", "2"), ("never", "3")):
        mocked_http.get(f"{API}/{code}", json=_invite_body(guild))

    refresh_discord_servers()

    order = [call.request.url.split("/invites/")[1].split("?")[0] for call in mocked_http.calls]
    assert order == ["never", "old", "fresh"]


@pytest.mark.django_db
def test_refresh_counts_gone_invites_without_changing_rows(mocked_http, sleeps):
    server = _server("aaa", "1")
    mocked_http.get(f"{API}/aaa", json={"message": "Unknown Invite"}, status=404)

    stats = refresh_discord_servers()

    server.refresh_from_db()
    assert stats["not_found"] == 1
    assert server.status == DiscordServer.Status.ACTIVE


@pytest.mark.django_db
def test_refresh_stops_cleanly_at_its_time_limit(mocked_http, monkeypatch):
    """Celery raises SoftTimeLimitExceeded inside the run; it ends with its stats logged."""
    from celery.exceptions import SoftTimeLimitExceeded

    _server("aaa", "1")
    _server("bbb", "2")
    mocked_http.get(f"{API}/aaa", json=_invite_body("1"))
    mocked_http.get(f"{API}/bbb", json=_invite_body("2"))

    def sleep_then_time_out(seconds):
        # The limit lands while pausing after the first server.
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr("communities.tasks.time.sleep", sleep_then_time_out)

    stats = refresh_discord_servers()

    assert stats["refreshed"] == 1
    assert stats["stopped_time_limit"] is True
    assert DiscordServerSnapshot.objects.count() == 1
    assert len(mocked_http.calls) == 1


# ---------- CSRF ----------


@pytest.mark.django_db
def test_submit_requires_the_csrf_token():
    """The submit form sends {% csrf_token %}; a cross-site POST without it is refused."""
    from django.test import Client

    response = Client(enforce_csrf_checks=True).post(SUBMIT_URL, {"invite": "abc"})

    assert response.status_code == 403
    assert DiscordServer.objects.count() == 0


@pytest.mark.django_db
def test_submit_page_form_carries_the_csrf_token(client):
    html = client.get("/submit/").content.decode()

    assert 'name="csrfmiddlewaretoken"' in html
