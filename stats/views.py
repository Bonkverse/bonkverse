"""The one leaderboard view: any board in stats/leaderboards.py LEADERBOARDS."""

from django.http import Http404
from django.shortcuts import render

from core.ratelimits import limit

from .leaderboards import LEADERBOARDS, PERIODS, TOP_N, period_from, periods, tabs


@limit("browse")
def leaderboard(request, board: str):
    config = LEADERBOARDS.get(board)
    if config is None:
        raise Http404("Unknown leaderboard")
    period = period_from(request.GET.get("period"))
    rows = list(config.rows(TOP_N, period))
    # Your own row: the signed-in player's best-ranked skin on this board is
    # the page's one highlight (ADR 0021).
    own_skin_id = next((skin.id for skin in rows if skin.is_owned_by(request.user)), None)

    return render(
        request,
        "stats/leaderboard.html",
        {
            "board": config,
            "rows": rows,
            "own_skin_id": own_skin_id,
            "tabs": tabs(board),
            "period": period,
            "period_label": PERIODS[period],
            "periods": periods(period),
        },
    )
