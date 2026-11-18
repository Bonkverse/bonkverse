"""Which leaderboards exist: /leaderboards/<key>/ for each LEADERBOARDS entry.

Together they are one "Top skins" page: each board is a tab, and every board
can be narrowed to a period (PERIODS: skins uploaded this week, this month,
or all time).

Owns: the list of boards, their tab labels, tab order and periods, and which
rows and partial each one shows. Does not own: how anything is counted or
ranked. Rows come from the owning app's selectors (skins today; players for a
level board, for example), so stats never queries another app's models.

Adding a board is one entry here. If its rows aren't skins, also add a
row partial for that kind of row (like `stats/_skin_rows.html`).
stats/urls.py makes the page, named leaderboards_<key>.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from skins.selectors import top_skins

TOP_N = 50

# ?period= values, in chip order, and their labels. The first is the default.
PERIODS = {
    "all": "All time",
    "month": "This month",
    "week": "This week",
}


@dataclass(frozen=True)
class Leaderboard:
    tab: str  # label in the tab bar
    column: str  # what the number counts, e.g. "upvotes"
    rows: Callable[[int, str], Iterable]  # the top N rows for a period, best first
    partial: str = "stats/_skin_rows.html"  # draws the rows


# Order matters: it is the tab order.
LEADERBOARDS = {
    "upvoted": Leaderboard(
        tab="Most upvoted",
        column="upvotes",
        rows=lambda n, period: top_skins("upvotes", n, period),
    ),
    "favorited": Leaderboard(
        tab="Most favorited",
        column="favorites",
        rows=lambda n, period: top_skins("favorites", n, period),
    ),
}


def url_name(board: str) -> str:
    """The URL name of a board's page (kept from the old views)."""
    return f"leaderboards_{board}"


def period_from(value) -> str:
    """A PERIODS key from a ?period= value; anything else is the default."""
    return value if value in PERIODS else next(iter(PERIODS))


def tabs(current: str) -> list[dict]:
    """The tab bar: every board, in LEADERBOARDS order."""
    return [
        {"url_name": f"stats:{url_name(slug)}", "label": board.tab, "current": slug == current}
        for slug, board in LEADERBOARDS.items()
    ]


def periods(current: str) -> list[dict]:
    """The period chips, in PERIODS order."""
    return [
        {"value": value, "label": label, "current": value == current}
        for value, label in PERIODS.items()
    ]
