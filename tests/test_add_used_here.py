"""Adding accounts used on this browser without proving them again
(accounts/used_here.py, ADR 0025).

An account that proved itself on this browser (password or friend request)
within the one-click window, and is in no group, can join the signed-in
person's accounts after they tick it and confirm it's theirs.
"""

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from accounts.models import AccountGroup, BonkUser, RememberedSignIn
from tests.conftest import load_bonk_fixture
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"


def _password_login(client, mocked_http, name):
    answer = load_bonk_fixture("login_success")
    answer["username"] = name
    mocked_http.post(LOGIN_URL, json=answer)
    client.post("/login/", {"username": name, "password": "pw"})


def _used_then_main(client, mocked_http, alts=("AltOne", "AltTwo"), main="MainPlayer"):
    """Sign in to each alt on this browser, then to the main."""
    for name in alts:
        _password_login(client, mocked_http, name)
        client.post("/logout/")
    _password_login(client, mocked_http, main)


def _add(client, *names, confirm=True):
    ids = [BonkUser.objects.get(username=name).pk for name in names]
    data = {"account": ids}
    if confirm:
        data["confirm"] = "on"
    return client.post("/accounts/add-used-here/", data)


def _group_names(name):
    user = BonkUser.objects.get(username=name)
    if user.account_group_id is None:
        return {name}
    return set(
        BonkUser.objects.filter(account_group_id=user.account_group_id).values_list(
            "username", flat=True
        )
    )


class TestOffered:
    def test_the_add_page_lists_them(self, client, mocked_http):
        _used_then_main(client, mocked_http)

        page = client.get("/login/?add=1").content.decode()

        assert "Used on this browser" in page
        assert "AltOne" in page and "AltTwo" in page

    def test_settings_lists_them(self, client, mocked_http):
        _used_then_main(client, mocked_http)

        page = client.get("/settings/profile/").content.decode()

        assert "Used on this browser" in page and "AltOne" in page

    def test_the_first_page_after_signing_in_offers_once(self, client, mocked_http):
        _used_then_main(client, mocked_http)

        first = client.get("/").content.decode()
        second = client.get("/").content.decode()

        assert "2 other accounts were" in first and "Review" in first
        assert "other accounts were" not in second

    def test_no_offer_when_nothing_to_add(self, client, mocked_http):
        _password_login(client, mocked_http, "MainPlayer")

        assert "used on this browser. Add" not in client.get("/").content.decode()

    def test_not_after_the_one_click_window(self, client, mocked_http):
        _used_then_main(client, mocked_http)
        RememberedSignIn.objects.exclude(user__username="MainPlayer").update(
            proven_at=timezone.now() - timedelta(days=31)
        )

        assert "Used on this browser" not in client.get("/login/?add=1").content.decode()

    def test_not_an_account_already_in_a_group(self, client, mocked_http):
        _used_then_main(client, mocked_http)
        theirs = UserFactory()
        group = AccountGroup.objects.create(main=theirs)
        BonkUser.objects.filter(username="AltOne").update(account_group=group)

        page = client.get("/login/?add=1").content.decode()

        assert "AltOne" not in page and "AltTwo" in page

    def test_not_from_another_browser(self, client, mocked_http):
        _used_then_main(client, mocked_http)
        other = Client()
        other.force_login(BonkUser.objects.get(username="MainPlayer"))

        assert "Used on this browser" not in other.get("/login/?add=1").content.decode()


class TestAdding:
    def test_adds_the_ticked_ones(self, client, mocked_http):
        _used_then_main(client, mocked_http)
        calls = len(mocked_http.calls)

        _add(client, "AltOne", "AltTwo")

        assert _group_names("MainPlayer") == {"MainPlayer", "AltOne", "AltTwo"}
        assert len(mocked_http.calls) == calls  # no bonk.io call

    def test_only_the_ticked_ones(self, client, mocked_http):
        _used_then_main(client, mocked_http)

        _add(client, "AltOne")

        assert _group_names("MainPlayer") == {"MainPlayer", "AltOne"}

    def test_they_can_be_switched_to_at_once(self, client, mocked_http):
        _used_then_main(client, mocked_http)
        _add(client, "AltOne")
        alt = BonkUser.objects.get(username="AltOne")

        client.post("/accounts/switch/", {"account": alt.pk})

        assert client.get("/api/me/").json()["user"]["username"] == "AltOne"

    def test_needs_the_confirm(self, client, mocked_http):
        _used_then_main(client, mocked_http)

        _add(client, "AltOne", confirm=False)

        assert _group_names("MainPlayer") == {"MainPlayer"}

    def test_cannot_add_one_not_used_here(self, client, mocked_http):
        _used_then_main(client, mocked_http)
        UserFactory(username="Stranger")

        _add(client, "Stranger")

        assert _group_names("MainPlayer") == {"MainPlayer"}

    def test_cannot_pull_one_from_another_group(self, client, mocked_http):
        _used_then_main(client, mocked_http)
        theirs = UserFactory()
        group = AccountGroup.objects.create(main=theirs)
        BonkUser.objects.filter(username="AltOne").update(account_group=group)

        _add(client, "AltOne")

        assert BonkUser.objects.get(username="AltOne").account_group_id == group.pk

    def test_signed_out_cannot(self, client, mocked_http):
        _used_then_main(client, mocked_http)
        client.post("/logout/")

        response = _add(client, "AltOne")

        assert response.status_code == 302
        assert BonkUser.objects.get(username="AltOne").account_group_id is None
