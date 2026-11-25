"""The SVG upload sanitizer (skins/svg_sanitizer.py).

Skin SVGs are served from this site's own origin (/media/skins/<id>.svg), so
anything that runs script when the file is opened directly is stored XSS.
"""

import pytest

from skins.svg_sanitizer import (
    MAX_SVG_BYTES,
    SVGTooLargeError,
    UnsafeSVGError,
    validate_svg_upload,
)

SVG = 'xmlns="http://www.w3.org/2000/svg"'
XHTML = "http://www.w3.org/1999/xhtml"


def svg(body, attrs=""):
    return f'<svg {SVG} viewBox="-25 -25 50 50"{attrs}>{body}</svg>'


@pytest.mark.parametrize(
    "content",
    [
        # what the editor makes (taken from a real skin)
        svg('<circle r="25" fill="#70e1f1"/>'),
        svg('<g transform="rotate(30)"><path d="M0 0L10 10Z" fill="#fff" opacity=".5"/></g>'),
        svg('<defs><circle id="c" r="5"/></defs><use href="#c"/>'),
        svg('<defs><clipPath id="k"><circle r="25"/></clipPath></defs><g clip-path="url(#k)"/>'),
        svg('<style>.a{fill:#f00}</style><rect class="a" width="5" height="5"/>'),
        svg('<image href="data:image/png;base64,iVBORw0KGgo=" width="5" height="5"/>'),
        svg('<image href="https://example.com/a.png" width="5" height="5"/>'),
    ],
)
def test_accepts_ordinary_skins(content):
    assert validate_svg_upload(content) == content.encode()


@pytest.mark.parametrize(
    "content",
    [
        svg("<script>alert(1)</script>"),
        svg('<circle r="5" onclick="alert(1)"/>'),
        svg('<a href="javascript:alert(1)"><circle r="5"/></a>'),
        svg('<a href="java&#9;script:alert(1)"><circle r="5"/></a>'),
        svg('<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>'),
        svg('<animate attributeName="href" to="javascript:alert(1)"/>'),
        svg('<use href="https://evil.example/x.svg#a"/>'),
        svg('<image href="data:image/svg+xml;base64,PHN2Zz4="/>'),
        '<!DOCTYPE svg [<!ENTITY x "y">]>' + svg("&x;"),
        '<?xml-stylesheet href="https://evil.example/x.css"?>' + svg(""),
    ],
)
def test_rejects_script_and_active_content(content):
    with pytest.raises(UnsafeSVGError):
        validate_svg_upload(content)


class TestNotAnSvg:
    """A file whose root is XHTML is rendered as an HTML page when opened, where
    <form action="javascript:..."> runs script on a click (checked in Chrome and
    Firefox). These all passed before the root and namespace checks."""

    def test_rejects_an_xhtml_page(self):
        page = (
            f'<html xmlns="{XHTML}"><body><form action="javascript:alert(1)">'
            "<button>Equip</button></form></body></html>"
        )
        with pytest.raises(UnsafeSVGError, match="root element"):
            validate_svg_upload(page)

    def test_rejects_an_svg_tag_in_the_xhtml_namespace(self):
        page = f'<svg xmlns="{XHTML}"><form action="javascript:alert(1)"><button/></form></svg>'
        with pytest.raises(UnsafeSVGError, match="root element"):
            validate_svg_upload(page)

    def test_rejects_html_elements_inside_an_svg(self):
        content = svg(f'<h:form xmlns:h="{XHTML}"><h:button>x</h:button></h:form>')
        with pytest.raises(UnsafeSVGError, match="HTML/MathML"):
            validate_svg_upload(content)

    def test_rejects_mathml(self):
        content = svg('<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math>')
        with pytest.raises(UnsafeSVGError, match="HTML/MathML"):
            validate_svg_upload(content)

    @pytest.mark.parametrize("attr", ["action", "formaction"])
    def test_checks_form_urls(self, attr):
        with pytest.raises(UnsafeSVGError, match="unsafe URI"):
            validate_svg_upload(svg(f'<g {attr}="javascript:alert(1)"/>'))


class TestCss:
    """External CSS loads are requests to someone else's server (tracking)."""

    def test_rejects_external_url_in_style(self):
        with pytest.raises(UnsafeSVGError):
            validate_svg_upload(svg("<style>a{background:url(https://evil.example/t)}</style>"))

    def test_checks_style_text_after_a_child_element(self):
        # The CSS after <x/> is <x/>'s tail in ElementTree, but browsers apply it.
        content = svg("<style>a{}<x/>@import url(https://evil.example/x.css);</style>")
        with pytest.raises(UnsafeSVGError):
            validate_svg_upload(content)

    @pytest.mark.parametrize(
        "css",
        [
            r"a{background:\75 rl(https://evil.example/t)}",  # \75 is "u"
            r"\@import 'https://evil.example/x.css';",
            "a{background:image-set('https://evil.example/t' 1x)}",
        ],
    )
    def test_rejects_disguised_external_css(self, css):
        with pytest.raises(UnsafeSVGError):
            validate_svg_upload(svg(f"<style>{css}</style>"))

    def test_rejects_external_url_in_a_presentation_attribute(self):
        with pytest.raises(UnsafeSVGError, match="url"):
            validate_svg_upload(svg('<rect fill="url(https://evil.example/p)"/>'))

    def test_accepts_local_url_in_a_presentation_attribute(self):
        content = svg('<defs><linearGradient id="g"/></defs><rect fill="url(#g)"/>')
        assert validate_svg_upload(content)


def test_too_large_is_its_own_error():
    content = svg("<!--" + "x" * MAX_SVG_BYTES + "-->")
    with pytest.raises(SVGTooLargeError):
        validate_svg_upload(content)
