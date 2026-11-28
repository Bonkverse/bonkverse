"""Signing in with a code typed in a bonk.io room the bot hosts
(accounts/room_claims.py, integrations/roombot.py, ADR 0026; experimental).

The room service (roombot/) is faked over HTTP. A claim is proven only by a
message with this browser's code, typed by the claimed account as bonk.io's
server reports it, and never by a guest.
"""

import json
import re

import pytest
import requests
import responses
from django.utils import timezone

from accounts import room_claims
from accounts.models import BonkAccountLink, BonkUser, LinkClaim
from players.models import BonkPlayer
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

ROOMBOT = "http://roombot.internal"
TOKEN = "r" * 40
LINK = "https://bonk.io/816187dbais"


@pytest.fixture(autouse=True)
def roombot_on(settings):
    settings.ROOMBOT_URL = ROOMBOT
    settings.ROOMBOT_TOKEN = TOKEN


def _room_opens(mocked_http, room_id="room-abc123xyz"):
    mocked_http.add(
        responses.POST, f"{ROOMBOT}/rooms", json={"id": room_id, "link": LINK}, status=201
    )
    mocked_http.add(
        responses.POST, re.compile(rf"{ROOMBOT}/rooms/{room_id}/close"), json={"state": "closed"}
    )
    return room_id


def _room_says(mocked_http, room_id, *, messages=(), players=(), state="open"):
    mocked_http.add(
        responses.GET,
        f"{ROOMBOT}/rooms/{room_id}",
        json={
            "id": room_id,
            "state": state,
            "link": LINK,
            "players": [{"username": n, "guest": g, "level": 10} for n, g in players],
            "messages": [{"username": n, "guest": g, "text": t} for n, g, t in messages],
        },
    )


def _start(client, mocked_http, name="ButDoge"):
    room_id = _room_opens(mocked_http)
    response = client.post("/login/room/", {"username": name})
    claim = LinkClaim.objects.get(method=LinkClaim.ROOM_CODE)
    assert response.status_code == 302
    assert response["Location"] == f"/login/room/{claim.pk}/"
    code = client.session[room_claims.SESSION_KEY][str(claim.pk)]
    return claim, code, room_id


def _status(client, claim):
    return client.post(f"/login/room/{claim.pk}/status/").json()


# ── Starting ─────────────────────────────────────────────────────────


def test_start_opens_a_room_and_keeps_only_a_hash_of_the_code(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)

    assert len(code) == 6
    assert claim.code_hash and code not in claim.code_hash
    assert claim.room_id == room_id and claim.room_link == LINK
    sent = mocked_http.calls[0].request
    assert json.loads(sent.body) == {"name": "ButDoge"}
    assert sent.headers["Authorization"] == f"Bearer {TOKEN}"


def test_the_waiting_page_shows_the_code_link_and_experimental_label(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    _room_says(mocked_http, room_id)

    page = client.get(f"/login/room/{claim.pk}/").content.decode()

    assert code in page and LINK in page
    assert "Experimental" in page


def test_the_login_page_offers_it_marked_experimental(client):
    page = client.get("/login/").content.decode()
    assert "/login/room/" in page and "Experimental" in page


def test_hidden_when_the_room_service_isnt_set_up(client, settings):
    settings.ROOMBOT_URL = ""
    assert "/login/room/" not in client.get("/login/").content.decode()
    client.post("/login/room/", {"username": "ButDoge"})
    assert not LinkClaim.objects.exists()


def test_busy_room_service_says_so_and_starts_nothing(client, mocked_http):
    mocked_http.add(responses.POST, f"{ROOMBOT}/rooms", json={"retry_after": 90}, status=429)

    page = client.post("/login/room/", {"username": "ButDoge"}, follow=True).content.decode()

    assert "busy" in page
    assert not LinkClaim.objects.exists()


@pytest.mark.parametrize("name", ["Boſsman", "Café"])
def test_non_ascii_names_are_refused_before_any_room_opens(client, mocked_http, name):
    client.post("/login/room/", {"username": name})
    assert not LinkClaim.objects.exists()
    assert not mocked_http.calls


# ── Accounts already on Bonkverse (owner decision 2026-11-27) ────────


def _prove_in_room(client, mocked_http, name="ButDoge", level=10):
    claim, code, room_id = _start(client, mocked_http, name=name)
    mocked_http.add(
        responses.GET,
        f"{ROOMBOT}/rooms/{room_id}",
        json={
            "id": room_id,
            "state": "open",
            "link": LINK,
            "players": [{"username": name, "guest": False, "level": level}],
            "messages": [{"username": name, "guest": False, "text": code}],
        },
    )
    return _status(client, claim)


def test_an_account_already_on_bonkverse_signs_in(client, mocked_http):
    owner = UserFactory(username="ButDoge")
    player = BonkPlayer.objects.create(username="ButDoge", bonk_id=4242, xp=None)
    BonkAccountLink.objects.create(user=owner, bonk_player=player, active=True)

    assert _prove_in_room(client, mocked_http)["status"] == "done"

    assert int(client.session["_auth_user_id"]) == owner.pk
    assert BonkUser.objects.filter(username__iexact="ButDoge").count() == 1


def test_it_counts_as_the_owners_proof_and_records_the_level(client, mocked_http):
    from accounts.groups import voting_standing
    from skins.votes import why_cant_vote

    _prove_in_room(client, mocked_http, level=12)

    user = BonkUser.objects.get(username="ButDoge")
    link = BonkAccountLink.objects.get(user=user)
    assert link.owner_proven_at is not None
    assert voting_standing(user) == (12, False)
    assert why_cant_vote(user) is None


def test_a_low_level_from_the_room_cant_vote(client, mocked_http):
    from skins.votes import why_cant_vote

    _prove_in_room(client, mocked_http, level=3)

    assert "level 5" in why_cant_vote(BonkUser.objects.get(username="ButDoge"))


def test_the_room_level_never_lowers_what_a_password_login_stored(client, mocked_http):
    from core.bonk.levels import level_for_xp, xp_for_level

    BonkPlayer.objects.create(username="ButDoge", bonk_id=4242, xp=xp_for_level(40) + 50)

    _prove_in_room(client, mocked_http, level=12)

    assert level_for_xp(BonkPlayer.objects.get(username="ButDoge").xp) == 40


def test_it_takes_back_an_account_only_a_friend_request_claimed(
    client, mocked_http, django_capture_on_commit_callbacks
):
    """Like a password (ADR 0024): Mallory claimed ButDoge by friend request
    and grouped it with her account; the owner proves it with a room code."""
    from django.test import Client

    from accounts import groups

    account = UserFactory(username="ButDoge")
    player = BonkPlayer.objects.create(username="ButDoge", bonk_id=4242)
    BonkAccountLink.objects.create(user=account, bonk_player=player, active=True)
    groups.join(UserFactory(username="MalloryAlt"), account)
    mallory = Client()
    mallory.force_login(account)

    with django_capture_on_commit_callbacks(execute=True):
        assert _prove_in_room(client, mocked_http)["status"] == "done"

    account.refresh_from_db()
    assert account.account_group_id is None
    assert mallory.get("/api/me/").status_code == 401  # her session ended
    assert client.get("/api/me/").json()["user"]["username"] == "ButDoge"


def test_an_owner_proven_account_isnt_taken_out_of_its_group(client, mocked_http):
    from accounts import groups

    account = UserFactory(username="ButDoge")
    player = BonkPlayer.objects.create(username="ButDoge", bonk_id=4242)
    BonkAccountLink.objects.create(
        user=account, bonk_player=player, active=True, owner_proven_at=timezone.now()
    )
    groups.join(UserFactory(username="MainOne"), account)
    group_id = BonkUser.objects.get(pk=account.pk).account_group_id

    _prove_in_room(client, mocked_http)

    account.refresh_from_db()
    assert account.account_group_id == group_id


# ── Proving ──────────────────────────────────────────────────────────


def test_the_right_code_from_the_account_signs_in(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    _room_says(
        mocked_http,
        room_id,
        players=[("ButDoge", False)],
        messages=[("ButDoge", False, f" {code.lower()} ")],
    )

    state = _status(client, claim)

    assert state["status"] == "done"
    user = BonkUser.objects.get(username="ButDoge")
    assert int(client.session["_auth_user_id"]) == user.pk
    player = BonkPlayer.objects.get(username="ButDoge")
    assert BonkAccountLink.objects.filter(user=user, bonk_player=player, active=True).exists()
    closing = [c for c in mocked_http.calls if c.request.url.endswith(f"/rooms/{room_id}/close")]
    assert closing, "the room is closed once proven"


def test_name_matches_ignoring_ascii_case(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http, name="butdoge")
    _room_says(mocked_http, room_id, messages=[("ButDoge", False, code)])

    assert _status(client, claim)["status"] == "done"
    assert BonkUser.objects.filter(username="ButDoge").exists()  # bonk.io's spelling


def test_a_guest_with_the_name_and_the_code_proves_nothing(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    _room_says(mocked_http, room_id, messages=[("ButDoge", True, code)])

    assert _status(client, claim)["status"] == "pending"
    assert not client.session.get("_auth_user_id")


def test_someone_else_typing_the_code_proves_nothing(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    _room_says(mocked_http, room_id, messages=[("Someone", False, code)])

    assert _status(client, claim)["status"] == "pending"


def test_a_lookalike_name_proves_nothing(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http, name="Bossman")
    _room_says(mocked_http, room_id, messages=[("Boſsman", False, code)])

    assert _status(client, claim)["status"] == "pending"


def test_the_right_code_after_three_wrong_ones_is_too_late(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    wrong = [("ButDoge", False, t) for t in ("AAAAAA", "hello", "BBBBBB")]
    _room_says(mocked_http, room_id, messages=wrong + [("ButDoge", False, code)])

    assert _status(client, claim)["status"] == "refused"
    assert not client.session.get("_auth_user_id")


def test_the_right_code_within_three_tries_counts(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    wrong = [("ButDoge", False, t) for t in ("AAAAAA", "BBBBBB")]
    _room_says(mocked_http, room_id, messages=wrong + [("ButDoge", False, code)])

    assert _status(client, claim)["status"] == "done"


def _says(mocked_http, room_id):
    """Mock the room's say route; returns the messages Bonkverse said."""
    mocked_http.add(responses.POST, f"{ROOMBOT}/rooms/{room_id}/say", json={"said": True})
    return lambda: [
        json.loads(call.request.body)["message"]
        for call in mocked_http.calls
        if call.request.url.endswith("/say")
    ]


def test_a_wrong_code_is_answered_at_once_in_the_room_and_on_the_page(client, mocked_http):
    """Owner, 2026-11-27: nothing was said until the third wrong code."""
    claim, code, room_id = _start(client, mocked_http)
    said = _says(mocked_http, room_id)
    _room_says(mocked_http, room_id, messages=[("ButDoge", False, "AAAAAA")])

    state = _status(client, claim)

    assert state["status"] == "pending"
    assert said() == ["That's not the code. 2 tries left."]
    assert "2 tries left" in state["note"]


def test_each_wrong_code_is_answered_once(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    said = _says(mocked_http, room_id)
    _room_says(mocked_http, room_id, messages=[("ButDoge", False, "AAAAAA")])
    _status(client, claim)
    _status(client, claim)  # nothing new typed
    _room_says(mocked_http, room_id, messages=[("ButDoge", False, t) for t in ("AAAAAA", "BBBBBB")])

    state = _status(client, claim)

    assert said() == ["That's not the code. 2 tries left.", "That's not the code. 1 try left."]
    assert "1 try left" in state["note"]


def test_overlapping_polls_answer_a_wrong_code_once(client, mocked_http):
    """Butdoge's review: two polls reading the same old count."""
    claim, code, room_id = _start(client, mocked_http)
    said = _says(mocked_http, room_id)
    _room_says(mocked_http, room_id, messages=[("ButDoge", False, "AAAAAA")])
    stale = LinkClaim.objects.get(pk=claim.pk)
    also_stale = LinkClaim.objects.get(pk=claim.pk)

    room_claims._check_room(stale)
    room_claims._check_room(also_stale)

    assert said() == ["That's not the code. 2 tries left."]
    assert LinkClaim.objects.get(pk=claim.pk).wrong_codes == 1


@pytest.mark.parametrize("trouble", ["409", "500", "down"])
def test_a_room_that_cant_hear_still_counts_the_code(client, mocked_http, trouble):
    claim, code, room_id = _start(client, mocked_http)
    url = f"{ROOMBOT}/rooms/{room_id}/say"
    if trouble == "down":
        mocked_http.add(responses.POST, url, body=requests.ConnectionError())
    else:
        mocked_http.add(responses.POST, url, json={"error": "x"}, status=int(trouble))
    _room_says(mocked_http, room_id, messages=[("ButDoge", False, "AAAAAA")])

    state = _status(client, claim)

    assert state["status"] == "pending"
    assert "2 tries left" in state["note"]
    assert LinkClaim.objects.get(pk=claim.pk).wrong_codes == 1


def test_the_waiting_page_shows_the_note(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    _says(mocked_http, room_id)
    _room_says(mocked_http, room_id, messages=[("ButDoge", False, "AAAAAA")])

    page = client.get(f"/login/room/{claim.pk}/").content.decode()

    assert "A wrong code was typed once. 2 tries left." in page


def test_no_note_before_any_wrong_code(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    _room_says(mocked_http, room_id)

    assert "note" not in _status(client, claim)


def test_three_wrong_codes_and_no_right_one_refuse_the_claim(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    _room_says(
        mocked_http, room_id, messages=[("ButDoge", False, t) for t in ("AAAAAA", "hi", "BBBBBB")]
    )

    state = _status(client, claim)

    assert state["status"] == "refused"
    assert "wrong codes" in state["message"]


def test_another_browser_cant_check_or_finish_it(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    other = type(client)()

    assert other.post(f"/login/room/{claim.pk}/status/").status_code == 403


def test_expires_and_closes_the_room(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    LinkClaim.objects.filter(pk=claim.pk).update(expires_at=timezone.now())

    assert _status(client, claim)["status"] == "expired"
    assert any(c.request.url.endswith("/close") for c in mocked_http.calls)


def test_a_closed_room_ends_the_claim(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    _room_says(mocked_http, room_id, state="closed")

    assert _status(client, claim)["status"] == "expired"


def test_room_service_down_keeps_waiting(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    mocked_http.add(responses.GET, f"{ROOMBOT}/rooms/{room_id}", status=502)

    assert _status(client, claim)["status"] == "pending"


# ── Kept apart from friend requests ──────────────────────────────────


def test_the_friend_request_worker_never_sees_room_code_claims(client, mocked_http):
    """A friend request from the name must never stand in for the code."""
    from accounts import link_claims

    claim, code, room_id = _start(client, mocked_http)

    assert not link_claims._friend_claims().filter(pk=claim.pk).exists()


def test_the_friend_request_status_page_wont_finish_a_room_code_claim(client, mocked_http):
    claim, code, room_id = _start(client, mocked_http)
    LinkClaim.objects.filter(pk=claim.pk).update(status=LinkClaim.PROVEN, bonk_name="ButDoge")
    session = client.session
    session["bv_link_claims"] = [claim.pk]  # as if this browser had a friend claim with this id
    session.save()

    assert client.post(f"/login/friend/{claim.pk}/status/").status_code == 403
    assert not client.session.get("_auth_user_id")
