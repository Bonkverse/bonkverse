"""SkinCode.parse(): real skin codes read, anything else refused (core/bonk/skin_codes.py).

Fake codes got stored once: two skins published through the editor's API
carried text ("POC-FINAL-002") as their code, next to an SVG with a script in
it. The SVG check stops the script; this stops the fake code.
"""

import base64
import struct

import pytest

from core.bonk import InvalidSkinCode, SkinCode
from core.bonk.skin_codes import MAX_CODE_LENGTH, MAX_LAYERS, MAX_SHAPE_ID
from tests.factories import SKIN_CODE, SKIN_CODE_DOUBLE_ENCODED

# Real codes from the gallery, one per shape of layer list.
REAL = {
    # dense layers only (what the editor writes)
    "editor": SKIN_CODE,
    # an empty first slot
    "empty_first_slot": (
        "CgcDYQACCRkBAQoHBWFsAAEADT4ZmZoAAAAAAAAAAMDwAAAAAAD6+voKBQABAA0+ij1xAAAAAAAAAADA8AAAAA"
        "AAAAAACgUAAQANPhmZmgAAAADAgAAAv8AAAAAAAPr6+goFAAEADT6ZmZoAAAAAwIAAAL/AAAAAAAAAAAAKBQABAA0"
        "/IUeuAAAAAL/AAADAYAAAAAAA+vr6AQEBAQEBAAAAAA=="
    ),
    # every layer written as "index" -> layer pairs (slots past a gap); stored URL-encoded
    "index_pairs": (
        "CgcDYQACCQ8DOAoHBWFsAAEAUD11wo/C3AAAQIAAAMAAAAAAAAAaI34DOQoFAAEAUD11wo9C3AAAwIAAAMAAAAAAAA"
        "AaI34FMTAKBQABAA0%2BszMzAAAAAAAAAABAgAAAAAAAAAAABTExCgUAAQANPrMzMwAAAAAAAAAAQNAAAAAAANMvLw"
        "UxMgoFAAEADT6zMzMAAAAAAAAAAEEYAAAAAAAAAAAFMTMKBQABAFA%2BdcKPQzQAAAAAAABAQAAAAAAAAAAABTE0CgU"
        "AAQANP0AAAAAAAAAAAAAAAAAAAAAAANMvLwUxNQoFAAEADT9ZmZoAAAAAAAAAAAAAAAAAAAAAAAABAQEBAQEBAQDTLy8="
    ),
    # no layers: nulls before the base color
    "no_layers": "CgcDYQACCQEBAQEAVS0S",
}


def _code(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _skin(layers: list[bytes], base_color=0x112233) -> bytes:
    """Build a code the way the editor's encoder does (dense layers)."""
    body = bytes([0x0A, 0x07, 0x03, 0x61, 0x00, 0x02, 0x09]) + _u29(2 * len(layers) + 1) + b"\x01"
    return body + b"".join(layers) + base_color.to_bytes(4, "big")


def _u29(n: int) -> bytes:
    """AMF3 variable-length integer (up to 2**21 - 1 here)."""
    if n < 0x80:
        return bytes([n])
    if n < 0x4000:
        return bytes([0x80 | n >> 7, n & 0x7F])
    return bytes([0x80 | n >> 14, 0x80 | (n >> 7) & 0x7F, n & 0x7F])


def _layer(shape=13, *, first=False, color=0xFAFAFA) -> bytes:
    head = bytes([0x0A, 0x07, 0x05, 0x61, 0x6C]) if first else bytes([0x0A, 0x05])
    return head + struct.pack(">HHffffBBI", 1, shape, 0.15, 0, 0, 0, 0, 0, color)


def _layers(shapes) -> list[bytes]:
    return [_layer(s, first=(n == 0)) for n, s in enumerate(shapes)]


class TestRealCodes:
    @pytest.mark.parametrize("name", sorted(REAL))
    def test_reads(self, name):
        SkinCode(REAL[name]).parse()

    def test_editor_code(self):
        skin = SkinCode(SKIN_CODE).parse()
        assert skin.base_color == 0
        assert [layer.shape_id for layer in skin.layers] == [13]
        assert skin.layers[0].color == 0xFAFAFA
        assert skin.layers[0].scale == pytest.approx(0.15)

    def test_url_encoded_twice(self):
        assert SkinCode(SKIN_CODE_DOUBLE_ENCODED).parse() == SkinCode(SKIN_CODE).parse()

    def test_index_pairs_come_out_in_slot_order(self):
        skin = SkinCode(REAL["index_pairs"]).parse()
        assert [layer.shape_id for layer in skin.layers] == [80, 80, 13, 13, 13, 80, 13, 13]
        assert skin.base_color == 0xD32F2F

    def test_empty_slots_are_skipped(self):
        assert len(SkinCode(REAL["empty_first_slot"]).parse().layers) == 5
        assert SkinCode(REAL["no_layers"]).parse().layers == ()

    def test_more_layers_than_bonk_editor_allows(self):
        """Real skins have up to 51 layers; bonk.io's own editor stops at 16."""
        assert len(SkinCode(_code(_skin(_layers([13] * 51)))).parse().layers) == 51

    def test_layer_floats_bonk_stored_as_nan(self):
        """9 gallery skins have a NaN or infinite position or size; they're real skins."""
        data = bytearray(_skin(_layers([13])))
        data[18:22] = struct.pack(">f", float("nan"))  # scale
        SkinCode(_code(bytes(data))).parse()

    def test_editor_codes_with_more_than_63_layers(self):
        """The editor's encoder writes the slot count as one byte (85 layers -> 0xab),
        not an AMF3 integer (0x81 0x2b). Gallery skins 9670 and 12027 are like this."""
        layers = _layers([13] * 85)
        data = bytes([0x0A, 0x07, 0x03, 0x61, 0x00, 0x02, 0x09, 2 * 85 + 1, 0x01])
        data += b"".join(layers) + (0x112233).to_bytes(4, "big")

        skin = SkinCode(_code(data)).parse()

        assert len(skin.layers) == 85
        assert skin.base_color == 0x112233

    def test_url_encoded_three_times(self):
        """Gallery skin 7520 is stored with "/" as %25252F."""
        triple = SKIN_CODE.replace("+", "%25252B").replace("=", "%25253D")
        assert SkinCode(triple).parse() == SkinCode(SKIN_CODE).parse()

    def test_the_whisp_and_the_layer_limit(self):
        SkinCode(_code(_skin(_layers([MAX_SHAPE_ID] * MAX_LAYERS)))).parse()


class TestRefused:
    @pytest.mark.parametrize(
        "text",
        [
            "POC-FINAL-002",  # the two fake skins' codes
            "JOKE-PRES-002",
            "POCFINAL002",  # base64 alphabet, not a skin
            _code(b"<svg><script>alert(1)</script></svg>"),
            _code(b"\x0a\x07\x03\x61"),  # the header and nothing else
        ],
    )
    def test_text_and_other_data(self, text):
        with pytest.raises(InvalidSkinCode):
            SkinCode(text).parse()

    def test_shape_that_does_not_exist(self):
        with pytest.raises(InvalidSkinCode, match="shape 116"):
            SkinCode(_code(_skin(_layers([13, MAX_SHAPE_ID + 1])))).parse()

    def test_more_layers_than_bonk_allows(self):
        with pytest.raises(InvalidSkinCode, match=f"{MAX_LAYERS + 1} layers"):
            SkinCode(_code(_skin(_layers([13] * (MAX_LAYERS + 1))))).parse()

    def test_bytes_after_the_skin(self):
        with pytest.raises(InvalidSkinCode, match="after the layers"):
            SkinCode(_code(_skin(_layers([13])) + b"<script>")).parse()

    def test_a_layer_of_another_type(self):
        data = bytearray(_skin(_layers([13])))
        data[12] = ord("x")  # class name "al" -> "ax"
        with pytest.raises(InvalidSkinCode, match="layer type"):
            SkinCode(_code(bytes(data))).parse()

    def test_too_long(self):
        with pytest.raises(InvalidSkinCode, match="longer than"):
            SkinCode("A" * (MAX_CODE_LENGTH + 1)).parse()

    def test_reason_is_kept_for_logs(self):
        with pytest.raises(InvalidSkinCode) as caught:
            SkinCode("POC-FINAL-002").parse()
        assert caught.value.reason == "not base64"


@pytest.mark.django_db
def test_audit_command_counts_refused_codes():
    from io import StringIO

    from django.core.management import call_command

    from tests.factories import SkinFactory

    SkinFactory(skin_code=SKIN_CODE)
    fake = SkinFactory(skin_code="POC-FINAL-002")
    out = StringIO()

    call_command("audit_skin_codes", stdout=out)

    assert "Checked 2 skin codes: 1 pass, 1 refused." in out.getvalue()
    assert f"not base64: 1: {fake.id}" in out.getvalue()
