"""A person's bonk.io accounts: adding, switching, signing out, removing
(accounts/groups.py, RFC-0003 phase 5, ADR 0023).

Each bonk.io account is its own site account; a group ties them together.
Switching needs no password but only between accounts signed in on this
browser.
"""

import json
import time

import pytest

from accounts import groups
from accounts.models import AccountGroup, BonkAccountLink, BonkUser, UserEvent
from tests.conftest import connect_bonk, load_bonk_fixture
from tests.factories import SkinFactory, UserFactory

pytestmark = pytest.mark.django_db

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"


def _signed_in(client, *accounts):
    """`client` signed in on every one of `accounts`, using the last."""
    client.force_login(accounts[-1])
    session = client.session
    session[groups.SIGNED_IN_KEY] = [account.pk for account in accounts]
    session.save()
    return client


def _group(*accounts):
    """Put `accounts` in one group, the first as main."""
    for account in accounts[1:]:
        groups.join(accounts[0], account)
    for account in accounts:
        account.refresh_from_db()
    return accounts[0].account_group


def _login(client, mocked_http, username="TestPlayer", **extra):
    answer = load_bonk_fixture("login_success")
    answer["username"] = username
    mocked_http.post(BONK_LOGIN_URL, json=answer)
    query = "?add=1" if extra.pop("add", False) else ""
    return client.post(f"/login/{query}", {"username": username, "password": "pw", **extra})


class TestAddAccount:
    def test_add_joins_the_group_and_keeps_both_signed_in(self, client, mocked_http):
        main = UserFactory(username="Mainy")
        client.force_login(main)

        response = _login(client, mocked_http, add=True)

        assert response.status_code == 302
        alt = BonkUser.objects.get(username="TestPlayer")
        main.refresh_from_db()
        assert alt.account_group_id == main.account_group_id is not None
        assert main.account_group.main_id == main.pk
        assert client.session[groups.SIGNED_IN_KEY] == [main.pk, alt.pk]
        me = client.get("/api/me/").json()
        assert me["user"]["username"] == "TestPlayer"
        assert {row["username"]: row["signed_in"] for row in me["accounts"]} == {
            "Mainy": True,
            "TestPlayer": True,
        }

    def test_a_plain_login_while_signed_in_never_groups(self, client, mocked_http):
        """Logging in to a friend's account on your browser doesn't join it."""
        main = UserFactory(username="Mainy")
        client.force_login(main)

        _login(client, mocked_http)

        main.refresh_from_db()
        assert main.account_group_id is None
        assert not AccountGroup.objects.exists()
        assert client.session[groups.SIGNED_IN_KEY] == [
            BonkUser.objects.get(username="TestPlayer").pk
        ]

    def test_the_page_says_what_adding_does(self, logged_in_client):
        page = logged_in_client.get("/login/?add=1&username=Alty").content.decode()

        assert "Add a bonk.io account" in page
        assert 'name="add" value="1"' in page
        assert 'value="Alty"' in page

    def test_signed_out_add_is_a_plain_login(self, client):
        page = client.get("/login/?add=1").content.decode()

        assert "Add a bonk.io account" not in page

    def test_adding_an_account_from_another_group_moves_it(self):
        """The password proves who controls it now (shared, sold, given away)."""
        old_main, moved = UserFactory(), UserFactory()
        old_group = _group(old_main, moved)
        new_main = UserFactory()

        groups.join(new_main, moved)

        moved.refresh_from_db()
        new_main.refresh_from_db()
        assert moved.account_group_id == new_main.account_group_id
        # The old group had two; one left is no group.
        assert not AccountGroup.objects.filter(pk=old_group.pk).exists()
        old_main.refresh_from_db()
        assert old_main.account_group_id is None

    def test_the_new_account_takes_the_groups_appearance(self):
        main = UserFactory(theme="dark", seasonal=False, appearance_at=123)
        alt = UserFactory(theme="light", appearance_at=5)

        groups.join(main, alt)

        alt.refresh_from_db()
        assert (alt.theme, alt.seasonal, alt.appearance_at) == ("dark", False, 123)


class TestSwitching:
    def test_switches_to_an_account_signed_in_here(self, client):
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        link = connect_bonk(_signed_in(client, main, alt), main, slot=4)

        response = client.post("/accounts/switch/", {"account": main.pk})

        assert response.status_code == 302
        assert client.get("/api/me/").json()["user"]["id"] == main.pk
        # Wear now acts as the main's bonk.io account.
        assert client.session["bonk_user_id"] == link.bonk_player.bonk_id
        assert client.session["bonk_active_slot"] == 4
        assert client.session[groups.SIGNED_IN_KEY] == [alt.pk, main.pk]
        assert UserEvent.objects.filter(user=main, event_type="account_switched").exists()

    def test_an_account_not_signed_in_here_needs_its_password(self, client):
        """The new-device guard, simplest form: no switching into an account
        this browser never signed in to."""
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        _signed_in(client, alt)

        client.post("/accounts/switch/", {"account": main.pk})

        assert client.get("/api/me/").json()["user"]["id"] == alt.pk

    def test_never_into_someone_elses_account(self, client):
        mine, theirs = UserFactory(), UserFactory()
        _signed_in(client, mine, theirs)  # even if the browser was signed in to it

        client.force_login(mine)
        client.post("/accounts/switch/", {"account": theirs.pk})

        assert client.get("/api/me/").json()["user"]["id"] == mine.pk

    def test_switching_drops_the_last_accounts_bonk_identity(self, client):
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        connect_bonk(_signed_in(client, alt, main), main)  # session points at main's
        client.post("/accounts/switch/", {"account": alt.pk})  # alt has no link

        assert "bonk_user_id" not in client.session

    def test_wear_after_switching_uses_the_new_accounts_link(self, client, mocked_http):
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        _signed_in(client, main, alt)
        connect_bonk(client, main, token="main-token")
        connect_bonk(client, alt, token="alt-token")
        wear = mocked_http.post(
            "https://bonk2.io/scripts/avatar_update.php",
            json=load_bonk_fixture("avatar_update_success"),
        )
        client.post("/accounts/switch/", {"account": main.pk})

        client.post(f"/api/skins/{SkinFactory().id}/wear/")

        assert "token=main-token" in wear.calls[0].request.body


class TestSignOut:
    def test_signing_out_of_one_switches_to_another(self, client):
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        _signed_in(client, main, alt)

        client.post("/logout/", {"scope": "this"})

        assert client.get("/api/me/").json()["user"]["id"] == main.pk
        assert client.session[groups.SIGNED_IN_KEY] == [main.pk]

    def test_signing_out_of_all(self, client):
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        _signed_in(client, main, alt)

        client.post("/logout/")

        assert client.get("/api/me/").status_code == 401

    def test_one_account_signs_out_as_before(self, logged_in_client):
        logged_in_client.post("/logout/", {"scope": "this"})

        assert logged_in_client.get("/api/me/").status_code == 401


class TestRemoveAndMain:
    def test_the_main_removes_an_account_and_its_history_goes_with_it(self, client):
        main, alt, third = UserFactory(), UserFactory(), UserFactory()
        _group(main, alt, third)
        skin = SkinFactory()
        skin.favorited_by.add(alt)
        _signed_in(client, alt, main)

        client.post("/accounts/remove/", {"account": alt.pk})

        alt.refresh_from_db()
        assert alt.account_group_id is None
        assert list(alt.favorite_skins.all()) == [skin]
        assert alt.pk not in client.session[groups.SIGNED_IN_KEY]

    def test_two_becoming_one_deletes_the_group(self, client):
        main, alt = UserFactory(), UserFactory()
        group = _group(main, alt)
        _signed_in(client, main)

        client.post("/accounts/remove/", {"account": alt.pk})

        assert not AccountGroup.objects.filter(pk=group.pk).exists()
        main.refresh_from_db()
        assert main.account_group_id is None

    def test_another_account_cant_remove_the_main_unless_the_main_is_here(self, client):
        main, alt, third = UserFactory(), UserFactory(), UserFactory()
        _group(main, alt, third)
        _signed_in(client, alt)

        client.post("/accounts/remove/", {"account": main.pk})

        main.refresh_from_db()
        assert main.account_group_id is not None

    def test_an_account_can_leave_by_itself(self, client):
        main, alt, third = UserFactory(), UserFactory(), UserFactory()
        _group(main, alt, third)
        _signed_in(client, alt)

        client.post("/accounts/remove/", {"account": alt.pk})

        alt.refresh_from_db()
        assert alt.account_group_id is None
        assert client.get("/api/me/").json()["user"]["id"] == alt.pk

    def test_the_main_leaving_hands_main_to_the_next(self, client):
        main, alt, third = UserFactory(), UserFactory(), UserFactory()
        group = _group(main, alt, third)
        _signed_in(client, main)

        client.post("/accounts/remove/", {"account": main.pk})

        group.refresh_from_db()
        assert group.main_id == alt.pk

    def test_make_main_needs_the_main_signed_in_here(self, client):
        main, alt = UserFactory(), UserFactory()
        group = _group(main, alt)
        _signed_in(client, alt)
        client.post("/accounts/main/", {"account": alt.pk})
        group.refresh_from_db()
        assert group.main_id == main.pk

        _signed_in(client, main, alt)
        client.post("/accounts/main/", {"account": alt.pk})
        group.refresh_from_db()
        assert group.main_id == alt.pk


class TestOtherSitesSwitch:
    URL = "/api/me/switch/"

    def _post(self, client, account, **headers):
        return client.post(
            self.URL,
            json.dumps({"account": account.pk}),
            content_type="application/json",
            **headers,
        )

    def test_switches_from_our_own_origin(self, client):
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        _signed_in(client, main, alt)

        response = self._post(
            client,
            main,
            HTTP_X_BONKVERSE_SWITCH="1",
            HTTP_ORIGIN="https://replays.bonkverse.io",
        )

        assert response.json()["ok"] is True
        assert response.json()["user"]["id"] == main.pk

    def test_needs_the_custom_header(self, client):
        """A plain cross-site form can't add it, so no CSRF token is needed."""
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        _signed_in(client, main, alt)

        assert self._post(client, main).status_code == 400

    def test_refuses_other_origins(self, client):
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        _signed_in(client, main, alt)

        response = self._post(
            client, main, HTTP_X_BONKVERSE_SWITCH="1", HTTP_ORIGIN="https://evil.example"
        )

        assert response.status_code == 403
        assert client.get("/api/me/").json()["user"]["id"] == alt.pk

    def test_cors_lets_the_header_through(self, client):
        response = client.options(
            self.URL,
            HTTP_ORIGIN="https://replays.bonkverse.io",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="x-bonkverse-switch, content-type",
        )

        assert "x-bonkverse-switch" in response["Access-Control-Allow-Headers"]


class TestHeaderAndSettings:
    def test_one_account_sees_no_switcher(self, logged_in_client):
        page = logged_in_client.get("/settings/profile/").content.decode()

        assert "Switch account" not in page
        assert "Add bonk.io account" in page

    def test_the_header_lists_the_other_accounts(self, client):
        main, alt, third = UserFactory(), UserFactory(), UserFactory()
        _group(main, alt, third)
        _signed_in(client, main, alt)

        page = client.get("/settings/profile/").content.decode()

        assert "Switch account" in page
        assert f"Sign out of {alt.username}" in page
        assert "Sign out of all accounts" in page
        # Third isn't signed in here: offered as "Sign in", with its name filled in.
        assert f"?add=1&amp;username={third.username}" in page

    def test_appearance_chosen_on_one_account_reaches_the_others(self, client):
        main, alt = UserFactory(), UserFactory()
        _group(main, alt)
        _signed_in(client, main, alt)
        now = int(time.time() * 1000)
        client.cookies["bv-theme"] = "light"
        client.cookies["bv-appearance-at"] = str(now)

        client.get("/settings/profile/")

        main.refresh_from_db()
        assert (main.theme, main.appearance_at) == ("light", now)


class TestWearPopupWithAnotherAccount:
    def test_the_popups_other_account_keeps_the_first_signed_in(self, client, mocked_http):
        main = UserFactory(username="Mainy")
        client.force_login(main)
        mocked_http.post(BONK_LOGIN_URL, json=load_bonk_fixture("login_success"))

        client.post("/api/bonk/login/", {"bonk_username": "TestPlayer", "bonk_password": "pw"})

        alt = BonkUser.objects.get(username="TestPlayer")
        assert client.session[groups.SIGNED_IN_KEY] == [main.pk, alt.pk]
        assert BonkAccountLink.objects.filter(user=alt).exists()


class TestConvertingOldMultiLinkAccounts:
    """manage.py group_linked_accounts: one site account linked to several
    bonk.io accounts becomes a group of site accounts."""

    def _links(self, owner, *names):
        from players.models import BonkPlayer

        links = []
        for n, name in enumerate(names):
            player = BonkPlayer.objects.create(bonk_id=9000 + n, username=name)
            links.append(BonkAccountLink.objects.create(user=owner, bonk_player=player))
        return links

    def test_dry_run_changes_nothing(self):
        from django.core.management import call_command

        owner = UserFactory(username="Owner")
        self._links(owner, "Owner", "AltOne")

        call_command("group_linked_accounts")

        assert BonkAccountLink.objects.filter(user=owner).count() == 2
        assert not AccountGroup.objects.exists()

    def test_each_link_moves_to_its_own_account_in_one_group(self):
        from django.core.management import call_command

        owner = UserFactory(username="Owner")
        skin = SkinFactory()
        skin.favorited_by.add(owner)
        _, alt_link = self._links(owner, "Owner", "AltOne")

        call_command("group_linked_accounts", "--run")

        alt = BonkUser.objects.get(username="AltOne")
        alt_link.refresh_from_db()
        assert alt_link.user_id == alt.pk
        owner.refresh_from_db()
        assert owner.account_group_id == alt.account_group_id is not None
        # The most recently connected link's account is the main.
        assert owner.account_group.main_id == alt.pk
        # History stays where it was saved.
        assert list(owner.favorite_skins.all()) == [skin]

    def test_an_existing_site_account_is_used_and_running_twice_is_safe(self):
        from django.core.management import call_command

        owner = UserFactory(username="Owner")
        alt = UserFactory(username="AltOne")
        self._links(owner, "Owner", "AltOne")

        call_command("group_linked_accounts", "--run")
        call_command("group_linked_accounts", "--run")

        assert BonkUser.objects.filter(username__iexact="altone").count() == 1
        assert BonkAccountLink.objects.filter(user=alt).count() == 1
        assert AccountGroup.objects.count() == 1
