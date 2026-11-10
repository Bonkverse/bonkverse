"""Which leaderboards exist: /leaderboards/<key>/ for each LEADERBOARDS entry.

Owns: the list of boards, their titles, tabs and tab order, and which rows
and table each one shows. Does not own: how anything is counted or ranked.
Rows come from the owning app's selectors (skins today; players for a
level board, for example), so stats never queries another app's models.

Adding a board is one entry here. If its rows aren't skins, also add a
table partial for that kind of row (like `stats/_skin_table.html`).
stats/urls.py makes the page, named leaderboards_<key>.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from skins.selectors import top_skins

TOP_N = 50


@dataclass(frozen=True)
class Leaderboard:
    title: str  # page heading
    column: str  # heading of the count column
    tab: str | None  # label in the tab bar; None keeps the board out of it
    rows: Callable[[int], Iterable]  # the top N rows, best first
    table: str = "stats/_skin_table.html"  # partial that draws the rows


# Order matters: it is the tab order.
LEADERBOARDS = {
    "upvoted": Leaderboard(
        title="Most Upvoted Skins",
        column="Upvotes",
        tab="Most upvoted",
        rows=lambda n: top_skins("upvotes", n),
    ),
    "favorited": Leaderboard(
        title="Most Favorited Skins",
        column="Favorites",
        tab="Most favorited",
        rows=lambda n: top_skins("favorites", n),
    ),
    # Reachable by URL only; not shown in the tabs.
    "downvoted": Leaderboard(
        title="Most Downvoted Skins",
        column="Downvotes",
        tab=None,
        rows=lambda n: top_skins("downvotes", n),
    ),
}


def url_name(board: str) -> str:
    """The URL name of a board's page (kept from the three old views)."""
    return f"leaderboards_{board}"


def tabs(current: str) -> list[dict]:
    """The tab bar: boards with a tab label, in LEADERBOARDS order."""
    return [
        {"url_name": url_name(slug), "label": board.tab, "current": slug == current}
        for slug, board in LEADERBOARDS.items()
        if board.tab
    ]
