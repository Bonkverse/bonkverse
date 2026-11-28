"""Signing in, or adding an account, with a friend request (accounts/
link_claims.py, accounts/bot_account.py; RFC-0003 phase 6).

The person names a bonk.io account; within 10 minutes a friend request from
it to the bot's account proves it. The worker reads the bot's requests only
while a claim is pending; the browser that made the claim finishes it.
"""

import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils import timezone

from accounts import bot_account, groups, link_claims
from accounts.models import BonkAccountLink, BonkUser, LinkClaim
from integrations.bonk_api import LOGIN_SCRIPT, rate_limit_cooldowns
from skins.votes import why_cant_vote
from tests.conftest import load_bonk_fixture, make_bonk_token
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

FRIENDS_URL = "https://bonk2.io/scripts/friends.php"
LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
LOGIN_AUTO_URL = "https://bonk2.io/scripts/login_auto.php"
EASTERN = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def bot(settings):
    settings.BONK_BOT_USERNAME = "Bonkverse Bot"
    settings.BONK_BOT_PASSWORD = "bot-password"
    cache.delete_many(["bonk_bot:token", "bonk_bot:remember", "bonk_bot:password_hold"])


@pytest.fixture
def bot_signed_in(monkeypatch):
    monkeypatch.setattr(bot_account, "token", lambda: "bot-token")


def _eastern(moment: datetime) -> str:
    return moment.astimezone(EASTERN).strftime("%Y-%m-%d %H:%M:%S")


def _friends_answer(*requests):
    """friends.php's answer with `requests`: (bonk_id, name, sent_at)."""
    return {
        "r": "success",
        "friends": [],
        "requests": [{"id": i, "name": n, "date": _eastern(t)} for i, n, t in requests],
    }


def _form(call) -> dict:
    return {k: v[0] for k, v in parse_qs(call.request.body).items()}


def _start(client, name="AltOne", **extra):
    response = client.post("/login/friend/", {"username": name, **extra})
    assert response.status_code == 302, response.content
    return LinkClaim.objects.latest("pk")


def _status(client, claim):
    return client.post(f"/login/friend/{claim.pk}/status/").json()


class TestMatching:
    def _claim(self, name, started):
        return LinkClaim(
            pk=hash((name, started)) % 10_000,
            name=name,
            name_key=link_claims.name_key(name),
            purpose=LinkClaim.SIGN_IN,
            started_at=started,
            expires_at=started + timedelta(minutes=10),
        )

    def test_a_request_sent_after_the_claim_proves_it_ignoring_case(self):
        now = timezone.now()
        claim = self._claim("The Saucy Tulip", now - timedelta(minutes=2))
        request = link_claims.Request(42, "the saucy tulip", now - timedelta(minutes=1))

        proofs, refused, delete = link_claims.match([claim], [request], now)

        assert proofs == [(claim, request)]
        assert refused == [] and delete == [42]

    def test_spaces_count(self):
        now = timezone.now()
        claim = self._claim("Saucy Tulip", now - timedelta(minutes=2))
        request = link_claims.Request(42, "SaucyTulip", now)

        assert link_claims.match([claim], [request], now)[0] == []

    def test_a_request_from_before_the_claim_proves_nothing(self):
        now = timezone.now()
        claim = self._claim("AltOne", now - timedelta(minutes=1))
        old = link_claims.Request(42, "AltOne", now - timedelta(minutes=5))

        proofs, _, delete = link_claims.match([claim], [old], now)

        assert proofs == [] and delete == []

    def test_two_claims_for_one_name_are_both_refused(self):
        now = timezone.now()
        first = self._claim("AltOne", now - timedelta(minutes=3))
        second = self._claim("altone", now - timedelta(minutes=2))
        request = link_claims.Request(42, "AltOne", now)

        proofs, refused, delete = link_claims.match([first, second], [request], now)

        assert proofs == []
        assert set(refused) == {first.pk, second.pk}
        assert delete == [42]

    def test_fresh_requests_meant_for_someone_else_are_left_alone(self):
        """BonxBot checks the same bot account until phase 7."""
        now = timezone.now()
        claim = self._claim("AltOne", now - timedelta(minutes=1))
        fresh = link_claims.Request(7, "Somebody Else", now - timedelta(minutes=2))
        stale = link_claims.Request(8, "Long Gone", now - timedelta(minutes=12))

        _, _, delete = link_claims.match([claim], [fresh, stale], now)

        assert delete == [8]

    def test_request_dates_are_us_eastern(self):
        assert link_claims.request_time("2026-11-24 12:00:00") == datetime(
            2026, 11, 24, 17, 0, tzinfo=ZoneInfo("UTC")
        )
        assert link_claims.request_time("not a date") is None


class TestStarting:
    def test_starts_a_claim_and_shows_the_bot_name(self, client):
        response = client.post("/login/friend/", {"username": "AltOne"}, follow=True)

        claim = LinkClaim.objects.get()
        assert (claim.name, claim.purpose, claim.status) == ("AltOne", "sign_in", "pending")
        page = response.content.decode()
        assert "Bonkverse Bot" in page and "AltOne" in page

    def test_off_until_the_bot_is_set_up(self, client, settings):
        settings.BONK_BOT_PASSWORD = ""

        client.post("/login/friend/", {"username": "AltOne"})

        assert not LinkClaim.objects.exists()

    def test_the_login_page_offers_it_only_when_set_up(self, client, settings):
        assert "with a friend request instead" in client.get("/login/").content.decode()
        settings.BONK_BOT_USERNAME = ""
        assert "with a friend request instead" not in client.get("/login/").content.decode()

    def test_a_name_can_be_tried_only_a_few_times_an_hour(self, client):
        for _ in range(link_claims.CLAIMS_PER_NAME_PER_HOUR):
            _start(client)

        client.post("/login/friend/", {"username": "altone"})

        assert LinkClaim.objects.count() == link_claims.CLAIMS_PER_NAME_PER_HOUR


class TestTheWorkerCheck:
    def test_nothing_pending_calls_nothing(self, mocked_http, bot_signed_in):
        assert link_claims.check_pending() == {"pending": 0, "expired": 0}
        assert len(mocked_http.calls) == 0

    def test_a_matching_request_proves_the_claim_and_is_deleted(
        self, client, mocked_http, bot_signed_in
    ):
        claim = _start(client)
        friends = mocked_http.post(
            FRIENDS_URL, json=_friends_answer((555, "AltOne", timezone.now()))
        )
        delete = mocked_http.post(FRIENDS_URL, json={"r": "success"})

        counts = link_claims.check_pending()

        claim.refresh_from_db()
        assert (claim.status, claim.bonk_id, claim.bonk_name) == ("proven", 555, "AltOne")
        assert counts["proven"] == 1
        assert _form(friends.calls[0]) == {"token": "bot-token", "task": "getfriends"}
        assert _form(delete.calls[0]) == {
            "token": "bot-token",
            "task": "deleterequest",
            "theirid": "555",
        }

    def test_overdue_claims_expire(self, client, mocked_http, bot_signed_in):
        claim = _start(client)
        LinkClaim.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        link_claims.check_pending()

        claim.refresh_from_db()
        assert claim.status == "expired"
        assert len(mocked_http.calls) == 0


class TestFinishing:
    def _prove(self, claim, bonk_id=555, name="AltOne"):
        LinkClaim.objects.filter(pk=claim.pk).update(
            status=LinkClaim.PROVEN, bonk_id=bonk_id, bonk_name=name, proven_at=timezone.now()
        )

    def test_pending_says_how_long_is_left(self, client):
        claim = _start(client)

        state = _status(client, claim)

        assert state["status"] == "pending" and 590 < state["seconds_left"] <= 600

    def test_proven_signs_in_without_a_password(self, client):
        claim = _start(client)
        self._prove(claim)

        state = _status(client, claim)

        assert state["status"] == "done"
        assert client.get("/api/me/").json()["user"]["username"] == "AltOne"
        link = BonkAccountLink.objects.get(user__username="AltOne")
        assert link.bonk_player.bonk_id == 555
        assert link.token_encrypted is None and link.owner_proven_at is None
        assert client.session["bonk_user_id"] == 555

    def test_finishes_only_once(self, client):
        claim = _start(client)
        self._prove(claim)
        _status(client, claim)

        assert _status(client, claim)["status"] == "done"
        assert LinkClaim.objects.get(pk=claim.pk).status == "done"

    def test_only_the_browser_that_started_it_can_finish_it(self, client):
        from django.test import Client

        claim = _start(client)
        self._prove(claim)
        other = Client()

        response = other.post(f"/login/friend/{claim.pk}/status/")

        assert response.status_code == 403
        assert other.get("/api/me/").status_code == 401

    def test_adding_joins_the_signed_in_persons_accounts(self, client):
        main = UserFactory(username="MainOne")
        client.force_login(main)
        claim = _start(client, add="1")
        self._prove(claim)

        _status(client, claim)

        alt = BonkUser.objects.get(username="AltOne")
        main.refresh_from_db()
        assert alt.account_group_id == main.account_group_id is not None
        assert client.get("/api/me/").json()["user"]["username"] == "AltOne"
        assert {r["username"] for r in client.get("/api/me/").json()["accounts"]} == {
            "MainOne",
            "AltOne",
        }

    def test_an_account_owned_since_the_claim_started_is_refused(self, client):
        claim = _start(client, name="MainOne")
        UserFactory(username="MainOne")  # signed in with its password meanwhile
        self._prove(claim, bonk_id=777, name="MainOne")

        state = _status(client, claim)

        assert state["status"] == "refused" and "already on Bonkverse" in state["message"]
        assert client.get("/api/me/").status_code == 401

    def test_expired_says_so(self, client):
        claim = _start(client)
        LinkClaim.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        state = _status(client, claim)

        assert state["status"] == "expired" and "AltOne" in state["message"]


class TestVotingNeedsOnePasswordLogin:
    def test_a_friend_request_only_account_cant_vote_yet(self, client):
        claim = _start(client)
        LinkClaim.objects.filter(pk=claim.pk).update(
            status=LinkClaim.PROVEN, bonk_id=555, bonk_name="AltOne"
        )
        _status(client, claim)

        reason = why_cant_vote(BonkUser.objects.get(username="AltOne"))

        assert reason and "password" in reason

    def test_after_a_password_login_it_can(self, client, mocked_http):
        claim = _start(client, name="TestPlayer")
        LinkClaim.objects.filter(pk=claim.pk).update(
            status=LinkClaim.PROVEN, bonk_id=1234567, bonk_name="TestPlayer"
        )
        _status(client, claim)
        mocked_http.post(LOGIN_URL, json=load_bonk_fixture("login_success"))

        client.post("/login/", {"username": "TestPlayer", "password": "pw"})

        assert why_cant_vote(BonkUser.objects.get(username="TestPlayer")) is None


class TestBotSession:
    def test_first_login_keeps_a_remember_me_token(self, mocked_http):
        answer = load_bonk_fixture("login_success")
        answer["token"] = make_bonk_token(exp=time.time() + 86400)
        answer["rememberToken"] = "r" * 77
        login = mocked_http.post(LOGIN_URL, json=answer)

        assert bot_account.token() == answer["token"]
        assert bot_account.token() == answer["token"]  # kept, not logged in again

        assert len(login.calls) == 1
        assert _form(login.calls[0])["remember"] == "true"

    def test_later_sessions_come_from_remember_me_not_the_password(self, mocked_http):
        answer = load_bonk_fixture("login_success")
        answer["token"] = make_bonk_token(exp=time.time() + 86400)
        answer["rememberToken"] = "r" * 77
        mocked_http.post(LOGIN_URL, json=answer)
        bot_account.token()
        bot_account.forget_token()
        auto = load_bonk_fixture("login_auto_success")
        auto["token"] = make_bonk_token(exp=time.time() + 86400)
        refresh = mocked_http.post(LOGIN_AUTO_URL, json=auto)

        assert bot_account.token() == auto["token"]
        assert len(refresh.calls) == 1

    def test_a_wrong_bot_password_isnt_retried_for_a_while(self, mocked_http):
        login = mocked_http.post(LOGIN_URL, json={"r": "fail", "e": "password"})

        assert bot_account.token() is None
        assert bot_account.token() is None

        assert len(login.calls) == 1

    def test_tokens_are_kept_encrypted(self, mocked_http):
        answer = load_bonk_fixture("login_success")
        answer["token"] = make_bonk_token(exp=time.time() + 86400)
        answer["rememberToken"] = "r" * 77
        mocked_http.post(LOGIN_URL, json=answer)

        bot_account.token()

        assert cache.get("bonk_bot:remember") != "r" * 77
        assert cache.get("bonk_bot:token") != answer["token"]


class TestDuringABonkPause:
    """bonk.io pausing Bonkverse's calls (integrations/bonk_api.py) stops the
    worker reading the bot's requests. Claims wait it out instead of running
    out, and the waiting page says why (2026-11-24: a claim expired while a
    login pause blocked every check)."""

    @pytest.fixture
    def paused(self):
        rate_limit_cooldowns.for_script(LOGIN_SCRIPT).start(600)
        return 600

    def test_cannot_start_a_claim_during_a_pause(self, client, paused):
        response = client.post("/login/friend/", {"username": "AltOne"}, follow=True)

        assert not LinkClaim.objects.exists()
        assert "pausing" in response.content.decode()

    def test_the_worker_holds_claims_through_a_pause(self, client, mocked_http, bot_signed_in):
        claim = _start(client)
        rate_limit_cooldowns.for_script(LOGIN_SCRIPT).start(600)
        LinkClaim.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

        counts = link_claims.check_pending()

        claim.refresh_from_db()
        assert counts["skipped"] == "paused" and counts["pending"] == 1
        assert claim.status == "pending"
        assert claim.expires_at >= timezone.now() + timedelta(seconds=600) + timedelta(minutes=4)
        assert len(mocked_http.calls) == 0

    def test_the_waiting_page_says_when_checks_resume(self, client):
        claim = _start(client)
        rate_limit_cooldowns.for_script(LOGIN_SCRIPT).start(300)
        LinkClaim.objects.update(expires_at=timezone.now() + timedelta(seconds=30))

        state = _status(client, claim)
        page = client.get(f"/login/friend/{claim.pk}/").content.decode()

        assert state["status"] == "pending"
        assert 295 <= state["paused"] <= 300
        assert state["seconds_left"] > 300
        assert "checking resumes" in page and 'data-paused="' in page

    def test_a_request_sent_before_the_pause_still_proves_it(
        self, client, mocked_http, bot_signed_in
    ):
        claim = _start(client)
        sent = timezone.now()
        # The pause ran past the claim's first 10 minutes, then ended.
        LinkClaim.objects.update(
            started_at=sent - timedelta(minutes=20),
            expires_at=timezone.now() + timedelta(minutes=4),
        )
        mocked_http.post(FRIENDS_URL, json=_friends_answer((555, "AltOne", sent)))
        mocked_http.post(FRIENDS_URL, json={"r": "success"})

        link_claims.check_pending()

        claim.refresh_from_db()
        assert claim.status == "proven"

    def test_a_pause_that_starts_mid_check_holds_them_too(self, client, mocked_http, bot_signed_in):
        claim = _start(client)
        mocked_http.post(FRIENDS_URL, json={"r": "fail", "e": "ratelimited"})

        counts = link_claims.check_pending()

        claim.refresh_from_db()
        assert counts["skipped"] == "rate_limited"
        assert claim.expires_at > timezone.now() + timedelta(minutes=5)


class TestTakeover:
    """Reported 2026-11-25: a friend request can't show who started the claim
    it proves. Someone waiting on a claim for your name could sign in as you
    when you friend the bot for any reason (BonxBot's /link uses it too).
    A friend request may now claim only accounts no one has on Bonkverse,
    and the password beats an earlier friend-request claim (ADR 0024)."""

    def _prove(self, claim, bonk_id=1234567, name="TestPlayer"):
        LinkClaim.objects.filter(pk=claim.pk).update(
            status=LinkClaim.PROVEN, bonk_id=bonk_id, bonk_name=name, proven_at=timezone.now()
        )

    def _password_login(self, client, mocked_http):
        mocked_http.post(LOGIN_URL, json=load_bonk_fixture("login_success"))
        client.post("/login/", {"username": "TestPlayer", "password": "pw"})

    def test_cannot_start_a_claim_for_an_account_already_here(self, client, mocked_http):
        from django.test import Client

        self._password_login(Client(), mocked_http)  # the victim, elsewhere

        response = client.post("/login/friend/", {"username": "testplayer"}, follow=True)

        assert not LinkClaim.objects.exists()
        assert "already on Bonkverse" in response.content.decode()

    def test_cannot_add_an_account_already_here_to_your_group(self, client, mocked_http):
        from django.test import Client

        self._password_login(Client(), mocked_http)  # the victim
        client.force_login(UserFactory(username="Mallory"))

        client.post("/login/friend/", {"username": "TestPlayer", "add": "1"})

        assert not LinkClaim.objects.exists()

    def test_an_owned_account_under_another_name_is_refused_at_the_end(self, client):
        claim = _start(client, name="NewName")
        owner = UserFactory(username="OldName")
        from players.models import BonkPlayer

        player = BonkPlayer.objects.create(bonk_id=4242, username="OldName")
        BonkAccountLink.objects.create(user=owner, bonk_player=player, active=True)
        self._prove(claim, bonk_id=4242, name="NewName")

        assert _status(client, claim)["status"] == "refused"
        assert client.get("/api/me/").status_code == 401

    def test_a_new_account_can_still_start_by_friend_request(self, client):
        claim = _start(client, name="TestPlayer")
        self._prove(claim)

        assert _status(client, claim)["status"] == "done"

    def test_the_password_takes_it_back_from_a_claimer(
        self, client, mocked_http, django_capture_on_commit_callbacks
    ):
        from django.test import Client

        from accounts.models import RememberedSignIn

        # Mallory claimed TestPlayer by friend request and grouped it with hers.
        claim = _start(client, name="TestPlayer")
        self._prove(claim)
        _status(client, claim)
        mallory_alt = UserFactory(username="MalloryAlt")
        groups.join(BonkUser.objects.get(username="TestPlayer"), mallory_alt)
        assert client.get("/api/me/").json()["user"]["username"] == "TestPlayer"

        # The real owner signs in with the password on their own browser.
        owner = Client()
        with django_capture_on_commit_callbacks(execute=True):
            self._password_login(owner, mocked_http)

        account = BonkUser.objects.get(username="TestPlayer")
        assert account.account_group_id is None
        assert owner.get("/api/me/").json()["user"]["username"] == "TestPlayer"
        assert client.get("/api/me/").status_code == 401  # Mallory's session ended
        assert RememberedSignIn.objects.filter(user=account).count() == 1  # owner's only

    def test_the_groups_own_browser_keeps_its_alt(self, client, mocked_http):
        """The owner signs in to their main (trusting this browser), adds a
        new alt by friend request, then signs in to the alt with its password
        here: nothing to take back."""
        main_answer = load_bonk_fixture("login_success")
        main_answer.update(username="MainOne", id=7654321)
        mocked_http.post(LOGIN_URL, json=main_answer)
        client.post("/login/", {"username": "MainOne", "password": "pw"})
        claim = _start(client, name="TestPlayer", add="1")
        self._prove(claim)
        _status(client, claim)
        account = BonkUser.objects.get(username="TestPlayer")
        group_id = account.account_group_id
        assert group_id is not None

        self._password_login(client, mocked_http)

        account.refresh_from_db()
        assert account.account_group_id == group_id
