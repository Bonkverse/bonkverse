"""Signing in with a code typed in a bonk.io room the bot hosts
(accounts/room_claims.py, integrations/roombot.py, ADR 0026; experimental).

The room service (roombot/) is faked over HTTP. A claim is proven only by a
message with this browser's code, typed by the claimed account as bonk.io's
server reports it, and never by a guest.
"""

import datetime
import json
import secrets
import re

import pytest
import requests
import responses
from django.utils import timezone

from accounts import room_claims
from accounts.models import BonkAccountLink, BonkUser, LinkClaim, TrustedDevice, UserEvent
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


def test_it_records_a_room_proof_and_the_level(client, mocked_http):
    from accounts.groups import voting_standing
    from skins.votes import why_cant_vote

    _prove_in_room(client, mocked_http, level=12)

    user = BonkUser.objects.get(username="ButDoge")
    link = BonkAccountLink.objects.get(user=user)
    assert link.room_proven_at is not None and link.room_level == 12
    assert link.password_proven_at is None  # kept apart: a password still beats it
    assert voting_standing(user) == (12, True)
    assert why_cant_vote(user) is None


def test_a_low_level_from_the_room_cant_vote(client, mocked_http):
    from skins.votes import why_cant_vote

    _prove_in_room(client, mocked_http, level=3)

    assert "level 5" in why_cant_vote(BonkUser.objects.get(username="ButDoge"))


def test_no_level_from_the_room_cant_vote_yet(client, mocked_http):
    """Butdoge's review: bonk.io didn't show a level (0), so it's unknown."""
    from skins.votes import why_cant_vote

    _prove_in_room(client, mocked_http, level=0)

    assert "password" in why_cant_vote(BonkUser.objects.get(username="ButDoge"))


def test_the_room_level_never_touches_the_players_xp(client, mocked_http):
    """Other pages show XP; the room's level lives on the link."""
    BonkPlayer.objects.create(username="ButDoge", bonk_id=4242, xp=None)

    _prove_in_room(client, mocked_http, level=12)

    assert BonkPlayer.objects.get(username="ButDoge").xp is None


def test_it_uses_the_player_row_the_account_already_links_to(client, mocked_http):
    """Butdoge's review: older data can hold two rows for one name."""
    owner = UserFactory(username="ButDoge")
    linked = BonkPlayer.objects.create(username="ButDoge", bonk_id=4242)
    BonkPlayer.objects.create(username="butdoge", bonk_id=None)
    BonkAccountLink.objects.create(
        user=owner, bonk_player=linked, active=True, password_proven_at=timezone.now()
    )

    _prove_in_room(client, mocked_http)

    assert BonkAccountLink.objects.filter(user=owner).count() == 1
    assert BonkAccountLink.objects.get(user=owner).room_proven_at is not None


def test_a_staff_name_is_refused_before_a_room_opens(client, mocked_http):
    BonkUser.objects.create_superuser(username="ButDoge", password=secrets.token_urlsafe(16))

    response = client.post("/login/room/", {"username": "butdoge"}, follow=True)

    assert "can&#x27;t be signed in to this way" in response.content.decode()
    assert not LinkClaim.objects.exists()
    assert not [c for c in mocked_http.calls if c.request.url.endswith("/rooms")]


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
        user=account, bonk_player=player, active=True, password_proven_at=timezone.now()
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


# ── Friend requests are gone (2026-11-27) ────────────────────────────


def test_old_friend_request_links_go_to_room_codes(client):
    response = client.get("/login/friend/?username=ButDoge&next=/skins/")

    assert response.status_code == 302
    assert response["Location"].startswith("/login/room/?")
    assert "username=ButDoge" in response["Location"] and "next=%2Fskins%2F" in response["Location"]


def test_an_offsite_next_is_dropped(client):
    response = client.get("/login/friend/?next=https://evil.example/")

    assert "evil" not in response["Location"]


def test_adding_by_friend_request_goes_to_adding_by_room_code(client):
    client.force_login(UserFactory(username="Someone"))

    response = client.get("/login/friend/?add=1")

    assert "add=1" in response["Location"]


def test_an_open_friend_request_page_says_its_gone(client):
    redirect = client.get("/login/friend/12/?next=/skins/")
    page = client.get(redirect["Location"]).content.decode()
    status = client.post("/login/friend/12/status/")

    assert redirect.status_code == 302
    assert redirect["Location"] == "/login/room/?next=%2Fskins%2F"
    assert "replaced by room codes" in page
    assert status.status_code == 410
    assert status.json()["status"] == "refused"
    assert "room code" in status.json()["message"]


def test_the_login_page_offers_room_codes_not_friend_requests(client):
    page = client.get("/login/?other=1").content.decode()

    assert "friend request" not in page.lower()
    assert "with a room code" in page


def _run_migration_0014():
    """Migration 0014's step, against the models as they were at 0013."""
    from importlib import import_module

    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    state = MigrationExecutor(connection).loader.project_state(
        ("accounts", "0013_room_proof_and_claim_level")
    )
    import_module("accounts.migrations.0014_cancel_friend_request_claims").cancel(state.apps, None)


def _came_in_by_friend_request(name, bonk_id):
    """An account a friend request signed in (before 2026-11-27): its link
    has no owner's proof, and a finished friend claim names its bonk.io id."""
    now = timezone.now()
    user = UserFactory(username=name)
    BonkAccountLink.objects.create(
        user=user,
        bonk_player=BonkPlayer.objects.create(username=name, bonk_id=bonk_id),
        active=True,
    )
    LinkClaim.objects.create(
        name=name,
        name_key=name.casefold(),
        method=LinkClaim.FRIEND_REQUEST,
        status=LinkClaim.DONE,
        bonk_id=bonk_id,
        bonk_name=name,
        started_at=now,
        expires_at=now,
    )
    return user


def _retire():
    """`manage.py retire_friend_requests`, run after the deploy."""
    from accounts.retire_friend_requests import retire

    return retire()


def _friend_claim(name, status):
    now = timezone.now()
    return LinkClaim.objects.create(
        name=name,
        name_key=name.casefold(),
        method=LinkClaim.FRIEND_REQUEST,
        status=status,
        started_at=now,
        expires_at=now + datetime.timedelta(minutes=5),
    )


def test_waiting_and_proven_friend_claims_are_cancelled_by_the_migration():
    waiting = _friend_claim("ButDoge", LinkClaim.PENDING)
    proven = _friend_claim("Other", LinkClaim.PROVEN)
    finished = _friend_claim("Third", LinkClaim.DONE)

    _run_migration_0014()

    for claim in (waiting, proven, finished):
        claim.refresh_from_db()
    assert waiting.status == proven.status == LinkClaim.REFUSED
    assert "room codes" in waiting.problem
    assert finished.status == LinkClaim.DONE


def test_retiring_signs_friend_request_only_accounts_out(client):
    """Whoever got in by friend request doesn't keep the account."""
    from django.test import Client

    friend_only = _came_in_by_friend_request("ByFriend", 1)
    owner = _password_proven("ByPassword", 2)
    theirs, mine = Client(), Client()
    theirs.force_login(friend_only)
    mine.force_login(owner)

    _retire()

    assert theirs.get("/api/me/").status_code == 401
    assert mine.get("/api/me/").status_code == 200


def test_retiring_takes_friend_only_accounts_out_of_groups(client):
    """A claimer who grouped the account under their main mustn't get it
    back by signing in as that main (butdoge's review)."""
    from accounts import groups

    claimed = _came_in_by_friend_request("ByFriend", 1)
    mallory_main = _password_proven("MalloryMain", 9)
    groups.join(mallory_main, claimed)
    owners_alt = _password_proven("OwnersAlt", 3)
    groups.join(_password_proven("OwnersMain", 4), owners_alt)

    counts = _retire()

    claimed.refresh_from_db()
    owners_alt.refresh_from_db()
    assert claimed.account_group_id is None
    assert owners_alt.account_group_id is not None
    assert counts["taken_out_of_groups"] == 1


def test_it_ends_a_session_holding_the_account_as_an_unlocked_alt():
    from django.contrib.sessions.backends.db import SessionStore

    from accounts import groups

    claimed = _came_in_by_friend_request("ByFriend", 1)
    other = SessionStore()
    other["_auth_user_id"] = "999999"
    other[groups.UNLOCKED_KEY] = [claimed.pk]
    other.create()

    _retire()

    assert not SessionStore().exists(other.session_key)


def test_running_it_again_is_harmless():
    from django.core.management import call_command

    _retire()
    call_command("retire_friend_requests", stdout=__import__("io").StringIO())


def test_retiring_ends_one_click_for_friend_request_only_accounts():
    from accounts.models import RememberedSignIn

    friend_only = _came_in_by_friend_request("ByFriend", 1)
    owner = _password_proven("ByPassword", 2)
    for user in (friend_only, owner):
        RememberedSignIn.objects.create(
            user=user, device_hash="d" * 64, label="x", proven_at=timezone.now()
        )

    _retire()

    assert not RememberedSignIn.objects.filter(user=friend_only).exists()
    assert RememberedSignIn.objects.filter(user=owner).exists()


def test_a_password_takes_back_an_account_a_friend_request_claimed(
    client, mocked_http, django_capture_on_commit_callbacks
):
    """Friend requests are gone, but accounts claimed that way stay; the
    owner's password still takes one back (ADR 0024)."""
    from django.test import Client

    from accounts import groups

    claimed = _came_in_by_friend_request("TestPlayer", 1234567)
    groups.join(UserFactory(username="MalloryMain"), claimed)
    mallory = Client()
    mallory.force_login(claimed)

    with django_capture_on_commit_callbacks(execute=True):
        _password_login(client, mocked_http)

    claimed.refresh_from_db()
    assert claimed.account_group_id is None
    assert mallory.get("/api/me/").status_code == 401


def test_a_friend_request_only_account_cant_vote_yet():
    from skins.votes import why_cant_vote

    account = _came_in_by_friend_request("ByFriend", 7)

    assert "password" in why_cant_vote(account)


# ── A relayed code (butdoge's reviews of #197) ──────────────────────────
# A code proves the named account typed it, not that the browser that asked
# is theirs: Mallory can talk the owner into typing her code. So on an
# account that has used its password a code opens only that account, and the
# owner's password always takes it back (owner, 2026-11-27).


def _password_proven(name="ButDoge", bonk_id=4242, *, days_ago=3, **link):
    account = UserFactory(username=name)
    player = BonkPlayer.objects.create(username=name, bonk_id=bonk_id)
    BonkAccountLink.objects.create(
        user=account,
        bonk_player=player,
        active=True,
        password_proven_at=timezone.now() - datetime.timedelta(days=days_ago),
        **link,
    )
    return account


def _password_login(client, mocked_http):
    from tests.conftest import load_bonk_fixture

    # login_success is TestPlayer, bonk.io id 1234567.
    mocked_http.post(
        "https://bonk2.io/scripts/login_legacy.php", json=load_bonk_fixture("login_success")
    )
    return client.post("/login/", {"username": "TestPlayer", "password": "hunter2"})


def test_on_a_password_proven_main_a_code_opens_only_that_account(client, mocked_http):
    from accounts import groups

    main = _password_proven()
    alt = UserFactory(username="ButDogeAlt")
    groups.join(main, alt)
    main.refresh_from_db()

    assert _prove_in_room(client, mocked_http)["status"] == "done"

    assert alt.pk not in client.session.get(groups.UNLOCKED_KEY, [])
    assert not TrustedDevice.objects.filter(group_id=main.account_group_id).exists()
    assert client.get("/api/me/").json()["user"]["username"] == "ButDoge"


def test_a_code_never_unlocks_but_one_that_never_used_a_password_still_does(client, mocked_http):
    """Owner's choice: the limit is only for accounts that have used their
    password; a room-code-only main unlocks its group as before."""
    from accounts import groups

    main = UserFactory(username="ButDoge")
    player = BonkPlayer.objects.create(username="ButDoge", bonk_id=None)
    BonkAccountLink.objects.create(
        user=main, bonk_player=player, active=True, room_proven_at=timezone.now()
    )
    alt = UserFactory(username="ButDogeAlt")
    groups.join(main, alt)

    _prove_in_room(client, mocked_http)

    assert alt.pk in client.session.get(groups.UNLOCKED_KEY, [])


def test_a_code_cant_add_a_password_proven_account(client, mocked_http):
    _password_proven()
    me = UserFactory(username="Mallory")
    client.force_login(me)

    response = client.post("/login/room/?add=1", {"username": "ButDoge"}, follow=True)

    assert "Add it with its bonk.io password" in response.content.decode()
    assert not LinkClaim.objects.exists()


def test_add_refused_at_the_finish_if_the_password_was_used_meanwhile(client, mocked_http):
    """The check runs again when the code is typed (finish path)."""
    from accounts import groups

    me = UserFactory(username="Mallory")
    client.force_login(me)
    room_id = _room_opens(mocked_http)
    client.post("/login/room/?add=1", {"username": "ButDoge"})
    claim = LinkClaim.objects.get(method=LinkClaim.ROOM_CODE)
    code = client.session[room_claims.SESSION_KEY][str(claim.pk)]
    owner = _password_proven()  # the owner signs in with the password meanwhile
    _room_says(
        mocked_http, room_id, players=[("ButDoge", False)], messages=[("ButDoge", False, code)]
    )

    reply = client.post(f"/login/room/{claim.pk}/status/")

    assert reply.status_code == 403
    assert "password" in reply.json()["message"]
    owner.refresh_from_db()
    assert owner.account_group_id is None or not groups.same_group(owner, me)


def test_a_staff_name_at_the_finish_is_refused_with_a_message(client, mocked_http):
    import secrets

    claim, code, room_id = _start(client, mocked_http)
    BonkUser.objects.create_superuser(username="ButDoge", password=secrets.token_urlsafe(16))
    _room_says(
        mocked_http, room_id, players=[("ButDoge", False)], messages=[("ButDoge", False, code)]
    )

    reply = client.post(f"/login/room/{claim.pk}/status/")

    assert reply.status_code == 403
    assert "can't be signed in to this way" in reply.json()["message"]
    assert "_auth_user_id" not in client.session


def test_a_password_ends_a_relayed_codes_session_and_keeps_the_group(
    client, mocked_http, django_capture_on_commit_callbacks
):
    """Mallory gets a password-proven account's code typed for her: she's
    signed in to that one account. The owner's next password ends her hold
    and leaves the account in the owner's own group."""
    from django.test import Client

    from accounts import groups

    owner = _password_proven("TestPlayer", 1234567)
    groups.join(UserFactory(username="OwnersMain"), owner)
    group_id = BonkUser.objects.get(pk=owner.pk).account_group_id
    mallory = Client()
    assert _prove_in_room(mallory, mocked_http, name="TestPlayer")["status"] == "done"

    with django_capture_on_commit_callbacks(execute=True):
        _password_login(client, mocked_http)

    owner.refresh_from_db()
    assert owner.account_group_id == group_id
    assert mallory.get("/api/me/").status_code == 401
    assert client.get("/api/me/").json()["user"]["username"] == "TestPlayer"


def test_a_password_takes_back_a_code_only_account_pulled_into_another_group(
    client, mocked_http, django_capture_on_commit_callbacks
):
    """An account that never used its password: a relayed code can add it to
    Mallory's group (full powers). The owner's password takes it out."""
    from django.test import Client

    owner = UserFactory(username="TestPlayer")
    row = BonkPlayer.objects.create(username="TestPlayer", bonk_id=None)  # a room proves names only
    BonkAccountLink.objects.create(
        user=owner,
        bonk_player=row,
        active=True,
        room_proven_at=timezone.now() - datetime.timedelta(days=2),
    )
    mallory = Client()
    mallory.force_login(UserFactory(username="MalloryMain"))
    _room_opens(mocked_http)
    mallory.post("/login/room/?add=1", {"username": "TestPlayer"})
    claim = LinkClaim.objects.get(method=LinkClaim.ROOM_CODE)
    code = mallory.session[room_claims.SESSION_KEY][str(claim.pk)]
    _room_says(
        mocked_http,
        claim.room_id,
        players=[("TestPlayer", False)],
        messages=[("TestPlayer", False, code)],
    )
    assert mallory.post(f"/login/room/{claim.pk}/status/").json()["status"] == "done"
    owner.refresh_from_db()
    assert owner.account_group_id is not None  # moved into Mallory's group

    with django_capture_on_commit_callbacks(execute=True):
        _password_login(client, mocked_http)  # also finds the id-less row by name

    owner.refresh_from_db()
    assert owner.account_group_id is None
    assert UserEvent.objects.filter(user=owner, event_type="account_reclaimed_by_password").exists()


def test_two_links_for_one_name_are_compared_together(
    client, mocked_http, django_capture_on_commit_callbacks
):
    """Older data: a clean password link and a newer room-code link on
    another row for the same name. The newest room proof wins the compare."""
    from django.test import Client

    owner = _password_proven("TestPlayer", 1234567)
    other_row = BonkPlayer.objects.create(username="testplayer", bonk_id=None)
    BonkAccountLink.objects.create(
        user=owner, bonk_player=other_row, active=True, room_proven_at=timezone.now()
    )
    mallory = Client()
    mallory.force_login(owner)

    with django_capture_on_commit_callbacks(execute=True):
        _password_login(client, mocked_http)

    assert mallory.get("/api/me/").status_code == 401


def test_a_room_code_cant_take_back_a_password_proven_account(client, mocked_http):
    from django.test import Client

    from accounts import groups

    owner = _password_proven()
    groups.join(UserFactory(username="MainOne"), owner)
    other = Client()
    other.force_login(owner)

    _prove_in_room(client, mocked_http)

    owner.refresh_from_db()
    assert owner.account_group_id is not None
    assert other.get("/api/me/").status_code == 200


def test_a_password_after_the_last_room_code_keeps_everything(client, mocked_http):
    from django.test import Client

    from accounts import groups

    owner = _password_proven("TestPlayer", 1234567, days_ago=0)
    BonkAccountLink.objects.filter(user=owner).update(
        room_proven_at=timezone.now() - datetime.timedelta(days=1)
    )
    groups.join(UserFactory(username="MainOne"), owner)
    other = Client()
    other.force_login(owner)

    _password_login(client, mocked_http)

    owner.refresh_from_db()
    assert owner.account_group_id is not None
    assert other.get("/api/me/").status_code == 200


# ── Butdoge's review of 7f8a64c ──────────────────────────────────────


def test_a_disconnected_link_still_counts_as_having_used_the_password(client, mocked_http):
    """An inactive link keeps its password proof: the limit still applies."""
    from accounts import groups

    main = _password_proven()
    BonkAccountLink.objects.filter(user=main).update(active=False)
    alt = UserFactory(username="ButDogeAlt")
    groups.join(main, alt)

    assert _prove_in_room(client, mocked_http)["status"] == "done"

    assert alt.pk not in client.session.get(groups.UNLOCKED_KEY, [])
    assert main.pk in client.session.get(groups.CODE_ONLY_KEY, [])


def test_a_linked_staff_account_cant_use_a_room_code(client, mocked_http):
    """A room proves only the name, which can change hands on bonk.io."""
    staff = UserFactory(username="ButDoge", is_staff=True)
    row = BonkPlayer.objects.create(username="ButDoge", bonk_id=4242)
    BonkAccountLink.objects.create(user=staff, bonk_player=row, active=True)

    response = client.post("/login/room/", {"username": "ButDoge"}, follow=True)

    assert "can&#x27;t be signed in to this way" in response.content.decode()
    assert not LinkClaim.objects.exists()


def test_a_code_only_main_isnt_the_main_signed_in_here(client, mocked_http):
    """Removing accounts, "apply to all" and trusted browsers need the main
    signed in here; a relayed code mustn't pass for it."""
    from accounts import groups

    main = _password_proven()
    alt = UserFactory(username="ButDogeAlt")
    groups.join(main, alt)
    _prove_in_room(client, mocked_http)

    client.post("/accounts/remove/", {"account": alt.pk})

    alt.refresh_from_db()
    assert alt.account_group_id == BonkUser.objects.get(pk=main.pk).account_group_id


def test_a_code_only_account_cant_take_others_into_its_group(client, mocked_http):
    """Signed in to the owner's main by a relayed code, Mallory adds her
    own account with its password: it doesn't join the owner's group."""
    from tests.conftest import load_bonk_fixture

    main = _password_proven()
    _prove_in_room(client, mocked_http)
    mocked_http.post(
        "https://bonk2.io/scripts/login_legacy.php", json=load_bonk_fixture("login_success")
    )

    client.post("/login/?add=1", {"username": "TestPlayer", "password": "hunter2"})

    mallory = BonkUser.objects.get(username="TestPlayer")
    main.refresh_from_db()
    assert mallory.account_group_id is None or mallory.account_group_id != main.account_group_id


def test_a_limited_code_sign_in_leaves_no_one_click(client, mocked_http):
    """One click would come back with full powers."""
    from accounts.models import RememberedSignIn

    main = _password_proven()
    _prove_in_room(client, mocked_http)

    assert not RememberedSignIn.objects.filter(user=main).exists()


def test_a_row_with_another_bonk_id_isnt_this_account(
    client, mocked_http, django_capture_on_commit_callbacks
):
    """A stale row for a name that changed hands on bonk.io can't lend its
    password proof to the new owner's account."""
    from django.test import Client

    account = UserFactory(username="TestPlayer")
    stale = BonkPlayer.objects.create(username="TestPlayer", bonk_id=999)
    BonkAccountLink.objects.create(
        user=account, bonk_player=stale, active=True, password_proven_at=timezone.now()
    )
    code_row = BonkPlayer.objects.create(username="testplayer", bonk_id=None)
    BonkAccountLink.objects.create(
        user=account, bonk_player=code_row, active=True, room_proven_at=timezone.now()
    )
    other = Client()
    other.force_login(account)

    with django_capture_on_commit_callbacks(execute=True):
        _password_login(client, mocked_http)  # TestPlayer is id 1234567

    assert other.get("/api/me/").status_code == 401  # the code-only hold ended


# ── Butdoge's review of fac12f3 ──────────────────────────────────────


def test_a_code_doesnt_undo_a_disconnect(client, mocked_http):
    account = _password_proven()
    BonkAccountLink.objects.filter(user=account).update(active=False)

    _prove_in_room(client, mocked_http)

    link = BonkAccountLink.objects.get(user=account)
    assert link.active is False and link.room_proven_at is not None


def test_a_refused_claim_ends_refused(client, mocked_http):
    import secrets

    claim, code, room_id = _start(client, mocked_http)
    BonkUser.objects.create_superuser(username="ButDoge", password=secrets.token_urlsafe(16))
    _room_says(
        mocked_http, room_id, players=[("ButDoge", False)], messages=[("ButDoge", False, code)]
    )
    client.post(f"/login/room/{claim.pk}/status/")

    claim.refresh_from_db()
    assert claim.status == LinkClaim.REFUSED


def test_your_own_code_on_a_password_browser_keeps_main_powers(client, mocked_http):
    """The owner, signed in with the password here, types a code here too:
    this browser stays the main's."""
    from accounts import groups

    main = _password_proven()
    alt = UserFactory(username="ButDogeAlt")
    groups.join(main, alt)
    client.force_login(main)
    session = client.session
    session[groups.SIGNED_IN_KEY] = [main.pk]
    session.save()

    _prove_in_room(client, mocked_http)

    assert main.pk not in client.session.get(groups.CODE_ONLY_KEY, [])


def test_on_the_groups_own_browser_a_password_keeps_the_alt_in_its_group(client, mocked_http):
    """The owner signing in to their own alt where the main is signed in:
    nothing to take back (sign_in._reclaim's own-browser exception)."""
    from accounts import groups

    main = _password_proven("OwnersMain", 77)
    alt = _came_in_by_friend_request("TestPlayer", 1234567)
    groups.join(main, alt)
    client.force_login(main)
    session = client.session
    session[groups.SIGNED_IN_KEY] = [main.pk]
    session.save()

    _password_login(client, mocked_http)

    alt.refresh_from_db()
    assert alt.account_group_id == BonkUser.objects.get(pk=main.pk).account_group_id


def test_it_matches_session_lists_holding_ids_as_text():
    """However a browser's lists stored the id, the session ends."""
    from django.contrib.sessions.backends.db import SessionStore

    from accounts import groups

    claimed = _came_in_by_friend_request("ByFriend", 1)
    other = SessionStore()
    other[groups.SIGNED_IN_KEY] = [str(claimed.pk)]
    other.create()

    _retire()

    assert not SessionStore().exists(other.session_key)


def test_with_room_codes_off_old_links_and_the_chooser_use_the_password(client, settings):
    settings.ROOMBOT_URL = ""

    response = client.get("/login/friend/?username=ByFriend")

    assert response["Location"].startswith("/login/?")


def test_a_trusted_browser_keeps_the_alt_in_its_group(client, mocked_http):
    """_reclaim's other exception: a browser the group trusts."""
    from accounts import devices, groups

    main = _password_proven("OwnersMain", 77)
    alt = _came_in_by_friend_request("TestPlayer", 1234567)
    groups.join(main, alt)
    main.refresh_from_db()
    from django.core.signing import get_cookie_signer
    from django.test import RequestFactory

    request = RequestFactory().get("/")
    request.bv_device = "this-browser-device-id"
    devices.trust(request, main.account_group)
    signer = get_cookie_signer(salt=devices.COOKIE + devices.COOKIE_SALT)
    client.cookies[devices.COOKIE] = signer.sign(request.bv_device)

    _password_login(client, mocked_http)

    alt.refresh_from_db()
    assert alt.account_group_id == main.account_group_id


def test_two_retired_accounts_in_one_group_including_its_main():
    """take_out re-reads each account; the second isn't handled from stale data."""
    from accounts import groups

    claimer_main = _came_in_by_friend_request("ClaimedMain", 11)
    claimed_alt = _came_in_by_friend_request("ClaimedAlt", 12)
    keeper = _password_proven("KeeperAlt", 13)
    groups.join(claimer_main, claimed_alt)
    groups.join(claimer_main, keeper)

    counts = _retire()

    for user in (claimer_main, claimed_alt, keeper):
        user.refresh_from_db()
    assert claimer_main.account_group_id is None and claimed_alt.account_group_id is None
    assert counts["taken_out_of_groups"] == 2


def test_with_room_codes_off_the_chooser_uses_the_password(client, settings):
    import json
    import time

    from django.core.signing import get_cookie_signer

    from accounts import known_accounts

    settings.ROOMBOT_URL = ""
    known = [{"u": "ByFriend", "via": known_accounts.FRIEND_REQUEST, "at": int(time.time())}]
    signer = get_cookie_signer(salt=known_accounts.COOKIE + known_accounts.COOKIE_SALT)
    client.cookies[known_accounts.COOKIE] = signer.sign(json.dumps(known))

    page = client.get("/login/").content.decode()

    assert "/login/?username=ByFriend" in page and "With your password" in page


def test_a_link_without_proof_or_friend_claim_is_left_alone(client):
    """Only accounts a friend request actually brought in are retired."""
    from django.test import Client

    other = UserFactory(username="NoClaimBehindIt")
    BonkAccountLink.objects.create(
        user=other,
        bonk_player=BonkPlayer.objects.create(username="NoClaimBehindIt", bonk_id=21),
        active=True,
    )
    browser = Client()
    browser.force_login(other)

    assert _retire()["accounts"] == 0
    assert browser.get("/api/me/").status_code == 200


def test_a_dry_run_changes_nothing(client):
    from django.test import Client

    from accounts.retire_friend_requests import retire

    claimed = _came_in_by_friend_request("ByFriend", 1)
    browser = Client()
    browser.force_login(claimed)

    counts = retire(dry_run=True)

    assert counts["accounts"] == 1 and counts["sessions"] == 1
    assert browser.get("/api/me/").status_code == 200


def test_retiring_forgets_browsers_trusted_for_a_claimers_group():
    """A friend-request sign-in to a main trusted that browser for the group."""
    from accounts import groups

    claimed_main = _came_in_by_friend_request("ClaimedMain", 31)
    keeper = _password_proven("KeeperAlt", 32)
    groups.join(claimed_main, keeper)
    claimed_main.refresh_from_db()
    TrustedDevice.objects.create(
        group_id=claimed_main.account_group_id,
        device_hash="c" * 64,
        label="claimer's browser",
        last_used_at=timezone.now(),
    )

    counts = _retire()

    assert not TrustedDevice.objects.exists()
    assert counts["trusted_browsers_forgotten"] == 1


def test_it_refuses_to_run_on_other_session_engines(settings):
    from accounts.retire_friend_requests import retire

    settings.SESSION_ENGINE = "django.contrib.sessions.backends.cache"

    with pytest.raises(RuntimeError):
        retire(dry_run=True)
