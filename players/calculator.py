"""What the XP & Level calculator (players/templates xp_calculator.html) and the
profile's level card know about a player, shaped from the replay profile.

Pure functions over plain data, like players/charts.py. Levels and XP math
live in core.bonk.levels; account dates in core.bonk.dbid.
"""

from __future__ import annotations

from datetime import date, timedelta

from core.bonk import dbid, levels

PACE_WINDOW_DAYS = 90
MAX_SERIES_POINTS = 400


def sane_level(level):
    """Replays sometimes report impossible levels (zero, negative, huge);
    treat those as unknown."""
    try:
        level = int(level)
    except (TypeError, ValueError):
        return None
    return level if 0 < level <= 5000 else None


def _days(profile):
    out = []
    for p in profile.get("days") or []:
        lv = sane_level(p.get("level"))
        try:
            d = date.fromisoformat(str(p.get("day"))[:10])
        except ValueError:
            continue
        if lv:
            out.append((d, lv, int(p.get("games") or 0)))
    return sorted(out)


def level_series(profile):
    """[[day, level]] at each change of level (plus the ends), for charts."""
    rows = _days(profile)
    series, best = [], 0
    for i, (d, lv, _) in enumerate(rows):
        lv = max(lv, best)
        if lv != best or i in (0, len(rows) - 1):
            series.append([d.isoformat(), lv])
        best = lv
    if len(series) > MAX_SERIES_POINTS:
        step = len(series) / MAX_SERIES_POINTS
        series = [series[int(i * step)] for i in range(MAX_SERIES_POINTS)] + [series[-1]]
    return series


def recent_pace(profile):
    """Levels and XP per day over the last PACE_WINDOW_DAYS of replays, or
    None without two days of replays in that window."""
    rows = _days(profile)
    if not rows:
        return None
    end_day = rows[-1][0]
    window = [r for r in rows if r[0] >= end_day - timedelta(days=PACE_WINDOW_DAYS)]
    if len(window) < 2:
        return None
    (d0, lv0, _), (d1, lv1, _) = window[0], window[-1]
    span = max((d1 - d0).days, 1)
    lv1 = max(lv1, max(lv for _, lv, _ in window))
    xp_per_day = (levels.xp_for_level(lv1) - levels.xp_for_level(lv0)) / span
    return {
        "days": span,
        "levels": lv1 - lv0,
        "levels_per_day": round((lv1 - lv0) / span, 4),
        "xp_per_day": round(xp_per_day),
        "wins_per_day": round(xp_per_day / levels.XP_PER_WIN, 1),
        "from": d0.isoformat(),
        "to": d1.isoformat(),
    }


def account_age(bonk_id, today=None):
    """{"day", "extrapolated", "years"} for a bonk.io account ID, or None."""
    est = dbid.estimate(bonk_id, today=today)
    if est is None:
        return None
    today = today or date.today()
    return {
        "day": est.day,
        "extrapolated": est.extrapolated,
        "years": round((today - est.day).days / 365.25, 1),
    }


def level_card(level, xp=None):
    """XP facts for a level: exact progress when we know the XP (the player
    signed in), otherwise the XP range the level covers."""
    level = sane_level(level)
    if not level:
        return None
    floor = levels.xp_for_level(level)
    nxt = levels.xp_for_level(level + 1)
    card = {"level": level, "xp_floor": floor, "xp_next": nxt, "exact": False}
    if xp is not None and levels.level_for_xp(xp) == level:
        prog = levels.progress(xp)
        card.update(exact=True, xp=xp, percent=prog.percent, to_next=prog.to_next)
    milestone = (level // 50 + 1) * 50
    card["milestone"] = milestone
    card["milestone_xp"] = levels.xp_for_level(milestone)
    card["milestone_goal"] = levels.goal(card.get("xp", floor), card["milestone_xp"])
    return card


def player_summary(profile, *, bonk_id=None, xp=None, today=None):
    """Everything the calculator needs about one player."""
    summary = profile.get("summary") or {}
    level = sane_level(summary.get("current_level"))
    age = account_age(bonk_id, today=today)
    return {
        "username": profile.get("username") or summary.get("username"),
        "level": level,
        "xp": xp if xp is not None and level and levels.level_for_xp(xp) == level else None,
        "xp_floor": levels.xp_for_level(level) if level else None,
        "bonk_id": bonk_id,
        "created": age["day"].isoformat() if age else None,
        "created_extrapolated": age["extrapolated"] if age else None,
        "series": level_series(profile),
        "pace": recent_pace(profile),
    }
