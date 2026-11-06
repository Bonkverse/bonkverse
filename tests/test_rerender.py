"""Tests for re-rendering a skin's images (skins/rerender.py)."""

import base64
import json

import pytest
import requests

from skins.models import SkinImage
from tests.factories import SkinFactory, UserFactory

pytestmark = pytest.mark.django_db

EDITOR = "https://editor.test"
RENDER_URL = f"{EDITOR}/api/render-bundle"
PURGE_URL = "https://api.cloudflare.com/client/v4/zones/zone123/purge_cache"
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    '<rect width="10" height="10" fill="red"/></svg>'
)
PNG = b"\x89PNG fake"


@pytest.fixture(autouse=True)
def _settings(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.BONKVERSE_RENDER_URL = EDITOR
    settings.CLOUDFLARE_ZONE_ID = ""
    settings.CLOUDFLARE_CACHE_API_TOKEN = ""


@pytest.fixture
def staff_client(client):
    client.force_login(UserFactory(username="Staff Member", is_staff=True))
    return client


def _renders(mocked_http, svg=SVG):
    mocked_http.post(
        RENDER_URL,
        json={"ok": True, "svg": svg, "pngBase64": base64.b64encode(PNG).decode()},
    )


def _rerender(client, skin):
    return client.post(f"/skins/{skin.id}/rerender/")


def test_writes_files_and_image_rows(staff_client, mocked_http, tmp_path):
    skin = SkinFactory(skin_code="AB%2FCD")  # stored URL-encoded
    call = mocked_http.post(
        RENDER_URL,
        json={"ok": True, "svg": SVG, "pngBase64": base64.b64encode(PNG).decode()},
    )

    response = _rerender(staff_client, skin)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["cache_purged"] is False  # Cloudflare not configured in tests
    assert json.loads(call.calls[0].request.body)["skinCode"] == "AB/CD"  # decoded
    assert (tmp_path / f"skins/{skin.id}.svg").read_text() == SVG
    assert (tmp_path / f"skins/{skin.id}.png").read_bytes() == PNG
    assert (tmp_path / f"skins/{skin.id}_thumb.png").read_bytes() == PNG  # no thumb: PNG reused
    kinds = set(SkinImage.objects.filter(skin=skin).values_list("kind", flat=True))
    assert kinds == {"svg", "png", "thumbnail"}
    skin.refresh_from_db()
    assert skin.image_url.endswith(f"skins/{skin.id}.svg")


def test_purges_the_three_files_when_cloudflare_is_configured(staff_client, mocked_http, settings):
    settings.CLOUDFLARE_ZONE_ID = "zone123"
    settings.CLOUDFLARE_CACHE_API_TOKEN = "cf-token"
    settings.BONKVERSE_BASE_URL = "https://bonkverse.io"
    skin = SkinFactory()
    _renders(mocked_http)
    purge = mocked_http.post(PURGE_URL, json={"success": True})

    response = _rerender(staff_client, skin)

    assert response.json()["cache_purged"] is True
    assert json.loads(purge.calls[0].request.body)["files"] == [
        f"https://bonkverse.io/media/skins/{skin.id}.svg",
        f"https://bonkverse.io/media/skins/{skin.id}.png",
        f"https://bonkverse.io/media/skins/{skin.id}_thumb.png",
    ]


def test_failed_purge_still_reports_success(staff_client, mocked_http, settings):
    settings.CLOUDFLARE_ZONE_ID = "zone123"
    settings.CLOUDFLARE_CACHE_API_TOKEN = "cf-token"
    _renders(mocked_http)
    mocked_http.post(PURGE_URL, body=requests.Timeout("slow"))

    response = _rerender(staff_client, SkinFactory())

    assert response.status_code == 200
    assert response.json()["cache_purged"] is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"body": requests.ConnectionError("render service down at 10.0.0.5")},
        {"json": {"ok": False, "error": "internal stack trace here"}},
        {"body": "<html>502</html>", "status": 502},
    ],
)
def test_render_failure_shows_a_sentence_not_service_details(
    staff_client, mocked_http, tmp_path, kwargs
):
    """Regression: the reply used to include the exception text or the
    service's own error body."""
    skin = SkinFactory()
    mocked_http.post(RENDER_URL, **kwargs)

    response = _rerender(staff_client, skin)

    assert response.status_code == 502
    body = response.json()
    assert body == {
        "ok": False,
        "error": "The render service couldn't render this skin. Try again later.",
    }
    assert not (tmp_path / "skins").exists()


def test_unsafe_rendered_svg_changes_nothing(staff_client, mocked_http, tmp_path):
    skin = SkinFactory()
    _renders(mocked_http, svg='<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>')

    response = _rerender(staff_client, skin)

    assert response.status_code == 422
    assert not (tmp_path / "skins").exists()
    assert not SkinImage.objects.filter(skin=skin).exists()


def test_skin_without_code(staff_client):
    response = _rerender(staff_client, SkinFactory(skin_code=""))

    assert response.status_code == 400
    assert "no stored skin code" in response.json()["error"]


def test_missing_skin(staff_client):
    assert staff_client.post("/skins/999999/rerender/").status_code == 404


def test_non_staff_is_forbidden(client, mocked_http):
    client.force_login(UserFactory(username="Regular Player"))

    response = _rerender(client, SkinFactory())

    assert response.status_code == 403
    assert len(mocked_http.calls) == 0
