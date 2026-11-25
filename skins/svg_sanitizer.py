"""Fail-closed sanitizer for user-uploaded SVG skins.

Policy: an upload is REJECTED (not silently rewritten) if it contains
<script> in any form, or any other active-content vector (event handlers,
javascript:/data: URIs, foreignObject, animation of href, CSS injection,
DOCTYPE/entities, stylesheet PIs). CSS url() is allowed only for local
fragments (#id) — any external url() is an outbound request to an
attacker-controlled server (tracking/exfil). <use> may only reference
local fragments, never an external document. Plain shapes and <image>
references (https or raster data: URIs) are allowed.

The document must be an SVG: its root is <svg> in the SVG namespace, and no
element may be in the XHTML or MathML namespace. A file served as
image/svg+xml whose root is XHTML is rendered by browsers as an HTML page, and
HTML has script vectors this list doesn't cover (<form action="javascript:">).
/media/ also serves files with a sandbox CSP (skins/views/media.py), so a
file that got past these rules still couldn't run script there.
"""

import re
import xml.etree.ElementTree as ET

MAX_SVG_BYTES = 2_000_000

# Shown to people whose skin is over MAX_SVG_BYTES.
TOO_LARGE_MESSAGE = (
    "This skin is too detailed to upload: its image is over the 2 MB limit. "
    "Try fewer or simpler layers."
)

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

SVG_NS = "http://www.w3.org/2000/svg"
# Namespaces whose elements browsers render as HTML/MathML inside an XML
# document: never part of a skin.
BLOCKED_NAMESPACES = {"http://www.w3.org/1999/xhtml", "http://www.w3.org/1998/Math/MathML"}

# Attributes whose value is a URI and must be scheme-checked. action and
# formaction submit a form to a javascript: URL on click.
URI_ATTRS = {"href", "src", "action", "formaction"}

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
    # image-set() takes quoted URLs, not url(), so the url() check misses it.
    "image-set(",
)

# CSS escapes: "\\75 rl(" is "url(", "\\@import" is "@import".
CSS_ESCAPE_RE = re.compile(r"\\([0-9a-fA-F]{1,6})[ \t\n\r\f]?|\\(.)", re.DOTALL)

# Every url(...) target in CSS must be a local fragment; anything else is a
# request to an external server. Checked on the obfuscation-stripped string,
# so 'u r l ( "https://..." )' is caught too.
CSS_URL_RE = re.compile(r"url\(([^)]*)\)")


class UnsafeSVGError(ValueError):
    """Raised when an uploaded SVG fails validation."""


class SVGTooLargeError(UnsafeSVGError):
    """Raised when an SVG is over MAX_SVG_BYTES.

    Not a safety problem: a legitimate skin can render this large, so callers
    show the person a size message instead of calling the skin unsafe.
    """


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


def _decode_css_escapes(css):
    def char(m):
        if m.group(1):
            code = int(m.group(1), 16)
            return chr(code) if 0 < code <= 0x10FFFF else "\ufffd"
        return m.group(2)

    return CSS_ESCAPE_RE.sub(char, css)


def _namespace(name):
    return name[1:].split("}", 1)[0] if isinstance(name, str) and name.startswith("{") else ""


def _css_is_safe(css):
    norm = _strip_obfuscation(_decode_css_escapes(css or ""))
    if any(tok in norm for tok in CSS_BLOCKED_TOKENS):
        return False
    for m in CSS_URL_RE.finditer(norm):
        target = m.group(1).strip("\"'")
        if not target.startswith("#"):
            return False
    return True


def validate_svg_upload(content):
    """Raise UnsafeSVGError if `content` (bytes/str) is not a safe SVG.

    Returns the original bytes unchanged when the upload is accepted.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not content:
        raise UnsafeSVGError("empty SVG")
    if len(content) > MAX_SVG_BYTES:
        raise SVGTooLargeError(f"SVG exceeds {MAX_SVG_BYTES} bytes")

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

    if root.tag != f"{{{SVG_NS}}}svg":
        raise UnsafeSVGError("the root element must be <svg> in the SVG namespace")

    for el in root.iter():
        tag = _localname(el.tag)
        if _namespace(el.tag) in BLOCKED_NAMESPACES:
            raise UnsafeSVGError(f"HTML/MathML element <{tag}> is not allowed in a skin")
        if tag in BLOCKED_ELEMENTS:
            raise UnsafeSVGError(f"blocked element <{tag}>")

        allow_raster_data = tag == "image"
        for attr, value in el.attrib.items():
            name = _localname(attr)
            if name.startswith("on"):
                raise UnsafeSVGError(f"event handler attribute '{name}' on <{tag}>")
            if name in URI_ATTRS:
                # <use> pulls in another document; only same-document
                # fragments are safe, anything else can carry script.
                if tag == "use" and not _strip_obfuscation(value).startswith("#"):
                    raise UnsafeSVGError(f"external <use> reference in '{name}' on <use>")
                if not _uri_is_safe(value, allow_raster_data):
                    raise UnsafeSVGError(f"unsafe URI in '{name}' on <{tag}>")
            if name == "style" and not _css_is_safe(value):
                raise UnsafeSVGError(f"unsafe CSS in style attribute on <{tag}>")
            # Presentation attributes take url() too: fill="url(https://...)".
            if name != "style" and "url(" in _strip_obfuscation(_decode_css_escapes(value)):
                if not _css_is_safe(value):
                    raise UnsafeSVGError(f"unsafe url() in '{name}' on <{tag}>")

        # All of the element's text, not just .text: in <style>a{}<x/>@import ...
        # the CSS after <x/> is <x/>'s tail, and browsers apply it.
        if tag == "style" and not _css_is_safe("".join(el.itertext())):
            raise UnsafeSVGError("unsafe CSS in <style> element")

    return content
