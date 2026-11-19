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

    return render(
        request,
        "stats/leaderboard.html",
        {
            "board": config,
            "rows": list(config.rows(TOP_N, period)),
            "tabs": tabs(board),
            "period": period,
            "period_label": PERIODS[period],
            "periods": periods(period),
        },
    )
