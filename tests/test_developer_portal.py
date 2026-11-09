"""The developer portal (/developers/): terms, creating and revoking your own
API keys, and the limits on them."""

import pytest
from django.urls import reverse

from public_api import services
from public_api.keys import create_key, find_active_key
from public_api.models import ApiKey, ApiTermsAcceptance
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

KEYS = "/developers/keys/"


def create(client, name="My site", **extra):
    return client.post(KEYS, {"name": name, **extra})


def raw_key_in(response):
    """The full key from a "copy your new key" page, or None."""
    html = response.content.decode()
    start = html.find('value="bvk_')
    if start == -1:
        return None
    start += len('value="')
    return html[start : html.index('"', start)]


# ── Pages ────────────────────────────────────────────────────────────────────


def test_landing_and_terms_are_public(client, settings):
    settings.BONKVERSE_DOCS_URL = "https://docs.example"
    landing = client.get("/developers/").content.decode()
    assert "https://docs.example/api" in landing
    assert reverse("developer_keys") in landing
    assert client.get("/developers/terms/").status_code == 200


def test_keys_page_sends_signed_out_visitors_to_login(client):
    response = client.get(KEYS)
    assert response.status_code == 302
    assert response["Location"] == "/login/?next=/developers/keys/"


def test_navbar_links_to_the_portal(client):
    assert f'href="{reverse("developers")}"' in client.get("/").content.decode()


# ── Creating keys ────────────────────────────────────────────────────────────


def test_first_key_needs_the_terms(logged_in_client, user):
    response = create(logged_in_client)

    assert response.status_code == 302
    assert not ApiKey.objects.exists()
    assert not ApiTermsAcceptance.objects.exists()
    assert "Tick the box to agree" in logged_in_client.get(KEYS).content.decode()


def test_creating_a_key_shows_it_once_and_it_works(logged_in_client, user, client):
    response = create(logged_in_client, name="Comp leaderboard", agree="on")

    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    raw = raw_key_in(response)
    assert raw is not None

    api_key = ApiKey.objects.get()
    assert api_key.owner == user
    assert api_key.name == "Comp leaderboard"
    assert api_key.tier == ApiKey.TIER_STANDARD
    assert find_active_key(raw) == api_key
    assert ApiTermsAcceptance.objects.get(user=user).version == services.TERMS_VERSION

    # The key answers on the API...
    me = client.get("/api/v1/me/", HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert me.status_code == 200
    # ...and is never shown again.
    again = logged_in_client.get(KEYS)
    assert raw_key_in(again) is None
    assert f"bvk_{api_key.prefix}_" in again.content.decode()


def test_later_keys_dont_ask_again(logged_in_client, user):
    create(logged_in_client, agree="on")
    page = logged_in_client.get(KEYS).content.decode()
    assert 'name="agree"' not in page

    assert create(logged_in_client, name="Second").status_code == 200
    assert ApiKey.objects.filter(owner=user).count() == 2


def test_new_terms_version_asks_again(logged_in_client, user, monkeypatch):
    create(logged_in_client, agree="on")
    monkeypatch.setattr(services, "TERMS_VERSION", "2099-01-01")

    assert create(logged_in_client, name="After the change").status_code == 302
    assert ApiKey.objects.filter(owner=user).count() == 1
    assert create(logged_in_client, name="Agreed", agree="on").status_code == 200


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_key_names_are_checked(logged_in_client, name):
    response = create(logged_in_client, name=name, agree="on")
    assert response.status_code == 302
    assert not ApiKey.objects.exists()


def test_at_most_three_active_keys(logged_in_client, user, settings):
    settings.PUBLIC_API_MAX_KEYS_PER_USER = 3
    for n in range(3):
        assert create(logged_in_client, name=f"k{n}", agree="on").status_code == 200

    assert create(logged_in_client, name="fourth").status_code == 302
    assert ApiKey.objects.filter(owner=user, is_active=True).count() == 3
    assert "the most one account can have" in logged_in_client.get(KEYS).content.decode()

    # Revoking one frees a slot.
    first = ApiKey.objects.filter(owner=user).first()
    logged_in_client.post(reverse("developer_revoke_key", args=[first.prefix]))
    assert create(logged_in_client, name="replacement").status_code == 200


def test_staff_issued_keys_without_owner_dont_count(logged_in_client, user):
    create_key(name="Luna", tier=ApiKey.TIER_PARTNER)
    for n in range(3):
        assert create(logged_in_client, name=f"k{n}", agree="on").status_code == 200


# ── Revoking ─────────────────────────────────────────────────────────────────


def test_revoking_your_key_stops_it(logged_in_client, user, client):
    raw = raw_key_in(create(logged_in_client, agree="on"))
    api_key = ApiKey.objects.get()

    response = logged_in_client.post(reverse("developer_revoke_key", args=[api_key.prefix]))

    assert response.status_code == 302
    api_key.refresh_from_db()
    assert not api_key.is_active
    assert client.get("/api/v1/me/", HTTP_AUTHORIZATION=f"Bearer {raw}").status_code == 401


def test_you_cant_revoke_someone_elses_key(logged_in_client):
    other, _raw = create_key(name="Theirs", owner=UserFactory(username="someone else"))

    logged_in_client.post(reverse("developer_revoke_key", args=[other.prefix]))

    other.refresh_from_db()
    assert other.is_active


def test_revoke_is_post_only(logged_in_client, user):
    create(logged_in_client, agree="on")
    prefix = ApiKey.objects.get().prefix
    response = logged_in_client.get(reverse("developer_revoke_key", args=[prefix]))
    assert response.status_code == 405
    assert ApiKey.objects.get().is_active


def test_your_list_shows_only_your_keys(logged_in_client):
    create_key(name="Someone else's bot", owner=UserFactory(username="other"))
    create(logged_in_client, name="Mine", agree="on")

    page = logged_in_client.get(KEYS).content.decode()
    assert "Mine" in page
    assert "Someone else" not in page
