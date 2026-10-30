"""Django admin access.

BonkUser extends AbstractBaseUser without PermissionsMixin, so it has no
has_perm / has_module_perms and the admin index crashes for every user,
staff included. There is also no create_superuser, and site accounts have
unusable passwords because login goes through bonk.io.
"""

import pytest


@pytest.mark.django_db
@pytest.mark.xfail(
    reason="BonkUser lacks has_module_perms (no PermissionsMixin); /admin crashes for staff",
    raises=AttributeError,
    strict=True,
)
def test_staff_can_open_admin_index(client, staff_user):
    client.force_login(staff_user)

    response = client.get("/admin/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_anonymous_admin_redirects_to_login(client):
    response = client.get("/admin/")

    assert response.status_code == 302
