"""Importing a BonkLeagues skin that was submitted somewhere other than the upload form.

Owns: turning a BonkLeagues link plus a name, creator and (usually) its skin
code into a Skin with its SVG, PNG and thumbnail files; deciding when a
submission is a duplicate; and cleaning names the upload form would have refused.
Used by: the BonxBot submission API (skins/apis/bot_skins.py) and the one-time
migration (skins/bonxbot_migration.py).
Does not own: HTTP to the editor or the fetcher (integrations/), authentication,
or event logging (the caller knows who submitted).

Where the images come from: when the caller already has the skin code, the
editor renders it and BonkLeagues is never contacted. Only a submission without
a code falls back to BLSkinFetcher, which reads the link from BonkLeagues.

Duplicates: two links that point at the same BonkLeagues skin are the same
skin, however they are written (http/https, www., a trailing slash, tracking
parameters on a short link). New skins store the canonical form; older rows are
matched in any of the spellings above. Imports of the same link are serialized
with a Postgres advisory lock, so two at once (the bot's instant push and its
retry loop, say) produce one skin, not two.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from django.conf import settings
from django.db import connection, transaction

from core.bonk import InvalidSkinCode, SkinCode
from integrations.bl_skin_fetcher import FetchResult, fetch_skin
from integrations.editor_render import RenderResult, render_skin_code
from skins.models import Skin
from skins.skin_media import RenderBundle, save_render
from skins.svg_sanitizer import SVGTooLargeError, UnsafeSVGError, validate_svg_upload

logger = logging.getLogger(__name__)

BONKLEAGUES_HOSTS = {"bonkleagues.io", "www.bonkleagues.io"}
CANONICAL_ORIGIN = "https://bonkleagues.io"
LINK_MAX_LENGTH = Skin._meta.get_field("link").max_length
NAME_MAX_LENGTH = Skin._meta.get_field("name").max_length
CREATOR_MAX_LENGTH = Skin._meta.get_field("creator").max_length
DEFAULT_NAME = "UnnamedSkin"
DEFAULT_CREATOR = "UnknownSkinCreator"

# A BonkLeagues short link: /s/<code>. The code is case-sensitive, so it is never lowercased.
_SHORT_LINK_PATH = re.compile(r"^/s/([A-Za-z0-9]+)$")
# Same characters the upload form and the editor accept.
_NOT_ALLOWED_IN_NAME = re.compile(r"[^A-Za-z0-9 _]")
_RUNS_OF_SPACES = re.compile(r" {2,}")
# First half of every advisory lock key taken here, so these locks can't collide
# with advisory locks anything else takes on the same database.
_LOCK_NAMESPACE = 0x426B5653  # "BkVS"


class ImportFailure:
    """Error codes in `ImportResult.error`. PERMANENT ones will fail the same way on retry."""

    INVALID_LINK = "invalid_link"
    LINK_TOO_LONG = "link_too_long"
    UNSAFE_SVG = "unsafe_svg"
    SVG_TOO_LARGE = "svg_too_large"  # rendered skin is over the size limit
    RENDER_FAILED = "render_failed"  # editor down or could not render the code
    FETCH_FAILED = "fetch_failed"  # no code given; fetcher down or could not read the link
    STORAGE_FAILED = "storage_failed"
    INVALID_SKIN_CODE = "invalid_skin_code"  # the given code isn't a bonk.io skin

    PERMANENT = {INVALID_LINK, LINK_TOO_LONG, UNSAFE_SVG, SVG_TOO_LARGE, INVALID_SKIN_CODE}


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


def canonical_link(raw: str | None) -> str | None:
    """One spelling per BonkLeagues skin, or None if this is not a BonkLeagues link.

    "http://www.bonkleagues.io/s/AbC1234/?ref=discord" -> "https://bonkleagues.io/s/AbC1234"
    Any other BonkLeagues URL keeps its path and query (they may carry the skin)
    but loses the scheme, www., trailing slash and #fragment differences.
    """
    parsed = urlparse((raw or "").strip())
    if parsed.scheme not in ("http", "https"):
        return None
    if (parsed.hostname or "").lower() not in BONKLEAGUES_HOSTS:
        return None

    path = parsed.path.rstrip("/")
    short = _SHORT_LINK_PATH.match(path)
    if short:
        return f"{CANONICAL_ORIGIN}/s/{short.group(1)}"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{CANONICAL_ORIGIN}{path}{query}"


def link_problem(raw: str | None) -> str | None:
    """The permanent error for this link, or None if it can be imported."""
    link = canonical_link(raw)
    if link is None:
        return ImportFailure.INVALID_LINK
    if len(link) > LINK_MAX_LENGTH:
        return ImportFailure.LINK_TOO_LONG
    return None


def existing_skin(raw: str | None) -> Skin | None:
    """The skin already imported from this BonkLeagues link, in any spelling (oldest first)."""
    link = canonical_link(raw)
    if link is None:
        return None
    return Skin.objects.filter(link__in=_stored_spellings(link)).order_by("id").first()


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

    A skin uploaded on the site and later submitted on Discord is stored once,
    and nothing is rendered for the duplicate.
    """
    problem = link_problem(link)
    if problem:
        return ImportResult(error=problem)
    link = canonical_link(link)

    with _import_lock(link):
        existing = existing_skin(link)
        if existing:
            return ImportResult(skin=existing, created=False)

        media, error, detail = _get_media(link, (skin_code or "").strip(), render, fetch)
        if error:
            return ImportResult(error=error, detail=detail)

        try:
            validate_svg_upload(media.svg)
        except SVGTooLargeError as exc:
            return ImportResult(error=ImportFailure.SVG_TOO_LARGE, detail=str(exc))
        except UnsafeSVGError as exc:
            return ImportResult(error=ImportFailure.UNSAFE_SVG, detail=str(exc))

        try:
            skin = _save(link, clean_skin_name(name), clean_creator(creator), media)
        except Exception:
            logger.exception("could not store imported skin %s", link)
            return ImportResult(error=ImportFailure.STORAGE_FAILED)
        return ImportResult(skin=skin, created=True)


def _stored_spellings(link: str) -> list[str]:
    """Every way an older row may have stored this canonical link."""
    rest = link.removeprefix(CANONICAL_ORIGIN)
    hosts = [f"{scheme}://{host}" for scheme in ("https", "http") for host in BONKLEAGUES_HOSTS]
    spellings = [f"{origin}{rest}" for origin in hosts]
    if _SHORT_LINK_PATH.match(rest):
        spellings += [f"{s}/" for s in spellings]
    return spellings


@contextmanager
def _import_lock(link: str):
    """Hold a Postgres advisory lock for this link until the import finishes.

    Session-level (not tied to a transaction) so no transaction stays open while
    the editor renders; released in `finally`, and by Postgres if the connection drops.
    """
    digest = hashlib.blake2b(link.encode("utf-8"), digest_size=4).digest()
    key = int.from_bytes(digest, "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, key])
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_LOCK_NAMESPACE, key])


def _get_media(link, skin_code, render, fetch):
    """(media, error, detail): render the code if we have one, otherwise ask BonkLeagues."""
    if skin_code:
        given = SkinCode(skin_code)
        try:
            given.parse()  # refuse text or other data posing as a code
        except InvalidSkinCode as exc:
            return None, ImportFailure.INVALID_SKIN_CODE, exc.reason
        code = given.decoded  # bot codes may be URL-encoded once or twice
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
    """Write the row and its three files together; on any failure keep neither.

    A failed file write rolls the row back (skin_media leaves no files); a
    failure after the files are in place rolls back the row and removes them.
    """
    paths = {}
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
            paths = save_render(
                skin,
                RenderBundle(
                    svg=media.svg.encode("utf-8"), png=media.png, thumbnail=media.thumbnail
                ),
            )
            return skin
    except Exception:
        for rel_path in paths.values():
            full_path = os.path.join(settings.MEDIA_ROOT, rel_path)
            if os.path.exists(full_path):
                os.remove(full_path)
        raise
