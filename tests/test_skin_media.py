"""Writing a skin's image files (skins/skin_media.py), shared by re-render,
editor publish and BonkLeagues/BonxBot import.

The rule under test: all three files land together or none change. A failed
write leaves the old files and rows alone and no temporary files behind.
"""

import builtins
import re
import struct
from pathlib import Path

import pytest

from skins.models import Skin, SkinImage
from skins.skin_media import (
    PNG_SIZE,
    THUMBNAIL_SIZE,
    RenderBundle,
    bundle_from_svg,
    media_paths,
    save_render,
)
from tests.factories import SkinFactory

REPO = Path(__file__).resolve().parent.parent
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><circle cx="5" cy="5" r="4" fill="red"/></svg>'

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def _bundle(tag=b"1"):
    return RenderBundle(svg=b"<svg>" + tag + b"</svg>", png=b"png" + tag, thumbnail=b"th" + tag)


def _files(tmp_path, skin):
    return {kind: (tmp_path / rel).read_bytes() for kind, rel in media_paths(skin.id).items()}


def test_writes_three_files_and_points_the_skin_at_them(tmp_path):
    skin = SkinFactory(image_url="")

    paths = save_render(skin, _bundle())

    assert paths == {
        "svg": f"skins/{skin.id}.svg",
        "png": f"skins/{skin.id}.png",
        "thumbnail": f"skins/{skin.id}_thumb.png",
    }
    assert _files(tmp_path, skin) == {"svg": b"<svg>1</svg>", "png": b"png1", "thumbnail": b"th1"}
    skin.refresh_from_db()
    assert skin.image_url == f"/media/skins/{skin.id}.svg"
    assert dict(SkinImage.objects.filter(skin=skin).values_list("kind", "path")) == paths


def test_saving_again_overwrites_and_keeps_one_row_per_kind(tmp_path):
    skin = SkinFactory()
    save_render(skin, _bundle(b"1"))
    row_ids = set(SkinImage.objects.filter(skin=skin).values_list("id", flat=True))

    save_render(skin, _bundle(b"2"))

    assert _files(tmp_path, skin)["png"] == b"png2"
    assert set(SkinImage.objects.filter(skin=skin).values_list("id", flat=True)) == row_ids


def test_a_failed_write_keeps_the_old_files_and_rows(tmp_path, monkeypatch):
    skin = SkinFactory()
    save_render(skin, _bundle(b"old"))
    real_open = builtins.open

    def fail_on_thumbnail(path, *args, **kwargs):
        if str(path).endswith("_thumb.png.tmp"):
            raise OSError("disk full")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("skins.skin_media.open", fail_on_thumbnail, raising=False)

    with pytest.raises(OSError):
        save_render(skin, _bundle(b"new"))

    assert _files(tmp_path, skin) == {
        "svg": b"<svg>old</svg>",
        "png": b"pngold",
        "thumbnail": b"thold",
    }
    assert not list((tmp_path / "skins").glob("*.tmp"))
    assert SkinImage.objects.filter(skin=skin).count() == 3


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_bundle_from_svg_draws_png_and_thumbnail():
    bundle = bundle_from_svg(SVG)

    assert bundle.svg == SVG
    assert _png_size(bundle.png) == (PNG_SIZE, PNG_SIZE)
    assert _png_size(bundle.thumbnail) == (THUMBNAIL_SIZE, THUMBNAIL_SIZE)


def test_publish_with_an_undrawable_svg_creates_no_skin(client, monkeypatch):
    from tests.factories import UserFactory

    client.force_login(UserFactory(username="Maker"))

    def cannot_draw(svg):
        raise ValueError("bad svg")

    monkeypatch.setattr("skins.apis.publish_skin.bundle_from_svg", cannot_draw)
    count = Skin.objects.count()

    response = client.post(
        "/api/publish-skin/", {"skin_name": "My Skin", "skin_code": "CODE", "svg": SVG.decode()}
    )

    assert response.status_code == 500
    assert Skin.objects.count() == count


def test_only_skin_media_writes_skin_images():
    """One home for writing image rows: skin_media.py (plus the old backfill command)."""
    allowed = {
        REPO / "skins" / "skin_media.py",
        REPO / "skins" / "management" / "commands" / "populate_skin_images.py",
    }
    skip = {"tests", "migrations", "staticfiles", "media", "backups", "node_modules", ".git"}
    pattern = re.compile(
        r"(?<!class )SkinImage\(|SkinImage\.objects\.(create|bulk_create|update_or_create)"
    )
    offenders = [
        str(path.relative_to(REPO))
        for path in REPO.rglob("*.py")
        if skip.isdisjoint(path.relative_to(REPO).parts)
        and path not in allowed
        and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"write skin images with skins.skin_media.save_render: {offenders}"
