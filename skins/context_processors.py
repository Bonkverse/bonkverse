# skins/context_processors.py
import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from .models import Changelog


def editor_urls(request):
    return {
        "BONKVERSE_EDITOR_URL": settings.BONKVERSE_EDITOR_URL,
        "BONKVERSE_REPLAYS_URL": settings.BONKVERSE_REPLAYS_URL,
        "BONKVERSE_DISCORD_URL": settings.BONKVERSE_DISCORD_URL,
        "BONKVERSE_DOCS_URL": settings.BONKVERSE_DOCS_URL,
    }


def latest_update(request):
    try:
        return {"latest_update": Changelog.objects.order_by("-created_at").first()}
    except Exception:
        return {"latest_update": None}


# ── The shared header and footer (Bonkverse/ui nav.json) ───────────────────
#
# Every Bonkverse site builds its header and footer from the same nav.json,
# copied here by scripts/sync_ui.py. Paths starting with "/" are on this site.
# Links to our other sites use this deployment's settings, so local and
# staging point at their own replay site and editor.

_UI_NAV = Path(settings.BASE_DIR) / "skins" / "static" / "ui" / "nav.json"

# Which header item is highlighted for a path on this site.
_SECTIONS = {
    "skins": (
        "/search/",
        "/new/",
        "/categories/",
        "/category/",
        "/leaderboards/",
        "/upload/",
        "/skins/",
    ),
    "players": ("/players/", "/player/", "/players_search/"),
    "tools": ("/tools/",),
    "developers": ("/developers/",),
}


# Which skin tab is highlighted, and the pages that show the tab row.
_SKIN_TABS = {
    "search": ("/search/",),
    "new": ("/new/",),
    "categories": ("/categories/", "/category/"),
    "leaderboards": ("/leaderboards/",),
    "upload": ("/upload/",),
}


@lru_cache(maxsize=1)
def _nav_file():
    return json.loads(_UI_NAV.read_text(encoding="utf-8"))


def _site_href(href):
    """Point links to our other sites at this deployment's copies."""
    swaps = {
        "https://replays.bonkverse.io/": settings.BONKVERSE_REPLAYS_URL + "/",
        "https://editor.bonkverse.io/": settings.BONKVERSE_EDITOR_URL + "/",
        "https://docs.bonkverse.io/": settings.BONKVERSE_DOCS_URL + "/",
        "https://discord.gg/2Zx7Cwhr4Z": settings.BONKVERSE_DISCORD_URL,
    }
    return swaps.get(href, href)


def _link(item):
    href = _site_href(item["href"])
    return {**item, "href": href, "external": not href.startswith("/")}


def site_nav(request):
    """`site_nav` for skins/partials/_site_header.html and _site_footer.html."""
    nav = _nav_file()
    path = request.path
    current = next((sid for sid, prefixes in _SECTIONS.items() if path.startswith(prefixes)), None)
    header = []
    for item in nav["header"]:
        entry = {"id": item["id"], "label": item["label"], "current": item["id"] == current}
        if "items" in item:
            # "menu", not "items": a template's item.items would call dict.items().
            entry["menu"] = [_link(sub) for sub in item["items"]]
        else:
            entry.update(_link(item))
        header.append(entry)
    return {
        "site_nav": {
            "version": nav["version"],
            "header": header,
            "skin_tabs": [
                {**_link(t), "current": path.startswith(_SKIN_TABS.get(t["id"], (t["href"],)))}
                for t in nav["skinTabs"]
            ],
            "show_skin_tabs": any(
                path.startswith(p) for prefixes in _SKIN_TABS.values() for p in prefixes
            ),
            "account": [_link(a) for a in nav["account"]["items"]],
            "footer": [
                {"title": col["title"], "links": [_link(i) for i in col["items"]]}
                for col in nav["footer"]
            ],
            "note": nav["note"],
        }
    }
