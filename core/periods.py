"""The one definition of the rolling time windows pages filter by.

Owns: which period names exist ("today", "week") and how far back each
reaches. Pages that filter "uploaded today / this week" go through here
(Skin.objects.created_in, skins/querysets.py).
Does not own: the visitor's calendar day (the search header's "uploaded
today" counts the visitor's own day in their time zone, skins/search.py) or
chart bucketing (players/charts.py).
"""

from datetime import datetime, timedelta

from django.utils import timezone

# Rolling windows that end now: "today" is the last 24 hours, not the
# calendar day. Add a period here (e.g. "month") when a page offers it; a
# name not listed means "all time".
PERIODS = {
    "today": timedelta(days=1),
    "week": timedelta(days=7),
}


def period_start(period: str, now: datetime | None = None) -> datetime | None:
    """When `period` began.

    Args:
        period: a name from PERIODS.
        now: the end of the window (default: now).

    Returns:
        The start of the window, or None for a name not in PERIODS (all time).
    """
    window = PERIODS.get(period)
    if window is None:
        return None
    return (now or timezone.now()) - window
