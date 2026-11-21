"""RFC-0002 ("One Bonkverse look"): the rules that keep every page on the
shared package, checked on the source.

- Colors come only from Bonkverse/ui's tokens (static/ui/tokens.css): the
  site's own CSS and scripts hold no hex, rgb() or hsl() colors and no named
  colors. Black at any transparency is allowed for shadows and scrims.
- The only font is Jost, from the package: stylesheets name a font only
  through var(--bv-font) or var(--bv-mono), and nothing loads Oxanium,
  Google Fonts or the old particles background.
- Every page is built on bv- components: nothing is left on the old
  site-legacy styles.

Exempt: static/ui/ (the package itself, synced by scripts/sync_ui.py) and
static/css/halloween.css, a seasonal theme whose future is an open question
in the revised RFC-0002. The chart colors in css/base.css are exempt until
the package has series tokens of its own.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "static" / "ui"
EXEMPT = {REPO / "static" / "css" / "halloween.css"}

STATIC_ROOTS = [REPO / "static", *sorted(REPO.glob("*/static"))]
TEMPLATE_ROOTS = [REPO / "templates", *sorted(REPO.glob("*/templates"))]


def _site_files(roots, pattern):
    for root in roots:
        for path in sorted(root.rglob(pattern)):
            if PACKAGE in path.parents or path in EXEMPT or ".venv" in path.parts:
                continue
            yield path


def _id(path):
    return str(path.relative_to(REPO))


STYLESHEETS = list(_site_files(STATIC_ROOTS, "*.css"))
SCRIPTS = list(_site_files(STATIC_ROOTS, "*.js"))
TEMPLATES = list(_site_files(TEMPLATE_ROOTS, "*.html"))

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
# rgb()/hsl() colors, except black at any transparency (shadows and scrims)
FUNCTION_COLOR = re.compile(r"\b(?:rgba?|hsla?)\((?!\s*0\s*[, ]\s*0\s*[, ]\s*0\b)[^)]*\)")
NAMED_COLOR = re.compile(
    r":\s*[^;{}]*?(?<![\w-])(red|white|black|blue|green|gray|grey|orange|yellow|purple|"
    r"pink|gold|silver|teal|navy|maroon|lime|aqua|cyan|magenta)(?![\w-])"
)
# The chart colors stay in css/base.css until the package has series tokens.
SERIES_DEFINITION = re.compile(r"^\s*--site-series-\d+:\s*#[0-9a-fA-F]{6};")


def _comment_free(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _lines(path):
    return enumerate(_comment_free(path.read_text()).splitlines(), start=1)


@pytest.mark.parametrize("path", STYLESHEETS, ids=_id)
def test_stylesheets_use_only_the_packages_colors(path):
    found = []
    for number, line in _lines(path):
        if SERIES_DEFINITION.match(line):
            continue
        for pattern in (HEX, FUNCTION_COLOR, NAMED_COLOR):
            match = pattern.search(line)
            if match:
                found.append(f"line {number}: {match.group(0).strip()}")
    assert not found, f"use a --bv-* token instead: {found}"


@pytest.mark.parametrize("path", SCRIPTS, ids=_id)
def test_scripts_pass_tokens_not_colors(path):
    """Scripts that color things (charts) pass var(--bv-…) or var(--site-series-N)."""
    found = re.findall(r"""['"`]#[0-9a-fA-F]{3,8}['"`]""", path.read_text())
    assert not found, f"use var(--…) instead of {found}"


ALLOWED_FONTS = {"var(--bv-font)", "var(--bv-mono)", "inherit"}


@pytest.mark.parametrize("path", STYLESHEETS, ids=_id)
def test_fonts_come_from_the_package(path):
    found = [
        f"line {number}: {value.strip()}"
        for number, line in _lines(path)
        for value in re.findall(r"font-family\s*:\s*([^;}]+)", line)
        if value.strip() not in ALLOWED_FONTS
    ]
    assert not found, f"use var(--bv-font) or var(--bv-mono): {found}"


@pytest.mark.parametrize("path", STYLESHEETS + SCRIPTS + TEMPLATES, ids=_id)
def test_nothing_loads_the_old_look(path):
    text = path.read_text().lower()
    for old in ("oxanium", "fonts.googleapis", "particles"):
        assert old not in text, f"{old} is part of the old look (RFC-0002)"


@pytest.mark.parametrize("path", STYLESHEETS + SCRIPTS + TEMPLATES, ids=_id)
def test_no_page_is_left_on_the_old_styles(path):
    assert "site-legacy" not in path.read_text(), "build the page on bv- components (site-page)"


def test_the_rules_see_the_sites_files():
    """Guards the globs above: an empty list would pass every test."""
    assert len(STYLESHEETS) > 10 and len(SCRIPTS) > 10 and len(TEMPLATES) > 50
