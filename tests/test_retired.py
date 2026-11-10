"""Endpoints retired in RFC-0001 Phase 1 stay gone; what replaced or survived them works.

The win/loss userscript (record wins/losses, heartbeat, stop tracking, bonk.io
verification via BonkBot, leaderboard JSON) was shut down. Its PlayerWin and
PlayerLoss rows are kept; PlayerSession (its login tokens) was dropped.
"""

import pytest
from django.apps import apps

from skins.events import log_event

pytestmark = pytest.mark.django_db

RETIRED = [
    "/api/wins/",
    "/api/losses/",
    "/api/leaderboard/all/",
    "/api/loss-leaderboard/week/",
    "/api/heartbeat/",
    "/api/stop_tracking/",
    "/api/request_verification/",
    "/api/complete_verification/",
]


@pytest.mark.parametrize("url", RETIRED)
@pytest.mark.parametrize("method", ["get", "post"])
def test_retired_endpoint_is_gone(client, url, method):
    assert getattr(client, method)(url).status_code == 404


def test_player_session_model_is_gone_but_win_loss_data_is_kept():
    skins_models = {model.__name__ for model in apps.get_app_config("skins").get_models()}
    stats_models = {model.__name__ for model in apps.get_app_config("stats").get_models()}

    assert "PlayerSession" not in skins_models
    # Moved to stats in RFC-0001 Phase 5.3b, same tables.
    assert {"PlayerWin", "PlayerLoss"} <= stats_models


class TestFriendsSyncStatus:
    """Still used: My Profile polls it after login."""

    URL = "/api/friends-sync-status/"

    def test_signed_out_is_401(self, client):
        assert client.get(self.URL).status_code == 401

    def test_pending_until_sync_logs_its_event(self, logged_in_client):
        assert logged_in_client.get(self.URL).json() == {"status": "pending"}

    def test_done_with_counts(self, logged_in_client, user):
        log_event(user, "friends_synced", friends_now=12, added_edges=3)

        body = logged_in_client.get(self.URL).json()

        assert body["status"] == "done"
        assert (body["friends_now"], body["added_edges"], body["removed_edges"]) == (12, 3, 0)
