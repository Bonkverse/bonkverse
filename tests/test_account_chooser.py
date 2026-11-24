"""The login page's "Choose an account" (accounts/known_accounts.py).

Accounts that signed in on this browser stay listed after signing out, like
Google's chooser. Choosing one still needs proof: it opens the way it last
signed in (password or friend request) with the name filled in.
"""

import json
import time

import pytest
from django.http import HttpResponse
from django.utils import timezone

from accounts import known_accounts
from accounts.models import LinkClaim
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


class TestTheChooser:
    def test_a_new_browser_gets_the_plain_form(self, client):
        page = _page(client)

        assert "Choose an account" not in page
        assert 'name="password"' in page

    def test_after_signing_out_the_account_is_offered(self, client, mocked_http):
        _password_login(client, mocked_http)
        client.post("/logout/")

        page = _page(client)

        assert "Choose an account" in page
        assert "TestPlayer" in page and "With your password" in page
        assert "/login/?username=TestPlayer" in page

    def test_a_friend_request_account_opens_the_friend_request_way(self, client):
        _friend_login(client)
        client.post("/logout/")

        page = _page(client)

        assert "With a friend request" in page
        assert "/login/friend/?username=AltOne" in page

    def test_the_way_it_last_signed_in_wins(self, client, mocked_http):
        _friend_login(client, name="TestPlayer", bonk_id=1234567)
        client.post("/logout/")
        _password_login(client, mocked_http)
        client.post("/logout/")

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
