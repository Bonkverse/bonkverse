"""The regular friend sync after login runs on the worker (skins.tasks.sync_friends).

Login queues the task with the account link's id once the link is saved; the
task reads the token from the link, asks bonk.io for the friend list and
stores it. The profile toast polls /api/friends-sync-status/ for the event
the task logs. Queued tasks run inline in tests (tests/conftest.py), and
bonk.io is faked with `responses` (tests/fixtures/bonk/).
"""

from unittest import mock

import pytest
import requests
from django.db.models import Q
from django.urls import reverse

from skins import login as login_module
from skins.friends_sync import NO_TOKEN, sync_friends_for_link
from skins.models import BonkAccountLink, BonkPlayer, Friendship, UserEvent
from skins.tasks import sync_friends
from tests.conftest import load_bonk_fixture
from tests.factories import UserFactory

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
BONK_FRIENDS_URL = "https://bonk2.io/scripts/friends.php"
TOKEN = "SCRUBBED-TEST-TOKEN-abc123"

pytestmark = pytest.mark.django_db


def _link(*, token=TOKEN, active=True, bonk_id=1234567, username="TestPlayer"):
    user = UserFactory(username=username)
    player = BonkPlayer.objects.create(bonk_id=bonk_id, username=username)
    return BonkAccountLink.objects.create(
        user=user,
        bonk_player=player,
        token_encrypted=BonkAccountLink.sign_token(token) if token else None,
        active=active,
    )


def _sent_token(call) -> str:
    from urllib.parse import parse_qs

    return parse_qs(call.request.body)["token"][0]


class TestTask:
    def test_stores_friends_and_logs_the_event_the_toast_waits_for(self, mocked_http):
        mocked_http.post(BONK_FRIENDS_URL, json=load_bonk_fixture("friends_success"))
        link = _link()

        stats = sync_friends(link.id)

        assert stats["friends_now"] == 3
        # The friend with an empty name gets a player row but no edge.
        assert Friendship.objects.filter(Q_player(link.bonk_player)).count() == 2
        event = UserEvent.objects.get(user=link.user, event_type="friends_synced")
        assert event.metadata["friends_now"] == 3

    def test_sends_the_stored_token(self, mocked_http):
        mocked_http.post(BONK_FRIENDS_URL, json=load_bonk_fixture("friends_success"))
        link = _link()

        sync_friends(link.id)

        assert _sent_token(mocked_http.calls[0]) == TOKEN

    def test_running_twice_is_harmless(self, mocked_http):
        mocked_http.post(BONK_FRIENDS_URL, json=load_bonk_fixture("friends_success"))
        link = _link()

        sync_friends(link.id)
        edges = set(
            Friendship.objects.filter(Q_player(link.bonk_player)).values_list("id", flat=True)
        )
        sync_friends(link.id)

        assert (
            set(Friendship.objects.filter(Q_player(link.bonk_player)).values_list("id", flat=True))
            == edges
        )

    def test_skips_a_link_that_is_gone_or_inactive(self, mocked_http):
        inactive = _link(active=False)

        assert sync_friends(inactive.id) == {"skipped": "link_gone"}
        assert sync_friends(999_999) == {"skipped": "link_gone"}
        assert len(mocked_http.calls) == 0

    def test_no_stored_token_means_no_call(self, mocked_http):
        link = _link(token=None)

        assert sync_friends(link.id) == {"error": NO_TOKEN}
        assert len(mocked_http.calls) == 0

    def test_retries_when_bonk_is_unreachable_then_succeeds(self, mocked_http):
        mocked_http.post(BONK_FRIENDS_URL, body=requests.ConnectionError("down"))
        mocked_http.post(BONK_FRIENDS_URL, json=load_bonk_fixture("friends_success"))
        link = _link()

        # Inline, Celery runs each retry straight away; throw=False keeps the
        # outer attempt's Retry from failing the test.
        sync_friends.apply(args=(link.id,), throw=False)

        assert len(mocked_http.calls) == 2
        assert UserEvent.objects.filter(user=link.user, event_type="friends_synced").exists()

    def test_gives_up_after_two_retries(self, mocked_http, settings):
        # Inline, each retry runs inside the one before; let the last
        # attempt's result come back instead of a Retry exception.
        settings.CELERY_TASK_EAGER_PROPAGATES = False
        mocked_http.post(BONK_FRIENDS_URL, body=requests.ConnectionError("down"))
        link = _link()

        sync_friends.apply(args=(link.id,), throw=False)

        assert len(mocked_http.calls) == 3  # first try + 2 retries
        assert not UserEvent.objects.filter(event_type="friends_synced").exists()

    @pytest.mark.parametrize("fixture", ["friends_token_expired", "ratelimited"])
    def test_never_retries_a_refusal(self, mocked_http, fixture):
        mocked_http.post(BONK_FRIENDS_URL, json=load_bonk_fixture(fixture))
        link = _link()

        result = sync_friends.apply(args=(link.id,), throw=False)

        assert result.successful()
        assert len(mocked_http.calls) == 1
        assert not UserEvent.objects.filter(event_type="friends_synced").exists()

    def test_service_reports_bonk_refusals(self, mocked_http):
        mocked_http.post(BONK_FRIENDS_URL, json=load_bonk_fixture("friends_token_expired"))
        link = _link()

        assert sync_friends_for_link(link).error == "token_rejected"


class TestToken:
    def test_round_trips(self):
        link = _link(token="abc")
        assert link.bonk_token() == "abc"

    def test_tampered_value_reads_as_none(self):
        link = _link()
        link.token_encrypted = link.token_encrypted[:-2] + "xx"
        assert link.bonk_token() is None


class TestLoginQueuesTheSync:
    @pytest.fixture(autouse=True)
    def _sync_on(self, settings, mocked_http):
        settings.SYNC_FRIENDS_ON_LOGIN = True
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

    def test_login_syncs_friends_through_the_worker(self, client, mocked_http):
        mocked_http.post(BONK_FRIENDS_URL, json=load_bonk_fixture("friends_success"))

        response = client.post("/login/", {"username": "TestPlayer", "password": "x"})

        assert response.status_code == 302
        assert client.session["show_friend_sync_toast"] is True
        status = client.get(reverse("friends_sync_status")).json()
        assert status["status"] == "done"
        assert status["friends_now"] == 3

    def test_queues_only_the_link_id_never_the_token(self, client):
        with mock.patch.object(login_module, "enqueue", return_value=True) as enqueue:
            client.post("/login/", {"username": "TestPlayer", "password": "x"})

        link = BonkAccountLink.objects.get(bonk_player__bonk_id=1234567)
        enqueue.assert_called_once_with(sync_friends, link.id)

    def test_requests_run_in_autocommit(self, settings):
        """Login queues right after saving the link; that is only safe while a
        request isn't one transaction. If this changes, queue with
        transaction.on_commit and set the toast flag before the session saves."""
        assert not settings.DATABASES["default"].get("ATOMIC_REQUESTS", False)

    def test_no_toast_when_the_sync_could_not_be_queued(self, client):
        with mock.patch.object(login_module, "enqueue", return_value=False):
            response = client.post("/login/", {"username": "TestPlayer", "password": "x"})

        assert response.status_code == 302  # the login itself still works
        assert "show_friend_sync_toast" not in client.session

    def test_off_switch(self, client, settings):
        settings.SYNC_FRIENDS_ON_LOGIN = False
        with mock.patch.object(login_module, "enqueue") as enqueue:
            client.post("/login/", {"username": "TestPlayer", "password": "x"})

        enqueue.assert_not_called()


def Q_player(player):
    return Q(player_low=player) | Q(player_high=player)
