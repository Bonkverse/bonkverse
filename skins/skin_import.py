"""Importing a BonkLeagues skin that was submitted somewhere other than the upload form.

Owns: turning a BonkLeagues link plus a name, creator and (usually) its skin
code into a Skin with its SVG, PNG and thumbnail files; treating an
already-imported link as a duplicate; and cleaning names the upload form would
have refused.
Used by: the BonxBot submission API (skins/apis/bot_skins.py) and the one-time
migration (management command import_bonxbot_skins).
Does not own: HTTP to the editor or the fetcher (integrations/), authentication,
or event logging (the caller knows who submitted).

Where the images come from: when the caller already has the skin code, the
editor renders it and BonkLeagues is never contacted. Only a submission without
a code falls back to BLSkinFetcher, which reads the link from BonkLeagues.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction

from core.bonk import SkinCode
from integrations.bl_skin_fetcher import FetchResult, fetch_skin
from integrations.editor_render import RenderResult, render_skin_code
from skins.models import Skin, SkinImage
from skins.svg_sanitizer import UnsafeSVGError, validate_svg_upload

logger = logging.getLogger(__name__)

BONKLEAGUES_HOSTS = {"bonkleagues.io", "www.bonkleagues.io"}
LINK_MAX_LENGTH = Skin._meta.get_field("link").max_length
NAME_MAX_LENGTH = Skin._meta.get_field("name").max_length
CREATOR_MAX_LENGTH = Skin._meta.get_field("creator").max_length
DEFAULT_NAME = "UnnamedSkin"
DEFAULT_CREATOR = "UnknownSkinCreator"

# Same characters the upload form and the editor accept.
_NOT_ALLOWED_IN_NAME = re.compile(r"[^A-Za-z0-9 _]")
_RUNS_OF_SPACES = re.compile(r" {2,}")


class ImportFailure:
    """Error codes in `ImportResult.error`. PERMANENT ones will fail the same way on retry."""

    INVALID_LINK = "invalid_link"
    LINK_TOO_LONG = "link_too_long"
    UNSAFE_SVG = "unsafe_svg"
    RENDER_FAILED = "render_failed"  # editor down or could not render the code
    FETCH_FAILED = "fetch_failed"  # no code given; fetcher down or could not read the link
    STORAGE_FAILED = "storage_failed"

    PERMANENT = {INVALID_LINK, LINK_TOO_LONG, UNSAFE_SVG}


@dataclass(frozen=True)
class ImportResult:
    skin: Skin | None = None
    created: bool = False
    error: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class _Media:
    skin_code: str
    svg: str
    png: bytes
    thumbnail: bytes


def clean_skin_name(raw: str | None) -> str:
    """Drop characters the site does not allow in names; never returns an empty name.

    "Fire🔥Dragon!!" -> "FireDragon". Discord lets people type anything, but the
    rest of the site (search, share links, editor) assumes the upload form's rules.
    """
    name = _NOT_ALLOWED_IN_NAME.sub("", raw or "")
    name = _RUNS_OF_SPACES.sub(" ", name).strip()
    return name[:NAME_MAX_LENGTH] or DEFAULT_NAME


def clean_creator(raw: str | None) -> str:
    """Keep the creator exactly as given (bonk.io names contain spaces) unless it is blank."""
    if not raw or not raw.strip():
        return DEFAULT_CREATOR
    return raw[:CREATOR_MAX_LENGTH]


def link_problem(link: str) -> str | None:
    """The permanent error for this link, or None if it can be imported."""
    parsed = urlparse(link)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in BONKLEAGUES_HOSTS:
        return ImportFailure.INVALID_LINK
    if len(link) > LINK_MAX_LENGTH:
        return ImportFailure.LINK_TOO_LONG
    return None


def existing_skin(link: str) -> Skin | None:
    """The skin already imported from this exact link (the upload form's duplicate rule)."""
    return Skin.objects.filter(link=link).order_by("id").first()


def import_bonkleagues_skin(
    link: str,
    name: str | None,
    creator: str | None,
    *,
    skin_code: str | None = None,
    render: Callable[[str], RenderResult] = render_skin_code,
    fetch: Callable[[str], FetchResult] = fetch_skin,
) -> ImportResult:
    """Create a Skin from a BonkLeagues submission, or return the one already imported from it.

    Duplicates are matched on the exact link, so a skin uploaded on the site and
    later submitted on Discord is stored once, and nothing is rendered for it.
    """
    link = (link or "").strip()
    problem = link_problem(link)
    if problem:
        return ImportResult(error=problem)

    existing = existing_skin(link)
    if existing:
        return ImportResult(skin=existing, created=False)

    media, error, detail = _get_media(link, (skin_code or "").strip(), render, fetch)
    if error:
        return ImportResult(error=error, detail=detail)

    try:
        validate_svg_upload(media.svg)
    except UnsafeSVGError as exc:
        return ImportResult(error=ImportFailure.UNSAFE_SVG, detail=str(exc))

    try:
        skin = _save(link, clean_skin_name(name), clean_creator(creator), media)
    except Exception:
        logger.exception("could not store imported skin %s", link)
        return ImportResult(error=ImportFailure.STORAGE_FAILED)
    return ImportResult(skin=skin, created=True)


def _get_media(link, skin_code, render, fetch):
    """(media, error, detail): render the code if we have one, otherwise ask BonkLeagues."""
    if skin_code:
        code = SkinCode(skin_code).decoded  # bot codes may be URL-encoded once or twice
        rendered = render(code)
        if rendered.error:
            return None, ImportFailure.RENDER_FAILED, rendered.error
        r = rendered.skin
        return _Media(code, r.svg, r.png, r.thumbnail), None, ""

    fetched = fetch(link)
    if fetched.error:
        return None, ImportFailure.FETCH_FAILED, fetched.error
    f = fetched.skin
    return _Media(f.skin_code, f.svg, f.png, f.thumbnail), None, ""


def _save(link, name, creator, media: _Media) -> Skin:
    """Write the row and its three files together; on any failure keep neither."""
    written = []
    try:
        with transaction.atomic():
            skin = Skin.objects.create(
                name=name,
                creator=creator,
                link=link,
                skin_code=media.skin_code,
                image_url="",
                uuid=uuid.uuid4(),
            )
            files = {
                "svg": (f"skins/{skin.id}.svg", media.svg.encode("utf-8")),
                "png": (f"skins/{skin.id}.png", media.png),
                "thumbnail": (f"skins/{skin.id}_thumb.png", media.thumbnail),
            }
            os.makedirs(os.path.join(settings.MEDIA_ROOT, "skins"), exist_ok=True)
            for rel_path, content in files.values():
                full_path = os.path.join(settings.MEDIA_ROOT, rel_path)
                with open(full_path, "wb") as f:
                    f.write(content)
                written.append(full_path)

            skin.image_url = f"{settings.MEDIA_URL}{files['svg'][0]}"
            skin.save(update_fields=["image_url"])
            SkinImage.objects.bulk_create(
                [SkinImage(skin=skin, kind=kind, path=rel) for kind, (rel, _) in files.items()]
            )
            return skin
    except Exception:
        for path in written:
            if os.path.exists(path):
                os.remove(path)
        raise
