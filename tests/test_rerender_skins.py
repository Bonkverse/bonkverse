"""`manage.py rerender_skins`: bulk re-render from stored codes, then one
Cloudflare purge (skins/management/commands/rerender_skins.py)."""

import base64
import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from integrations import cloudflare
from skins.models import SkinImage
from skins.skin_media import RenderBundle, file_problems, save_render
from tests.factories import SkinFactory

pytestmark = pytest.mark.django_db

EDITOR = "https://editor.test"
RENDER_URL = f"{EDITOR}/api/render-bundle"
PURGE_URL = "https://api.cloudflare.com/client/v4/zones/zone123/purge_cache"
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture(autouse=True)
def _settings(settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = tmp_path
    (tmp_path / "skins").mkdir()
    settings.BONKVERSE_RENDER_URL = EDITOR
    settings.CLOUDFLARE_ZONE_ID = ""
    settings.CLOUDFLARE_CACHE_API_TOKEN = ""
    monkeypatch.setattr("skins.management.commands.rerender_skins.time.sleep", lambda s: None)


def _renders_ok(mocked_http, times=None):
    body = {"ok": True, "svg": SVG, "pngBase64": base64.b64encode(PNG).decode()}
    mocked_http.post(RENDER_URL, json=body)


def _run(*args):
    out = StringIO()
    call_command("rerender_skins", *args, stdout=out)
    return out.getvalue()


def _healthy(skin):
    save_render(skin, RenderBundle(svg=SVG.encode(), png=PNG, thumbnail=PNG))


class TestFileProblems:
    def test_missing_empty_and_wrong_type(self, tmp_path):
        skin = SkinFactory()
        (tmp_path / f"skins/{skin.id}.svg").write_bytes(b"")
        (tmp_path / f"skins/{skin.id}.png").write_bytes(b"<html>nope</html>")

        assert file_problems(skin.id) == ["svg: empty", "png: not a PNG", "thumbnail: missing"]

    def test_healthy_files(self):
        skin = SkinFactory()
        _healthy(skin)

        assert file_problems(skin.id) == []


class TestDryRun:
    def test_counts_and_changes_nothing(self, mocked_http):
        healthy, broken = SkinFactory(), SkinFactory(image_url="https://bonkleagues.io/x.svg")
        _healthy(healthy)
        SkinFactory(skin_code="")

        out = _run()

        assert "Dry run: nothing changed." in out
        assert "skins: 3" in out
        assert "no code (can't re-render): 1" in out
        assert "with a code, files look broken: 1" in out
        assert "image_url outside /media/ (will switch to /media/): 1" in out
        assert f"svg: missing: skins [{broken.id}]" in out
        assert len(mocked_http.calls) == 0

    def test_warns_when_there_is_no_media_folder(self, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path / "elsewhere"

        assert "Run this on the bonkverse service" in _run()


class TestRun:
    def test_rerenders_every_skin_with_a_code(self, mocked_http, tmp_path):
        _renders_ok(mocked_http)
        external = SkinFactory(image_url="https://bonkleagues.io/x.svg")
        other = SkinFactory()
        SkinFactory(skin_code="")

        out = _run("--run")

        assert "Re-rendered 2 skin(s)." in out
        assert len(mocked_http.calls) == 2
        for skin in (external, other):
            skin.refresh_from_db()
            assert skin.image_url == f"/media/skins/{skin.id}.svg"
            assert file_problems(skin.id) == []
            assert SkinImage.objects.filter(skin=skin).count() == 3

    def test_only_broken(self, mocked_http):
        _renders_ok(mocked_http)
        healthy, broken = SkinFactory(), SkinFactory()
        _healthy(healthy)

        _run("--run", "--only-broken")

        assert len(mocked_http.calls) == 1
        assert file_problems(broken.id) == []

    def test_start_after_and_limit(self, mocked_http):
        _renders_ok(mocked_http)
        first, second, third = SkinFactory(), SkinFactory(), SkinFactory()

        _run("--run", "--start-after", str(first.id), "--limit", "1")

        assert len(mocked_http.calls) == 1
        assert file_problems(second.id) == []
        assert file_problems(third.id) != []

    def test_a_failed_skin_keeps_its_images_and_is_listed(self, mocked_http):
        mocked_http.post(RENDER_URL, json={"ok": False, "error": "bad code"}, status=422)
        skin = SkinFactory()
        _healthy(skin)
        before = skin.image_url

        out = _run("--run")

        assert f"render_failed: 1: {skin.id}" in out
        skin.refresh_from_db()
        assert skin.image_url == before
        assert file_problems(skin.id) == []

    def test_stops_when_the_render_service_keeps_failing(self, mocked_http):
        mocked_http.post(RENDER_URL, json={"ok": False}, status=503)
        skins = [SkinFactory() for _ in range(5)]

        out = _run("--run", "--max-failures", "3", "--purge-cache")

        assert len(mocked_http.calls) == 3
        assert f"Resume with --start-after {skins[0].id - 1}" in out
        assert "Not purging Cloudflare: the run stopped early." in out

    def test_refuses_to_run_without_the_media_folder(self, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path / "elsewhere"

        with pytest.raises(CommandError, match="bonkverse service"):
            _run("--run")


class TestPurge:
    def test_purges_everything_once_at_the_end(self, mocked_http, settings):
        settings.CLOUDFLARE_ZONE_ID = "zone123"
        settings.CLOUDFLARE_CACHE_API_TOKEN = "cf-token"
        _renders_ok(mocked_http)
        mocked_http.post(PURGE_URL, json={"success": True})
        SkinFactory(), SkinFactory()

        out = _run("--run", "--purge-cache")

        purges = [c for c in mocked_http.calls if c.request.url == PURGE_URL]
        assert len(purges) == 1
        assert json.loads(purges[0].request.body) == {"purge_everything": True}
        assert "Cloudflare cache emptied." in out

    def test_no_purge_without_the_flag(self, mocked_http, settings):
        settings.CLOUDFLARE_ZONE_ID = "zone123"
        settings.CLOUDFLARE_CACHE_API_TOKEN = "cf-token"
        _renders_ok(mocked_http)
        SkinFactory()

        _run("--run")

        assert all(c.request.url != PURGE_URL for c in mocked_http.calls)

    def test_purge_everything_reports_failure(self, mocked_http):
        mocked_http.post(
            PURGE_URL, json={"success": False, "errors": [{"code": 10000}]}, status=403
        )

        result = cloudflare.purge_everything("zone123", "cf-token")

        assert result.ok is False and result.error == "status_403"

    def test_purge_everything_skips_when_unconfigured(self, mocked_http):
        assert cloudflare.purge_everything("", "").skipped is True
        assert len(mocked_http.calls) == 0
