"""Trusted browsers (accounts/devices.py, RFC-0003 phase 5, PR 3).

Only the group's main unlocks the group: signing in to the main on a browser
makes every account in the group one-click switchable there, and trusts the
browser. Signing in to any other account opens only that account. A trusted
browser can be removed in Settings, forgotten on "Sign out of all accounts",
and expires 90 days after its last use; then the accounts the main unlocked
there are signed out there.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts import devices, groups
from accounts.models import TrustedDevice
from tests.conftest import load_bonk_fixture
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


def _login(client, mocked_http, user, **extra):
    """A password login (bonk.io mocked) as `user`'s bonk.io account."""
    answer = load_bonk_fixture("login_success")
    answer["username"] = user.username
    mocked_http.post(BONK_LOGIN_URL, json=answer)
    return client.post(
        "/login/",
        {"username": user.username, "password": "pw", **extra},
        HTTP_USER_AGENT=CHROME_WINDOWS,
    )


@pytest.fixture
def group():
    main = UserFactory(username="MainOne")
    alt = UserFactory(username="AltOne")
    third = UserFactory(username="AltTwo")
    groups.join(main, alt)
    groups.join(main, third)
    for account in (main, alt, third):
        account.refresh_from_db()
    return main, alt, third


def _me(client):
    return client.get("/api/me/").json()


def _signed_in_names(client):
    return {row["username"] for row in _me(client)["accounts"] if row["signed_in"]}


class TestTheMainUnlocks:
    def test_signing_in_to_the_main_unlocks_every_account(self, client, mocked_http, group):
        main, alt, third = group

        _login(client, mocked_http, main)

        assert _signed_in_names(client) == {"MainOne", "AltOne", "AltTwo"}
        client.post("/accounts/switch/", {"account": third.pk})
        assert _me(client)["user"]["username"] == "AltTwo"

    def test_and_trusts_the_browser(self, client, mocked_http, group):
        main, *_ = group

        _login(client, mocked_http, main)

        device = TrustedDevice.objects.get(group=main.account_group)
        assert device.label == "Chrome on Windows"
        assert devices.COOKIE in client.cookies

    def test_another_account_opens_only_itself(self, client, mocked_http, group):
        _, alt, _ = group

        _login(client, mocked_http, alt)

        assert _signed_in_names(client) == {"AltOne"}
        assert not TrustedDevice.objects.exists()

    def test_even_on_a_browser_the_main_used_before(self, client, mocked_http, group):
        """Only the main unlocks, every time (the owner's choice, option A)."""
        main, alt, _ = group
        _login(client, mocked_http, main)
        client.post("/logout/")

        _login(client, mocked_http, alt)

        assert _signed_in_names(client) == {"AltOne"}


class TestRemovingTrust:
    def test_removing_the_browser_signs_out_the_unlocked_accounts_there(
        self, client, mocked_http, group
    ):
        main, alt, _ = group
        _login(client, mocked_http, main)
        client.post("/accounts/switch/", {"account": alt.pk})
        device = TrustedDevice.objects.get()

        # Removed (from Settings on another browser, say).
        TrustedDevice.objects.filter(pk=device.pk).delete()

        me = _me(client)
        # Back on the main, the one account signed in with its own password.
        assert me["user"]["username"] == "MainOne"
        assert {r["username"] for r in me["accounts"] if r["signed_in"]} == {"MainOne"}

    def test_trust_unused_for_90_days_ends(self, client, mocked_http, group):
        main, *_ = group
        _login(client, mocked_http, main)
        TrustedDevice.objects.update(last_used_at=timezone.now() - timedelta(days=91))

        assert _signed_in_names(client) == {"MainOne"}

    def test_use_keeps_it_trusted(self, client, mocked_http, group):
        main, *_ = group
        _login(client, mocked_http, main)
        stale = timezone.now() - timedelta(days=80)
        TrustedDevice.objects.update(last_used_at=stale)

        _me(client)

        assert TrustedDevice.objects.get().last_used_at > stale

    def test_sign_out_of_all_can_forget_this_device(self, client, mocked_http, group):
        main, *_ = group
        _login(client, mocked_http, main)

        client.post("/logout/", {"forget": "on"})

        assert not TrustedDevice.objects.exists()

    def test_sign_out_of_all_keeps_it_unless_asked(self, client, mocked_http, group):
        main, *_ = group
        _login(client, mocked_http, main)

        client.post("/logout/")

        assert TrustedDevice.objects.exists()


class TestSettingsList:
    def test_lists_the_groups_browsers(self, client, mocked_http, group):
        main, *_ = group
        _login(client, mocked_http, main)

        page = client.get("/settings/profile/").content.decode()

        assert "Trusted browsers" in page
        assert "Chrome on Windows" in page
        assert "this browser" in page

    def test_the_main_signed_in_here_can_remove_one(self, client, mocked_http, group):
        main, *_ = group
        _login(client, mocked_http, main)
        other = TrustedDevice.objects.create(
            group=main.account_group,
            device_hash="x" * 64,
            label="Firefox on Linux",
            last_used_at=timezone.now(),
        )

        client.post("/accounts/browsers/remove/", {"device": other.pk})

        assert not TrustedDevice.objects.filter(pk=other.pk).exists()

    def test_another_account_alone_cant(self, client, mocked_http, group):
        main, alt, _ = group
        other = TrustedDevice.objects.create(
            group=main.account_group, device_hash="x" * 64, last_used_at=timezone.now()
        )
        _login(client, mocked_http, alt)

        client.post("/accounts/browsers/remove/", {"device": other.pk})

        assert TrustedDevice.objects.filter(pk=other.pk).exists()

    def test_the_header_offers_to_forget_this_device(self, client, mocked_http, group):
        main, *_ = group
        _login(client, mocked_http, main)

        page = client.get("/settings/profile/").content.decode()

        assert "Also forget this device" in page


class TestDeviceCookie:
    def test_the_database_keeps_only_a_hash(self, client, mocked_http, group):
        main, *_ = group
        _login(client, mocked_http, main)

        raw = client.cookies[devices.COOKIE].value
        assert TrustedDevice.objects.get().device_hash not in raw
        assert len(TrustedDevice.objects.get().device_hash) == 64

    def test_a_forged_cookie_trusts_nothing(self, client, mocked_http, group):
        main, alt, _ = group
        _login(client, mocked_http, main)
        client.post("/logout/")
        client.cookies[devices.COOKIE] = "forged"

        _login(client, mocked_http, alt)

        assert _signed_in_names(client) == {"AltOne"}


@pytest.mark.parametrize(
    "agent, label",
    [
        (CHROME_WINDOWS, "Chrome on Windows"),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Safari on iOS",
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
            "Firefox on Linux",
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 "
            "Safari/537.36 Edg/131.0",
            "Edge on Windows",
        ),
        ("", "A browser"),
    ],
)
def test_browser_labels(agent, label):
    assert devices.label_for(agent) == label
