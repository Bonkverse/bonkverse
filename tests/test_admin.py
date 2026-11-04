"""Django admin access.

BonkUser had no PermissionsMixin, so the admin index crashed for everyone,
staff included, and createsuperuser had nothing to call. Site accounts have
no usable password (login goes through bonk.io), so the admin login form is
replaced by a redirect to the site login.
"""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from skins.models import BonkUser
from tests.factories import SkinFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client):
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    return client


def test_staff_can_open_admin_index(client, staff_user):
    """Regression: AttributeError (no has_module_perms) for every staff user."""
    client.force_login(staff_user)

    assert client.get("/admin/").status_code == 200


@pytest.mark.parametrize(
    "url", ["/admin/", "/admin/skins/skin/", "/admin/skins/bonkuser/", "/admin/auth/group/"]
)
def test_superuser_can_open_admin_pages(admin_client, url):
    SkinFactory()

    assert admin_client.get(url).status_code == 200


def test_superuser_can_open_a_user(admin_client, user):
    assert admin_client.get(f"/admin/skins/bonkuser/{user.pk}/change/").status_code == 200


def test_staff_without_permissions_sees_no_models(client, staff_user):
    client.force_login(staff_user)

    response = client.get("/admin/")

    assert b"/admin/skins/skin/" not in response.content


def test_regular_user_is_sent_to_login(client, user):
    client.force_login(user)

    response = client.get("/admin/")

    assert response.status_code == 302


def test_anonymous_admin_goes_to_site_login_and_back(client):
    response = client.get("/admin/", follow=True)

    final_url, _status = response.redirect_chain[-1]
    assert final_url.startswith("/login/")
    assert "next=%2Fadmin%2F" in final_url


def test_create_superuser_makes_an_admin_without_a_password():
    user = BonkUser.objects.create_superuser("Boss", password="ignored")

    assert user.is_staff and user.is_superuser
    assert not user.has_usable_password()


class TestGrantAdmin:
    def test_promotes_existing_account(self, user):
        out = StringIO()

        call_command("grant_admin", user.username.upper(), stdout=out)

        user.refresh_from_db()
        assert user.is_staff and user.is_superuser
        assert "now an admin" in out.getvalue()

    def test_revoke_keeps_staff(self, user):
        call_command("grant_admin", user.username, stdout=StringIO())

        call_command("grant_admin", user.username, "--revoke", stdout=StringIO())

        user.refresh_from_db()
        assert user.is_staff and not user.is_superuser

    def test_unknown_username_is_an_error(self):
        with pytest.raises(CommandError, match="sign in to Bonkverse once"):
            call_command("grant_admin", "nobody-here")
