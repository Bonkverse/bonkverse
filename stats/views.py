"""The one leaderboard view: any board in stats/leaderboards.py LEADERBOARDS."""

from django.http import Http404
from django.shortcuts import render

from core.ratelimits import limit

from .leaderboards import LEADERBOARDS, TOP_N, tabs


@limit("browse")
def leaderboard(request, board: str):
    config = LEADERBOARDS.get(board)
    if config is None:
        raise Http404("Unknown leaderboard")

    return render(
        request,
        "stats/leaderboard.html",
        {"board": config, "rows": config.rows(TOP_N), "tabs": tabs(board)},
    )
