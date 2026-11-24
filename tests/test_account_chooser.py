"""The login page's "Choose an account" (accounts/known_accounts.py) and
one-click sign-in (accounts/devices.py, ADR 0025).

Accounts that signed in on this browser stay listed after signing out, like
Google's chooser. One that proved itself here (password or friend request)
in the last ONE_CLICK_SIGN_IN_DAYS signs straight back in, with no bonk.io
call; after that it opens the way it last signed in, name filled in.
"""

import json
import time
from datetime import timedelta

import pytest
from django.http import HttpResponse
from django.utils import timezone

from accounts import known_accounts
from accounts.models import LinkClaim, RememberedSignIn
from tests.conftest import load_bonk_fixture
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"


@pytest.fixture(autouse=True)
def bot(settings):
    settings.BONK_BOT_USERNAME = "Bonkverse Bot"
    settings.BONK_BOT_PASSWORD = "bot-password"


def _password_login(client, mocked_http, name="TestPlayer"):
    answer = load_bonk_fixture("login_success")
    answer["username"] = name
    mocked_http.post(LOGIN_URL, json=answer)
    client.post("/login/", {"username": name, "password": "pw"})


def _friend_login(client, name="AltOne", bonk_id=555):
    client.post("/login/friend/", {"username": name})
    claim = LinkClaim.objects.latest("pk")
    LinkClaim.objects.filter(pk=claim.pk).update(
        status=LinkClaim.PROVEN, bonk_id=bonk_id, bonk_name=name, proven_at=timezone.now()
    )
    client.post(f"/login/friend/{claim.pk}/status/")


def _page(client, url="/login/"):
    return client.get(url).content.decode()


def _age_proofs(days):
    """Move every one-click proof `days` into the past."""
    RememberedSignIn.objects.update(proven_at=timezone.now() - timedelta(days=days))


def _expire_one_click():
    _age_proofs(31)


class TestTheChooser:
    def test_a_new_browser_gets_the_plain_form(self, client):
        page = _page(client)

        assert "Choose an account" not in page
        assert 'name="password"' in page

    def test_after_signing_out_the_account_is_offered(self, client, mocked_http):
        _password_login(client, mocked_http)
        client.post("/logout/")
        _expire_one_click()

        page = _page(client)

        assert "Choose an account" in page
        assert "TestPlayer" in page and "With your password" in page
        assert "/login/?username=TestPlayer" in page

    def test_a_friend_request_account_opens_the_friend_request_way(self, client):
        _friend_login(client)
        client.post("/logout/")
        _expire_one_click()

        page = _page(client)

        assert "With a friend request" in page
        assert "/login/friend/?username=AltOne" in page

    def test_the_way_it_last_signed_in_wins(self, client, mocked_http):
        _friend_login(client, name="TestPlayer", bonk_id=1234567)
        client.post("/logout/")
        _password_login(client, mocked_http)
        client.post("/logout/")
        _expire_one_click()

        page = _page(client)

        assert "/login/?username=TestPlayer" in page
        assert "/login/friend/?username=TestPlayer" not in page

    def test_every_account_is_listed_newest_first(self, client, mocked_http):
        _friend_login(client, name="AltOne", bonk_id=1)
        _password_login(client, mocked_http)
        client.post("/logout/")

        page = _page(client)

        assert page.index("TestPlayer") < page.index("AltOne")

    def test_choosing_fills_in_the_name(self, client, mocked_http):
        _password_login(client, mocked_http)
        client.post("/logout/")

        page = _page(client, "/login/?username=TestPlayer")

        assert 'value="TestPlayer"' in page and 'name="password"' in page

    def test_use_another_account_shows_the_plain_form(self, client, mocked_http):
        _password_login(client, mocked_http)
        client.post("/logout/")

        page = _page(client, "/login/?other=1")

        assert "Choose an account" not in page

    def test_signed_in_sees_the_form(self, client, mocked_http):
        _password_login(client, mocked_http)

        assert "Choose an account" not in _page(client)


class TestOneClick:
    def test_a_recent_sign_in_signs_straight_back_in(self, client, mocked_http):
        _password_login(client, mocked_http)
        client.post("/logout/")
        calls = len(mocked_http.calls)

        page = _page(client)
        response = client.post("/login/choose/", {"username": "TestPlayer"})

        assert "Signs straight in" in page and 'action="/login/choose/"' in page
        assert response.status_code == 302
        assert client.get("/api/me/").json()["user"]["username"] == "TestPlayer"
        assert len(mocked_http.calls) == calls  # no bonk.io call

    def test_a_friend_request_sign_in_counts_too(self, client):
        _friend_login(client)
        client.post("/logout/")

        client.post("/login/choose/", {"username": "AltOne"})

        assert client.get("/api/me/").json()["user"]["username"] == "AltOne"

    def test_it_follows_next(self, client, mocked_http):
        _password_login(client, mocked_http)
        client.post("/logout/")

        response = client.post("/login/choose/", {"username": "TestPlayer", "next": "/skins/"})

        assert response["Location"] == "/skins/"

    def test_one_click_does_not_extend_the_window(self, client, mocked_http):
        _password_login(client, mocked_http)
        client.post("/logout/")
        _age_proofs(29)

        client.post("/login/choose/", {"username": "TestPlayer"})
        client.post("/logout/")
        _age_proofs(31)

        assert "Signs straight in" not in _page(client)

    def test_after_the_window_it_asks_again(self, client, mocked_http):
        _password_login(client, mocked_http)
        client.post("/logout/")
        _expire_one_click()

        response = client.post("/login/choose/", {"username": "TestPlayer"})

        assert response["Location"] == "/login/?username=TestPlayer"
        assert client.get("/api/me/").status_code == 401

    def test_another_browser_cannot(self, client, mocked_http):
        from django.test import Client

        _password_login(client, mocked_http)
        other = Client()

        response = other.post("/login/choose/", {"username": "TestPlayer"})

        assert response.status_code == 302
        assert other.get("/api/me/").status_code == 401

    def test_a_forged_name_cannot(self, client, mocked_http):
        _password_login(client, mocked_http)
        client.post("/logout/")
        UserFactory(username="SomeoneElse")

        client.post("/login/choose/", {"username": "SomeoneElse"})

        assert client.get("/api/me/").status_code == 401

    def test_remove_ends_it(self, client, mocked_http):
        _password_login(client, mocked_http)
        client.post("/logout/")

        client.post("/login/forget/", {"username": "TestPlayer"})

        assert not RememberedSignIn.objects.exists()

    def test_also_forget_this_device_ends_it(self, client, mocked_http):
        _password_login(client, mocked_http)

        client.post("/logout/", {"forget": "on"})

        assert not RememberedSignIn.objects.exists()

    def test_settings_lists_and_removes_it(self, client, mocked_http):
        _password_login(client, mocked_http)

        page = client.get("/settings/profile/").content.decode()
        row = RememberedSignIn.objects.get()
        client.post("/accounts/one-click/remove/", {"browser": row.pk})

        assert "One-click sign-in" in page and "this browser" in page
        assert not RememberedSignIn.objects.exists()

    def test_settings_cannot_remove_another_accounts(self, client, mocked_http):
        _password_login(client, mocked_http)
        theirs = RememberedSignIn.objects.create(
            user=UserFactory(), device_hash="x" * 64, proven_at=timezone.now()
        )

        client.post("/accounts/one-click/remove/", {"browser": theirs.pk})

        assert RememberedSignIn.objects.filter(pk=theirs.pk).exists()


class TestForgetting:
    def test_remove_takes_one_off(self, client, mocked_http):
        _friend_login(client, name="AltOne", bonk_id=1)
        _password_login(client, mocked_http)
        client.post("/logout/")

        client.post("/login/forget/", {"username": "testplayer"})
        page = _page(client)

        assert "TestPlayer" not in page and "AltOne" in page

    def test_removing_the_last_one_leaves_the_plain_form(self, client, mocked_http):
        _password_login(client, mocked_http)
        client.post("/logout/")

        client.post("/login/forget/", {"username": "TestPlayer"})

        assert "Choose an account" not in _page(client)

    def test_also_forget_this_device_clears_the_list(self, client, mocked_http):
        _password_login(client, mocked_http)

        client.post("/logout/", {"forget": "on"})

        assert "Choose an account" not in _page(client)

    def test_a_plain_sign_out_keeps_it(self, client, mocked_http):
        _password_login(client, mocked_http)

        client.post("/logout/")

        assert "Choose an account" in _page(client)


class TestTheCookie:
    def test_signed_and_http_only(self, client, mocked_http):
        _password_login(client, mocked_http)

        cookie = client.cookies[known_accounts.COOKIE]
        assert cookie["httponly"]
        assert "TestPlayer" in cookie.value  # names only, nothing secret

    def test_a_tampered_cookie_is_ignored(self, client):
        client.cookies[known_accounts.COOKIE] = '[{"u":"Someone","via":"password","at":9999999999}]'

        assert "Choose an account" not in _page(client)

    def test_at_most_eight_and_old_ones_drop_off(self, rf):
        request = rf.get("/")
        old = time.time() - (known_accounts.KEEP_DAYS + 1) * 86400
        request.bv_known = []
        for n in range(10):
            known_accounts.remember(request, f"Player{n}", known_accounts.PASSWORD)
        assert len(known_accounts.accounts(request)) == known_accounts.MAX_ACCOUNTS
        assert known_accounts.accounts(request)[0]["username"] == "Player9"

        signed = known_accounts.COOKIE
        response_request = rf.get("/")
        response = HttpResponse()
        response.set_signed_cookie(
            signed,
            json.dumps([{"u": "Old", "via": "password", "at": old}]),
            salt=known_accounts.COOKIE_SALT,
        )
        response_request.COOKIES[signed] = response.cookies[signed].value
        assert known_accounts._read(response_request) == []

    def test_names_compare_ignoring_case(self, rf):
        request = rf.get("/")
        request.bv_known = []
        known_accounts.remember(request, "The Saucy Tulip", known_accounts.PASSWORD)
        known_accounts.remember(request, "the saucy tulip", known_accounts.FRIEND_REQUEST)

        assert known_accounts.accounts(request) == [
            {"username": "the saucy tulip", "via": "friend"}
        ]


def test_user_factory_accounts_are_not_listed_by_force_login(client):
    """Only real sign-ins (password or friend request) add to the list."""
    client.force_login(UserFactory())
    client.post("/logout/")

    assert "Choose an account" not in _page(client)
