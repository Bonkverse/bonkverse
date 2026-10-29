"""Fail-closed sanitizer for user-uploaded SVG skins.

Policy: an upload is REJECTED (not silently rewritten) if it contains
<script> in any form, or any other active-content vector (event handlers,
javascript:/data: URIs, foreignObject, animation of href, CSS injection,
DOCTYPE/entities, stylesheet PIs). Plain shapes and <image> references
(https or raster data: URIs) are allowed.
"""

import re
import xml.etree.ElementTree as ET

MAX_SVG_BYTES = 2_000_000

# Elements that can execute or smuggle script. <image> is intentionally
# NOT here — raster image references are fine.
BLOCKED_ELEMENTS = {
    "script",
    "foreignobject",
    "animate",
    "set",
    "handler",
    "listener",
    "iframe",
    "embed",
    "object",
    "applet",
    "frame",
    "frameset",
    "base",
    "meta",
    "link",
}

# Attributes whose value is a URI and must be scheme-checked.
URI_ATTRS = {"href", "src"}

# data: URIs allowed only for raster images on <image> (never image/svg+xml).
RASTER_DATA_RE = re.compile(r"^data:image/(png|jpe?g|gif|webp|bmp|avif);")

# Raw-text checks, applied before parsing (defense in depth; also catches
# <script> hidden in comments/CDATA, which the parser would not see).
RAW_BLOCKED_RES = [
    re.compile(r"<\s*script\b", re.IGNORECASE),  # any <script ...>
    re.compile(r"<!\s*(doctype|entity)\b", re.IGNORECASE),  # XXE / billion laughs
    re.compile(r"<\?\s*xml-stylesheet\b", re.IGNORECASE),  # PI CSS injection
]

CSS_BLOCKED_TOKENS = (
    "javascript:",
    "vbscript:",
    "expression(",
    "@import",
    "-moz-binding",
    "behavior:",
)


class UnsafeSVGError(ValueError):
    """Raised when an uploaded SVG fails validation."""


def _localname(name):
    # ElementTree namespaces look like '{http://...}href'.
    return name.rsplit("}", 1)[-1].lower() if isinstance(name, str) else ""


def _strip_obfuscation(value):
    # Browsers ignore control chars/whitespace inside URLs and CSS, so
    # 'java\tscript:' must be treated as 'javascript:'.
    return re.sub(r"[\x00-\x20]", "", value or "").lower()


def _uri_is_safe(value, allow_raster_data):
    cleaned = _strip_obfuscation(value)
    if not cleaned:
        return True
    scheme = cleaned.split(":", 1)[0] if ":" in cleaned else ""
    if scheme in ("http", "https"):
        return True
    if scheme == "data":
        return allow_raster_data and bool(RASTER_DATA_RE.match(cleaned))
    if scheme == "":
        return cleaned.startswith("#")  # local fragment only
    return False


def _css_is_safe(css):
    norm = _strip_obfuscation(css)
    return not any(tok in norm for tok in CSS_BLOCKED_TOKENS)


def validate_svg_upload(content):
    """Raise UnsafeSVGError if `content` (bytes/str) is not a safe SVG.

    Returns the original bytes unchanged when the upload is accepted.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not content:
        raise UnsafeSVGError("empty SVG")
    if len(content) > MAX_SVG_BYTES:
        raise UnsafeSVGError(f"SVG exceeds {MAX_SVG_BYTES} bytes")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise UnsafeSVGError("SVG must be valid UTF-8") from None

    for rx in RAW_BLOCKED_RES:
        if rx.search(text):
            raise UnsafeSVGError(
                "SVG contains a blocked construct (<script>, DOCTYPE/ENTITY, or xml-stylesheet)"
            )

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise UnsafeSVGError(f"malformed XML: {e}") from e

    for el in root.iter():
        tag = _localname(el.tag)
        if tag in BLOCKED_ELEMENTS:
            raise UnsafeSVGError(f"blocked element <{tag}>")

        allow_raster_data = tag == "image"
        for attr, value in el.attrib.items():
            name = _localname(attr)
            if name.startswith("on"):
                raise UnsafeSVGError(f"event handler attribute '{name}' on <{tag}>")
            if name in URI_ATTRS and not _uri_is_safe(value, allow_raster_data):
                raise UnsafeSVGError(f"unsafe URI in '{name}' on <{tag}>")
            if name == "style" and not _css_is_safe(value):
                raise UnsafeSVGError(f"unsafe CSS in style attribute on <{tag}>")

        if tag == "style" and el.text and not _css_is_safe(el.text):
            raise UnsafeSVGError("unsafe CSS in <style> element")

    return content
