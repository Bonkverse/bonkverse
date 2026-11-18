"""The skins app's public operations for other apps.

Owns: images for a skin code that isn't a gallery skin (a player's worn
skin), rendered once per code by the editor's render service and kept on
the media volume (skin_media.py writes them); and adding a skin to someone's
collection (their favorites) from a BonkLeagues link or a skin id, uploading
it first if Bonkverse doesn't have it (`collect`, for BonxBot).
Does not own: gallery skins' own images (skin_media.save_render via
rerender.py, skin_import.py, views/publish.py) or serving /media/ (views/media.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.core.cache import cache

from core.bonk import InvalidSkinCode, SkinCode
from integrations.editor_render import render_skin_code

from . import skin_media
from .models import CreatorSource, Skin, SubmissionSource
from .submitters import Submission, discord_id_or_none  # noqa: F401 - the id parser is for other apps

logger = logging.getLogger(__name__)

# One render per code at a time: a page of avatars asks for many at once.
_RENDER_LOCK_SECONDS = 45
# After a failed render, don't ask the render service about that code again
# for a while; the page shows initials meanwhile.
_FAILURE_BACKOFF_SECONDS = 10 * 60

CODE_IMAGE_KINDS = skin_media.CODE_IMAGE_KINDS
code_digest = skin_media.code_digest


def code_image(skin_code: str, kind: str) -> str | None:
    """Path under MEDIA_ROOT of a skin code's image, rendering it on first use.

    Args:
        skin_code: A skin code, URL-encoded or not. Must parse as a skin.
        kind: "png" (512 px) or "thumbnail" (128 px).

    Returns:
        The path, or None when there's no image yet: the code isn't a skin,
        the render failed recently, another request is rendering it, or
        the files couldn't be written. Never raises for those.
    """
    if kind not in CODE_IMAGE_KINDS:
        raise ValueError(f"unknown code image kind {kind!r}")
    try:
        SkinCode(skin_code).parse()
    except (InvalidSkinCode, ValueError):
        return None

    path = skin_media.code_media_path(skin_code, kind)
    if skin_media.code_images_exist(skin_code):
        return path

    digest = skin_media.code_digest(skin_code)
    failed_key = f"skin_code_image:failed:{digest}"
    lock_key = f"skin_code_image:rendering:{digest}"
    try:
        if cache.get(failed_key) or not cache.add(lock_key, 1, timeout=_RENDER_LOCK_SECONDS):
            return None
    except Exception:
        # Cache down: render anyway rather than show no skins at all.
        lock_key = None
    try:
        if _render_and_save(skin_code, digest):
            return path
        _remember_failure(failed_key)
        return None
    finally:
        if lock_key:
            try:
                cache.delete(lock_key)
            except Exception:
                pass


def _render_and_save(skin_code: str, digest: str) -> bool:
    result = render_skin_code(SkinCode(skin_code).decoded)
    if result.error:
        logger.warning("skin code image %s: render failed: %s", digest, result.error)
        return False
    rendered = result.skin
    if not (skin_media.is_png(rendered.png) and skin_media.is_png(rendered.thumbnail)):
        logger.warning("skin code image %s: render service sent something other than PNGs", digest)
        return False
    try:
        skin_media.save_code_render(skin_code, rendered.png, rendered.thumbnail)
    except OSError:
        logger.exception("skin code image %s: could not write media files", digest)
        return False
    return True


def _remember_failure(key: str) -> None:
    try:
        cache.set(key, 1, timeout=_FAILURE_BACKOFF_SECONDS)
    except Exception:
        pass


# --- collections -------------------------------------------------------------------


@dataclass(frozen=True)
class Collected:
    skin: Skin | None = None
    uploaded: bool = False  # it wasn't on Bonkverse until now
    already: bool = False  # it was already in their collection
    error: str | None = None  # "skin_not_found", "missing_skin", or an ImportFailure code


def collect(user, *, link: str | None = None, skin_id=None, discord_user_id=None) -> Collected:
    """Add a skin to `user`'s collection, by Bonkverse id or BonkLeagues link.

    A link Bonkverse doesn't have yet is imported first, named and credited
    the way BonkLeagues lists it: the person collecting isn't claiming to have
    made it. Adding a skin that's already collected changes nothing.
    """
    from .skin_import import import_as_listed

    uploaded = False
    if skin_id is not None:
        try:
            skin = Skin.objects.filter(id=int(skin_id)).first()
        except (TypeError, ValueError):
            skin = None
        if skin is None:
            return Collected(error="skin_not_found")
    elif isinstance(link, str) and link.strip():
        submission = Submission(
            source=SubmissionSource.DISCORD,
            creator_source=CreatorSource.BONKLEAGUES,
            discord_user_id=discord_user_id,
        )
        result = import_as_listed(link.strip(), submission)
        if result.error:
            return Collected(error=result.error)
        skin, uploaded = result.skin, result.created
    else:
        return Collected(error="missing_skin")

    already = skin.favorited_by.filter(pk=user.pk).exists()
    if not already:
        skin.favorited_by.add(user)
    return Collected(skin=skin, uploaded=uploaded, already=already)
