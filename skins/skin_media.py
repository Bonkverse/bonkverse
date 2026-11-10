"""Writing a skin's image files: the one place SVG, PNG and thumbnail land in MEDIA_ROOT.

Owns: where a skin's files live (skins/<id>.svg, <id>.png, <id>_thumb.png),
writing them, the Skin.image_url and SkinImage rows that point at them, and
making PNGs from an SVG when nothing else rendered them.
Does not own: rendering skin codes (integrations/editor_render.py), fetching
from BonkLeagues (integrations/bl_skin_fetcher.py), SVG safety checks
(svg_sanitizer.py; callers validate first), creating or deleting the Skin
row, purging Cloudflare (rerender.py), or serving files (media.py).

Used by: re-render (rerender.py), editor publish (apis/publish_skin.py) and
BonkLeagues/BonxBot import (skin_import.py). The upload form goes through
skin_import too.

The one cleanup rule: all three files are written to temporary names first
and only then moved into place, so a failure leaves whatever was there before
untouched (a re-render that fails keeps the old images) and removes the
temporary files. On success the files, image_url and image rows all match.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import cairosvg
from django.conf import settings

from skins.models import Skin, SkinImage

logger = logging.getLogger(__name__)

PNG_SIZE = 512
THUMBNAIL_SIZE = 128

# SkinImage.kind -> file name pattern under MEDIA_ROOT.
_FILE_NAMES = {
    "svg": "skins/{id}.svg",
    "png": "skins/{id}.png",
    "thumbnail": "skins/{id}_thumb.png",
}


@dataclass(frozen=True)
class RenderBundle:
    """A skin's three images, as bytes."""

    svg: bytes
    png: bytes
    thumbnail: bytes


def bundle_from_svg(svg: bytes) -> RenderBundle:
    """Make the PNG and thumbnail from an SVG locally (cairosvg).

    For SVGs that arrive without renders (the editor's publish). Raises
    whatever cairosvg raises on an SVG it can't draw.
    """
    return RenderBundle(
        svg=svg,
        png=cairosvg.svg2png(bytestring=svg, output_width=PNG_SIZE, output_height=PNG_SIZE),
        thumbnail=cairosvg.svg2png(
            bytestring=svg, output_width=THUMBNAIL_SIZE, output_height=THUMBNAIL_SIZE
        ),
    )


def media_paths(skin_id: int) -> dict[str, str]:
    """{kind: path relative to MEDIA_ROOT} for a skin's three files."""
    return {kind: pattern.format(id=skin_id) for kind, pattern in _FILE_NAMES.items()}


def save_render(skin: Skin, bundle: RenderBundle) -> dict[str, str]:
    """Write a skin's three image files and point the skin and its image rows at them.

    Overwrites existing files (re-render). Callers check the SVG with
    svg_sanitizer first.

    Args:
        skin: a saved Skin.
        bundle: its SVG, PNG and thumbnail.

    Returns:
        {kind: path relative to MEDIA_ROOT} of the files written.

    Raises:
        OSError: a file couldn't be written. Files that were there before are
            unchanged, temporary files are removed, and no row was touched.
    """
    paths = media_paths(skin.id)
    contents = {"svg": bundle.svg, "png": bundle.png, "thumbnail": bundle.thumbnail}
    _write_all({paths[kind]: contents[kind] for kind in paths})

    skin.image_url = f"{settings.MEDIA_URL}{paths['svg']}"
    skin.save(update_fields=["image_url"])
    _point_image_rows(skin, paths)
    return paths


def _write_all(files: dict[str, bytes]) -> None:
    """Write every file to a temporary name, then move each into place."""
    os.makedirs(os.path.join(settings.MEDIA_ROOT, "skins"), exist_ok=True)
    staged = []  # (temporary path, final path)
    try:
        for rel_path, content in files.items():
            final = os.path.join(settings.MEDIA_ROOT, rel_path)
            temporary = f"{final}.tmp"
            with open(temporary, "wb") as f:
                f.write(content)
            staged.append((temporary, final))
    except OSError:
        for temporary, _ in staged:
            _remove_quietly(temporary)
        _remove_quietly(f"{final}.tmp")  # the one that failed mid-write
        raise
    # os.replace is atomic per file on one filesystem (the media volume).
    for temporary, final in staged:
        os.replace(temporary, final)


def _point_image_rows(skin: Skin, paths: dict[str, str]) -> None:
    """One SkinImage row per kind, with the current path (created or updated)."""
    existing = {row.kind: row for row in SkinImage.objects.filter(skin=skin, kind__in=paths)}
    SkinImage.objects.bulk_create(
        [
            SkinImage(skin=skin, kind=kind, path=path)
            for kind, path in paths.items()
            if kind not in existing
        ]
    )
    for kind, row in existing.items():
        if row.path != paths[kind]:
            row.path = paths[kind]
            row.save(update_fields=["path"])


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("could not remove temporary media file %s", path)
