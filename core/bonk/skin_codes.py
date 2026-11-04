"""Skin codes: the encoded avatar string bonk.io stores and renders."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

# BonkLeagues imports sometimes stored codes URL-encoded twice (%252F for "/").
_MAX_DECODE_PASSES = 2


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

    def __str__(self) -> str:
        return self.raw
