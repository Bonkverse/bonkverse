"""Skin files under /media/: served with cache headers and rate limited.

Regression (2026-11-03): one client fetched ~30k skin images in under an hour.
/media/ had no rate limit, and the audit skipped it.
"""

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def media_file(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    (tmp_path / "skins").mkdir()
    (tmp_path / "skins" / "1.png").write_bytes(b"\x89PNG fake")
    return "/media/skins/1.png"


def test_serves_file_with_cache_headers(client, media_file):
    response = client.get(media_file)

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"\x89PNG fake"
    assert response["Cache-Control"] == "public, max-age=3600, s-maxage=604800"


def test_missing_file_is_404_and_not_cacheable(client, media_file):
    response = client.get("/media/skins/999.png")

    assert response.status_code == 404
    assert "s-maxage" not in response.get("Cache-Control", "")


def test_cannot_escape_media_root(client, media_file):
    assert client.get("/media/../settings.py").status_code in (400, 404)


def test_scraping_is_rate_limited(client, media_file, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, "media": "3/m"}

    codes = [client.get(media_file).status_code for _ in range(4)]

    assert codes == [200, 200, 200, 429]


def test_media_route_is_covered_by_the_rate_limit_audit():
    from skins.management.commands.audit_rate_limits import collect_rows

    tiers = {route: tier for route, _view, tier, _rate, _methods in collect_rows()}

    assert tiers["/media/<path:path>"] == "media"


class TestBulkAccessNote:
    """Hitting the media limit invites the collector to ask instead of scraping."""

    @pytest.fixture
    def limited(self, client, media_file, settings):
        settings.RATE_LIMITS = {**settings.RATE_LIMITS, "media": "1/m"}
        client.get(media_file)
        return client

    def test_media_429_page_points_to_discord(self, limited, media_file, settings):
        response = limited.get(media_file)

        assert response.status_code == 429
        assert b"Collecting Bonkverse skins?" in response.content
        assert settings.BONKVERSE_DISCORD_URL.encode() in response.content

    def test_media_429_json_includes_contact(self, limited, media_file, settings):
        response = limited.get(media_file, HTTP_ACCEPT="application/json")

        assert response.status_code == 429
        assert response.json()["contact"] == settings.BONKVERSE_DISCORD_URL

    def test_other_limits_do_not_show_the_note(self, client, settings):
        settings.RATE_LIMITS = {**settings.RATE_LIMITS, "browse": "1/m"}
        client.get("/categories/")

        response = client.get("/categories/")

        assert response.status_code == 429
        assert b"Collecting Bonkverse skins?" not in response.content
