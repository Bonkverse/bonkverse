"""JSON contract for voting and favoriting (skins/skin_votes.py).

Phase 3 moves the browser code that calls these endpoints into one shared
module (bv-api.js); these tests pin exactly what the pages rely on, so that
rewrite can't silently change it. The wear endpoints' contract is pinned in
test_wear.py.
"""

import json

import pytest

from skins.models import SkinVote, UserEvent
from tests.factories import SkinFactory, UserFactory

pytestmark = pytest.mark.django_db


def _vote_url(skin):
    return f"/api/skins/{skin.id}/vote/"


def _fav_url(skin):
    return f"/api/skins/{skin.id}/favorite/"


@pytest.fixture
def skin():
    return SkinFactory()


class TestVote:
    def test_upvote(self, logged_in_client, skin):
        response = logged_in_client.post(_vote_url(skin), {"vote": "up"})

        assert response.status_code == 200
        assert response.json() == {
            "upvotes": 1,
            "downvotes": 0,
            "current_vote": "up",
            "status": "ok",
        }

    def test_same_vote_again_removes_it(self, logged_in_client, skin):
        logged_in_client.post(_vote_url(skin), {"vote": "up"})

        response = logged_in_client.post(_vote_url(skin), {"vote": "up"})

        assert response.json() == {
            "upvotes": 0,
            "downvotes": 0,
            "current_vote": None,
            "status": "ok",
        }
        assert not SkinVote.objects.exists()

    def test_switching_moves_the_vote(self, logged_in_client, skin):
        logged_in_client.post(_vote_url(skin), {"vote": "up"})

        response = logged_in_client.post(_vote_url(skin), {"vote": "down"})

        assert response.json() == {
            "upvotes": 0,
            "downvotes": 1,
            "current_vote": "down",
            "status": "ok",
        }
        skin.refresh_from_db()
        assert (skin.upvotes, skin.downvotes) == (0, 1)

    def test_counts_include_other_voters(self, logged_in_client, skin):
        other = UserFactory(username="Other Voter")
        SkinVote.objects.create(user=other, skin=skin, vote="up")
        skin.upvotes = 1
        skin.save()

        response = logged_in_client.post(_vote_url(skin), {"vote": "up"})

        assert response.json()["upvotes"] == 2

    def test_json_body_is_accepted(self, logged_in_client, skin):
        response = logged_in_client.post(
            _vote_url(skin), json.dumps({"vote": "down"}), content_type="application/json"
        )

        assert response.json()["current_vote"] == "down"

    @pytest.mark.parametrize("vote", ["", "sideways", "UP"])
    def test_invalid_vote_is_400(self, logged_in_client, skin, vote):
        response = logged_in_client.post(_vote_url(skin), {"vote": vote})

        assert response.status_code == 400
        assert response.json() == {"error": "invalid vote"}

    def test_logs_an_event_when_a_vote_is_cast(self, logged_in_client, skin):
        logged_in_client.post(_vote_url(skin), {"vote": "up"})
        logged_in_client.post(_vote_url(skin), {"vote": "up"})  # removal: no event

        events = UserEvent.objects.filter(event_type="skin_voted")
        assert [e.metadata for e in events] == [{"direction": "up"}]

    def test_anonymous_is_401(self, client, skin):
        """Pinned as-is: no `auth` tag here, unlike the wear endpoints. The
        search page's postForm redirects to /login/ on any 401."""
        response = client.post(_vote_url(skin), {"vote": "up"})

        assert response.status_code == 401
        assert response.json() == {"error": "auth required"}

    def test_missing_skin_is_404(self, logged_in_client):
        assert logged_in_client.post("/api/skins/999999/vote/", {"vote": "up"}).status_code == 404

    def test_get_is_405(self, logged_in_client, skin):
        assert logged_in_client.get(_vote_url(skin)).status_code == 405


class TestFavorite:
    def test_favorite_then_unfavorite(self, logged_in_client, skin):
        first = logged_in_client.post(_fav_url(skin))
        second = logged_in_client.post(_fav_url(skin))

        assert first.status_code == 200
        assert first.json() == {
            "favorited": True,
            "favorites": 1,
            "upvotes": 0,
            "downvotes": 0,
            "status": "ok",
        }
        assert second.json() == {
            "favorited": False,
            "favorites": 0,
            "upvotes": 0,
            "downvotes": 0,
            "status": "ok",
        }

    def test_count_includes_other_users(self, logged_in_client, skin):
        skin.favorited_by.add(UserFactory(username="Fan One"), UserFactory(username="Fan Two"))

        response = logged_in_client.post(_fav_url(skin))

        assert (response.json()["favorited"], response.json()["favorites"]) == (True, 3)

    def test_logs_events(self, logged_in_client, skin):
        logged_in_client.post(_fav_url(skin))
        logged_in_client.post(_fav_url(skin))

        assert list(UserEvent.objects.order_by("id").values_list("event_type", flat=True)) == [
            "skin_favorited",
            "skin_unfavorited",
        ]

    def test_anonymous_is_401(self, client, skin):
        response = client.post(_fav_url(skin))

        assert response.status_code == 401
        assert response.json() == {"error": "auth required"}
        assert not skin.favorited_by.exists()

    def test_missing_skin_is_404(self, logged_in_client):
        assert logged_in_client.post("/api/skins/999999/favorite/").status_code == 404

    def test_get_is_405(self, logged_in_client, skin):
        assert logged_in_client.get(_fav_url(skin)).status_code == 405
