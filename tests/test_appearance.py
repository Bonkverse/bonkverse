"""A signed-in player's appearance (theme and seasonal switch) is saved to
their account and follows them to other browsers (accounts/appearance.py)."""

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def browser(**cookies):
    client = Client()
    for name, value in cookies.items():
        client.cookies[name.replace("_", "-")] = value
    return client


def test_a_newer_choice_in_the_browser_is_saved_to_the_account(user):
    client = browser(bv_theme="light", bv_season="off", bv_appearance_at="2000")
    client.force_login(user)

    client.get("/")

    user.refresh_from_db()
    assert (user.theme, user.seasonal, user.appearance_at) == ("light", False, 2000)


def test_an_older_choice_in_the_browser_does_not_overwrite_the_account(user):
    user.theme, user.seasonal, user.appearance_at = "dark", True, 5000
    user.save()
    client = browser(bv_theme="light", bv_season="off", bv_appearance_at="1000")
    client.force_login(user)

    response = client.get("/")

    user.refresh_from_db()
    assert (user.theme, user.seasonal) == ("dark", True)
    # …and this browser is brought up to date instead
    assert response.cookies["bv-theme"].value == "dark"
    assert response.cookies["bv-season"].value == "on"
    assert response.cookies["bv-appearance-at"].value == "5000"


def test_a_new_browser_gets_the_accounts_choice(user):
    user.theme, user.seasonal, user.appearance_at = "light", False, 5000
    user.save()
    client = browser()
    client.force_login(user)

    response = client.get("/")

    assert response.cookies["bv-theme"].value == "light"
    assert response.cookies["bv-season"].value == "off"
    assert not response.cookies["bv-theme"]["httponly"]  # theme.js reads it


def test_cookies_are_shared_with_every_bonkverse_site(user, settings):
    settings.ALLOWED_HOSTS = ["bonkverse.io"]
    user.theme, user.appearance_at = "dark", 5000
    user.save()
    client = browser()
    client.force_login(user)

    response = client.get("/", HTTP_HOST="bonkverse.io")

    assert response.cookies["bv-theme"]["domain"] == ".bonkverse.io"


def test_nothing_happens_without_a_choice_or_signed_out(user):
    signed_in = browser()
    signed_in.force_login(user)
    assert "bv-theme" not in signed_in.get("/").cookies

    signed_out = browser(bv_theme="light", bv_appearance_at="2000")
    assert "bv-theme" not in signed_out.get("/").cookies


def test_a_bad_stamp_is_ignored(user):
    client = browser(bv_theme="light", bv_appearance_at="soon")
    client.force_login(user)

    client.get("/")

    user.refresh_from_db()
    assert user.appearance_at is None


def test_api_me_says_the_accounts_appearance(user):
    user.theme, user.seasonal, user.appearance_at = "light", False, 5000
    user.save()
    client = browser()
    client.force_login(user)

    data = client.get("/api/me/").json()

    assert data["user"]["appearance"] == {"theme": "light", "seasonal": False, "at": 5000}


def test_settings_page_has_the_appearance_controls(logged_in_client):
    html = logged_in_client.get("/settings/profile/").content.decode()

    assert "Appearance" in html
    assert "data-bv-theme-picker" in html
    assert "data-bv-season-toggle" in html


def test_header_puts_theme_and_season_in_one_appearance_menu(client):
    html = client.get("/").content.decode()

    assert 'class="bv-dropdown bv-appearance"' in html
    assert html.count("data-bv-theme-picker") == 1
