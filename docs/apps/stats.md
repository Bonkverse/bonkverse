# stats

Leaderboards, and later larger stat tracking. Created in RFC-0001 Phase 5.3.

**Owns:** which boards exist, their titles, tabs and order, and how a board's rows are drawn. **Does not own:** how anything is counted or ranked. A board gets its rows from the app that owns the data, through that app's selectors (`skins.selectors.top_skins` today), and never imports another app's models (`tests/test_leaderboards.py` checks).

## Routes

Names are in the `stats` namespace (`app_name` in `stats/urls.py`): `{% url 'stats:<name>' %}`, `reverse("stats:<name>")`.

Together the boards are one **Top skins** page: one tab per `LEADERBOARDS` entry, made by `stats/urls.py`, and period chips (`?period=all|month|week`, `PERIODS` in `stats/leaderboards.py`; an unknown value is all time). Votes and favorites aren't dated, so a period keeps skins *uploaded* in that window ("the best new skins this week"; `core.periods`). Skins with a count of 0 and skins with an open report are left out.

| Path | Name | Tab |
|---|---|---|
| `/leaderboards/upvoted/` | `leaderboards_upvoted` | Most upvoted |
| `/leaderboards/favorited/` | `leaderboards_favorited` | Most favorited |

An unknown board is a 404. There is deliberately no Most Downvoted board (removed after the 2026-11-09 design review: ranking creators by dislike invites brigading; votes stay a sort). Rate limit `browse`. Each board page is one query for an anonymous visitor.

## Adding a board

1. **Rows.** In the app that owns the data, add a selector that returns the top N rows, best first, each with its count as `value`. For skins, add a metric to `skins.selectors.SKIN_RANKINGS` (`top_skins(metric, n)` uses it). For a player board (level, for example) it would be a function in `players/selectors.py`.
2. **Rows.** Skin rows use `stats/_skin_rows.html` (rank, skin, name and creator, one number). Any other kind of row gets its own partial next to it (say `stats/_player_rows.html`) that loops over `rows` and shows `board.column` as what the number counts.
3. **Entry.** Add a `Leaderboard` to `LEADERBOARDS` in `stats/leaderboards.py`: `tab`, `column`, `rows=lambda n, period: <selector>(…, n, period)`, and `partial=` if it isn't a skin board. Dict order is tab order.
4. **Snapshot.** The new path fails `tests/test_url_snapshot.py` until it's added: `python -m tests.test_url_snapshot > tests/fixtures/url_routes.json`.
5. **Tests.** The parametrized tests in `tests/test_leaderboards.py` pick the board up (row partial exists, one query per period). Add one for its ranking in the owning app's tests.

A new nav link or tab outside the leaderboard pages goes through `Bonkverse/ui` `nav.json`, as for any header item.

## Files

```
stats/
  leaderboards.py               # LEADERBOARDS, Leaderboard, PERIODS, TOP_N (50), url_name(), tabs(), periods()
  views.py                      # the one view
  urls.py                       # one path per board
  templates/stats/
    leaderboard.html            # the Top skins page: tabs, period chips, the board's rows
    _tabs.html                  # board tabs; the period carries over
    _skin_rows.html             # rows = skins with .value
  static/stats/css/
    leaderboard.css             # loaded by leaderboard.html only
```

The page is on the shared `bv-` components (`site-page`).

## Models

`stats/models.py`: `PlayerWin` and `PlayerLoss`, the archived rows from the retired win/loss tracker userscript. Read-only: nothing writes them (the tracker's endpoints were removed in Phase 1) and no page shows them; they're kept for future stat tracking. Moved from `skins/` in 5.3b **without moving data**: they keep the tables `skins_playerwin` and `skins_playerloss` (`db_table`). Not registered in `/admin`.

Their `username` validator is `core.validators.validate_bonk_username`. `skins.models.validate_username` stays as an alias because skins migration 0016 imports it by that path.
