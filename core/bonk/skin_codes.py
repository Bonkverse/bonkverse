"""Skin codes: the encoded avatar string bonk.io stores and renders."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

# BonkLeagues imports sometimes stored codes URL-encoded twice (%252F for "/").
_MAX_DECODE_PASSES = 2
# A decoded code is base64.
_BASE64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


@dataclass(frozen=True)
class SkinCode:
    """A bonk.io skin code as stored on a Skin (`skin.skin_code`).

    Stored codes may be URL-encoded (once, or twice for some BonkLeagues
    imports). `decoded` is the plain base64 form the render service expects.
    """

    raw: str

    def __post_init__(self):
        if not self.raw:
            raise ValueError("skin code is empty")

    @property
    def decoded(self) -> str:
        """The code with URL-encoding removed (up to two passes)."""
        code = self.raw
        for _ in range(_MAX_DECODE_PASSES):
            if "%" not in code:
                break
            code = unquote(code)
        return code

    @classmethod
    def from_image_url(cls, image_url: str) -> SkinCode | None:
        """The code from a BonkLeagues image URL's `skinCode` query parameter, if any."""
        try:
            value = parse_qs(urlparse(image_url).query).get("skinCode", [None])[0]
        except (TypeError, ValueError):
            return None
        return cls(value) if value else None

    @classmethod
    def from_bonkleagues_url(cls, url: str | None) -> SkinCode | None:
        """The code carried by a BonkLeagues URL, if it carries one.

        Handles both forms BLSkinFetcher reports as `finalUrl`:
        - an image URL with `?skinCode=<code>`
        - the skins page redirect `skins.html#<name>|<author>|<code>`, where the
          fragment (separators included) is percent-encoded.
        Returns None for anything else, including a fragment whose last part
        isn't a base64 code, so a page URL is never mistaken for a skin.
        """
        if not url:
            return None
        found = cls.from_image_url(url)
        if found is None:
            try:
                fragment = urlparse(url).fragment
            except ValueError:
                return None
            parts = unquote(fragment).split("|")
            if len(parts) < 3:
                return None
            # Same split as BLSkinFetcher's extractFromUrl: everything after the second "|".
            value = "|".join(parts[2:]).strip()
            if not value:
                return None
            found = cls(value)
        return found if _BASE64.match(found.decoded) else None

    def __str__(self) -> str:
        return self.raw
