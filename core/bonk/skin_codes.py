"""Skin codes: the encoded avatar string bonk.io stores and renders.

A skin code is base64 of an AMF3 object of class "a": a version, the layer
list (an AMF3 array) and the base color. `SkinCode.parse()` reads it the way
the skin editor's decoder does (skin-editor src/bonk/decode/decodeSkinCore.js)
and refuses anything that isn't a real skin, so text or other data can't be
stored as a code.
"""

from __future__ import annotations

import base64
import binascii
import re
import struct
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

# BonkLeagues imports sometimes stored codes URL-encoded twice (%252F for "/").
_MAX_DECODE_PASSES = 2
# A decoded code is base64.
_BASE64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")

# Shapes the skin editor can draw (public/output_shapes/1..115.svg; 115 is
# the whisp). Raise this with the editor's TOTAL_BONK_SHAPES.
MAX_SHAPE_ID = 115
# bonk.io's own editor stops at 16 layers, but real skins have more: the
# gallery has skins with up to 51 (BonkLeagues and older tools allow it).
# This is a sanity bound, well above any real skin.
MAX_LAYERS = 128
# Slot indexes go past the layer count when layers were removed (empty
# slots stay in the list).
_MAX_SLOT_INDEX = 255
# 128 layers are about 3.6 KB; base64 and URL-encoding make that ~6 KB.
MAX_CODE_LENGTH = 12000

_HEADER = bytes([0x0A, 0x07, 0x03, 0x61])  # object, externalizable, class "a"
_ARRAY = 0x09
_LAYER = 0x0A
_LAYER_CLASS = bytes([0x07, 0x05, 0x61, 0x6C])  # first layer: class "al" inline
_LAYER_CLASS_REF = 0x05  # later layers refer back to it
_EMPTY_SLOT = (0x00, 0x01)  # AMF3 undefined, null
_LAYER_FIELDS = struct.Struct(">HHffffBBI")  # 1, shape, scale, angle, x, y, flipX, flipY, color


class InvalidSkinCode(ValueError):
    """The text isn't a bonk.io skin code. `reason` says why, for logs."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SkinLayer:
    shape_id: int
    scale: float
    angle: float
    x: float
    y: float
    flip_x: bool
    flip_y: bool
    color: int


@dataclass(frozen=True)
class ParsedSkin:
    base_color: int
    layers: tuple[SkinLayer, ...]  # in slot order (bottom to top)


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

    def parse(self) -> ParsedSkin:
        """Read the skin: its base color and layers.

        Raises:
            InvalidSkinCode: not a skin code (not base64, not bonk.io's skin
                format, a shape the editor doesn't have, more than
                MAX_LAYERS layers, or bytes left over).
        """
        if len(self.raw) > MAX_CODE_LENGTH:
            raise InvalidSkinCode(f"longer than {MAX_CODE_LENGTH} characters")
        text = self.decoded
        if not _BASE64.match(text):
            raise InvalidSkinCode("not base64")
        try:
            data = base64.b64decode(text + "=" * (-len(text) % 4), validate=True)
        except (binascii.Error, ValueError) as e:
            raise InvalidSkinCode("not base64") from e
        return _Reader(data).skin()

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


class _Reader:
    """Reads one skin's bytes; every problem is an InvalidSkinCode."""

    def __init__(self, data: bytes):
        self.data = data
        self.i = 0
        # AMF3 string table, in stream order: class "a", then keys and "al".
        self.strings = ["a"]
        self.class_defined = False

    def skin(self) -> ParsedSkin:
        if self._take(4) != _HEADER:
            raise InvalidSkinCode("not bonk.io's skin format")
        self._take(2)  # format version
        if self._byte() != _ARRAY:
            raise InvalidSkinCode("no layer list")

        slots: list[tuple[int, SkinLayer]] = []
        dense = self._u29() >> 1
        if dense > _MAX_SLOT_INDEX + 1:
            raise InvalidSkinCode(f"{dense} layer slots")
        # Slots past a gap come first, as "index" -> layer pairs, ended by "".
        while (key := self._string()) != "":
            if not key.isdigit() or int(key) > _MAX_SLOT_INDEX:
                raise InvalidSkinCode("layer list has a key that isn't a slot index")
            if (layer := self._slot()) is not None:
                slots.append((int(key), layer))
        for index in range(dense):
            if (layer := self._slot()) is not None:
                slots.append((index, layer))
        if len(slots) > MAX_LAYERS:
            raise InvalidSkinCode(f"{len(slots)} layers (at most {MAX_LAYERS})")

        # Skins saved with no layers have AMF3 nulls before the base color.
        rest = self.data[self.i :]
        if len(rest) < 4 or any(b != 0x01 for b in rest[:-4]):
            raise InvalidSkinCode("unexpected bytes after the layers")
        base_color = int.from_bytes(rest[-4:], "big")
        if base_color > 0xFFFFFF:
            raise InvalidSkinCode("base color out of range")

        slots.sort(key=lambda pair: pair[0])
        return ParsedSkin(base_color=base_color, layers=tuple(layer for _, layer in slots))

    def _slot(self) -> SkinLayer | None:
        marker = self._byte()
        if marker in _EMPTY_SLOT:
            return None
        if marker != _LAYER:
            raise InvalidSkinCode("a layer slot holds something that isn't a layer")
        if not self.class_defined:
            if self._take(4) != _LAYER_CLASS:
                raise InvalidSkinCode("layer isn't bonk.io's layer type")
            self.strings.append("al")
            self.class_defined = True
        elif self._byte() != _LAYER_CLASS_REF:
            raise InvalidSkinCode("layer isn't bonk.io's layer type")

        one, shape, scale, angle, x, y, flip_x, flip_y, color = _LAYER_FIELDS.unpack(
            self._take(_LAYER_FIELDS.size)
        )
        if one != 1:
            raise InvalidSkinCode("layer isn't bonk.io's layer type")
        if not 1 <= shape <= MAX_SHAPE_ID:
            raise InvalidSkinCode(f"shape {shape} doesn't exist")
        if flip_x > 1 or flip_y > 1 or color > 0xFFFFFF:
            raise InvalidSkinCode("layer flip or color out of range")
        return SkinLayer(shape, scale, angle, x, y, bool(flip_x), bool(flip_y), color)

    def _take(self, n: int) -> bytes:
        if self.i + n > len(self.data):
            raise InvalidSkinCode("ends too early")
        chunk = self.data[self.i : self.i + n]
        self.i += n
        return chunk

    def _byte(self) -> int:
        return self._take(1)[0]

    def _u29(self) -> int:
        """AMF3 variable-length integer (1 to 4 bytes)."""
        value = 0
        for _ in range(3):
            b = self._byte()
            value = (value << 7) | (b & 0x7F)
            if not b & 0x80:
                return value
        return (value << 8) | self._byte()

    def _string(self) -> str:
        header = self._u29()
        if not header & 1:  # reference to an earlier string
            try:
                return self.strings[header >> 1]
            except IndexError:
                raise InvalidSkinCode("bad string reference") from None
        text = self._take(header >> 1).decode("latin-1")
        if text:
            self.strings.append(text)
        return text
