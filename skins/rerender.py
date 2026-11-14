"""Re-rendering a gallery skin's images from its stored code (staff only).

Owns: re-rendering one skin (`rerender`), used by the staff button
(skins/views/rerender.py, which also asks Cloudflare to drop the old cached
copies) and the rerender_skins command.
Does not own: rendering (integrations/editor_render.py), writing the files and
image rows (skin_media.py), the cache purge request (integrations/cloudflare.py)
or SVG safety rules (svg_sanitizer.py).
"""

import logging
from dataclasses import dataclass


from core.bonk import SkinCode
from integrations.editor_render import render_skin_code
from skins.models import Skin
from skins.skin_media import RenderBundle, save_render
from skins.svg_sanitizer import (
    SVGTooLargeError,
    UnsafeSVGError,
    validate_svg_upload,
)

logger = logging.getLogger(__name__)


class RerenderError:
    """`RerenderResult.error` codes. Every one leaves the skin's old images in place."""

    NO_CODE = "no_code"  # nothing to render from
    RENDER_FAILED = "render_failed"  # the editor's render service failed
    TOO_LARGE = "too_large"  # rendered SVG over the size limit
    UNSAFE = "unsafe_svg"  # rendered SVG failed the safety check
    STORAGE_FAILED = "storage_failed"  # couldn't write the files


@dataclass(frozen=True)
class RerenderResult:
    paths: dict[str, str] | None = None  # {kind: path under MEDIA_ROOT} on success
    error: str | None = None


def rerender(skin: Skin) -> RerenderResult:
    """Render a skin from its stored code and replace its image files and rows.

    Doesn't purge Cloudflare or log an event: the caller decides (one skin,
    or every skin with one purge at the end). Points image_url at the skin's
    own /media/ files, whatever it pointed at before.
    """
    if not skin.skin_code:
        return RerenderResult(error=RerenderError.NO_CODE)

    # Stored codes may be URL-encoded once or twice (BonkLeagues imports).
    result = render_skin_code(SkinCode(skin.skin_code).decoded)
    if result.error:
        logger.warning("rerender skin %s: render failed: %s", skin.id, result.error)
        return RerenderResult(error=RerenderError.RENDER_FAILED)
    rendered = result.skin

    # Same check as every other way a skin's SVG reaches /media/.
    try:
        validate_svg_upload(rendered.svg)
    except SVGTooLargeError:
        return RerenderResult(error=RerenderError.TOO_LARGE)
    except UnsafeSVGError as exc:
        logger.warning("rerender skin %s: rendered SVG rejected: %s", skin.id, exc)
        return RerenderResult(error=RerenderError.UNSAFE)

    # Replaces the files on the media volume; a failed write keeps the old ones.
    bundle = RenderBundle(
        svg=rendered.svg.encode("utf-8"), png=rendered.png, thumbnail=rendered.thumbnail
    )
    try:
        return RerenderResult(paths=save_render(skin, bundle))
    except OSError:
        logger.exception("rerender skin %s: could not write media files", skin.id)
        return RerenderResult(error=RerenderError.STORAGE_FAILED)
