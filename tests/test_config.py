"""Service URLs and keys come from settings, so each environment can point at its own.

RFC-0001 Phase 1: before this, URLs were hardcoded in views and templates, so a
local server linked to (and re-rendered through) production.
"""

import pytest
import requests

from tests.factories import SkinFactory

pytestmark = pytest.mark.django_db


class TestLinksStayOnThisSite:
    """Share and detail links pointed at https://bonkverse.io, so clicking them
    on a local or staging server jumped to production."""

    def test_search_results_link_relatively(self, client):
        skin = SkinFactory(name="Dragon")

        html = client.get("/search/?q=Dragon").content.decode()

        assert f'href="/skins/share/{skin.id}/{skin.uuid}/"' in html
        assert f'href="/skins/detail/{skin.id}"' in html
        assert "https://bonkverse.io/skins/" not in html

    def test_profile_and_favorites_link_relatively(self, logged_in_client, user):
        SkinFactory(creator=user.username)

        html = logged_in_client.get("/my-profile/").content.decode()

        assert "https://bonkverse.io/skins/" not in html


class TestServiceUrls:
    def test_rerender_uses_render_service_not_editor_link(
        self, staff_client, mocked_http, settings
    ):
        settings.BONKVERSE_EDITOR_URL = "http://localhost:5173"
        settings.BONKVERSE_RENDER_URL = "https://render.example"
        call = mocked_http.post(
            "https://render.example/api/render-bundle", json={"ok": False, "error": "x"}
        )
        skin = SkinFactory()

        staff_client.post(f"/skins/{skin.id}/rerender/")

        assert len(call.calls) == 1

    def test_matchmaking_uses_bonkbot_setting(self, client, mocked_http, settings):
        settings.BONKBOT_API_URL = "https://bonkbot.example"
        call = mocked_http.post("https://bonkbot.example/join-matchmaking", json={"ok": True})

        client.post("/api/join-matchmaking/", data="{}", content_type="application/json")

        assert len(call.calls) == 1

    def test_map_decoder_unconfigured_is_503(self, client, settings):
        settings.DECODER_SERVICE_URL = ""

        response = client.post("/api/tools/map-decode/", {"encoded": "abc"})

        assert response.status_code == 503

    def test_map_decoder_uses_settings_and_key(self, client, mocked_http, settings):
        settings.DECODER_SERVICE_URL = "https://decoder.example"
        settings.DECODER_SERVICE_KEY = "k-123"
        call = mocked_http.post("https://decoder.example/decode/map", json={"map": {}})

        response = client.post("/api/tools/map-decode/", {"encoded": "abc"})

        assert response.status_code == 200
        assert call.calls[0].request.headers["X-Decoder-Key"] == "k-123"

    def test_map_decoder_failure_hides_details(self, client, mocked_http, settings):
        settings.DECODER_SERVICE_URL = "https://decoder.example"
        mocked_http.post(
            "https://decoder.example/decode/map", body=requests.ConnectionError("internal-host:9")
        )

        response = client.post("/api/tools/map-decode/", {"encoded": "abc"})

        assert response.status_code == 502
        assert b"internal-host" not in response.content


def test_app_code_does_not_read_the_environment_directly():
    """Config is read once, in settings.py. Management commands are exempt."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    offenders = [
        str(path.relative_to(root))
        for folder in ("skins", "core")
        for path in (root / folder).rglob("*.py")
        if "management" not in path.parts
        and "migrations" not in path.parts
        and any(
            needle in line and not line.lstrip().startswith("#")
            for line in path.read_text().splitlines()
            for needle in ("os.getenv(", "os.environ")
        )
    ]

    assert offenders == []
