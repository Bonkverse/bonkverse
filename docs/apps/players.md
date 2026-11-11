# players

bonk.io players as Bonkverse knows them: profiles built from the replay archive, the player directory and search, the friend graph (bonk.io friends and Flash-era friends), social stats, the XP calculator and profile privacy. The app existed before Phase 5 (profiles, replay sync, privacy); RFC-0001 step 5.4 moved the friend sync, player search APIs and social stats in from `skins/`, and 5.4b moved the player models.

**Owns:** what a profile shows and who may see it, storing friend lists, syncing names and DBIDs with the replay archive. **Does not own:** signing in or the bonk.io session (`skins/sign_in.py`, later `accounts`), talking to bonk.io or the replay archive (`integrations/`), the event log the sync writes to (`skins.events`, until 5.6 decides its home).

## Routes

| Path | Name | What |
|---|---|---|
| `/players/` | `players_directory` | Directory and search (`views.directory`, rules in `search.py`) |
| `/players_search/players/`, `/players_search/flash-friends/` | `players_page`, `flash_friends_page` | Old search pages, kept for old links |
| `/player/<username>/` and `…/activity/`, `level/`, `maps/`, `people/`, `friends/`, `skins/` | `player_profile`, `player_activity`, … | Profile tabs (`views.py`, data from `selectors.py`) |
| `/settings/profile/` | `profile_settings` | Who sees which profile section |
| `/tools/xp/` (+ `player.json`, `levels.json`) | `xp_calculator`, … | XP calculator |
| `/social-stats/` | `social_stats` | Friend-graph totals and most-connected players (`social_stats.py`) |
| `/api/players/search/`, `/api/flash-friends/search/` | `players_search`, `flash_friends_search` | JSON search (`api.py`) |
| `/api/friends-sync-status/` | `friends_sync_status` | Polled by My Profile's toast after login (`api.py`) |

`<username>` is the `username` converter (`converters.py`, registered in `PlayersConfig.ready()`): `.` and `..` get a `~` in front.

## Public entry points for other apps

`players/services.py`: `queue_friend_sync(account_link_id)`, `sync_flash_friends_for_user(...)`, `adopt_replay_names(...)` (all used by login), `update_visibility(...)`. `players/selectors.py` for reads (profiles, directory, calculator).

## Background work

`tasks.py`:
- `sync_friends`, queued at login, registered as **`skins.tasks.sync_friends`** (its name before the move, so runs queued during a deploy keep working; pinned by `tests/test_friend_sync_task.py`).
- `sync_replays`, hourly.

Details: [background-work.md](../architecture/background-work.md).

## Files

```
players/
  views.py, api.py, social_stats.py   # pages, JSON endpoints, social stats page
  selectors.py, search.py              # reads; directory search rules
  services.py, tasks.py                # writes and entry points; worker tasks
  friends_sync.py                      # friends.php -> Friendship edges, in named steps
  flash_friends_sync.py                # Flash-era friends from the login reply
  replay_sync.py                       # names in, DBIDs out with the replay archive
  calculator.py, charts.py, converters.py, dbid_lookup.py
  templates/players/                   # every profile tab, directory, settings, XP calculator, social stats
  static/players/js/, static/players/css/   # page scripts and page-only styles
  management/commands/                 # sync_replays, populate_* (local seed data)
```

Shared styles stay in `skins/static/css/`: `player_profile.css` (also used by the developer portal), `charts.css`, `controls.css`.

`dbid_lookup.py` (social stats' account-age estimates) is an older table than `core/bonk/dbid.py` (profiles, public API). Merging them would change the estimates on the social stats page, so it's a separate decision.

## Models

All in `players/models.py`:

| Model | Table | What |
|---|---|---|
| `BonkPlayer` | `skins_bonkplayer` | A bonk.io account (DBID, name, XP). Not the Bonkverse login user. |
| `Friendship` | `skins_friendship` | One undirected friend edge, stored once (low id, high id). |
| `FriendCountHistory` | `skins_friendcounthistory` | Friend count at each sync. |
| `FlashFriend`, `FlashFriendship` | `skins_flashfriend`, `skins_flashfriendship` | Flash-era friends and who imported them. |
| `ProfileVisibility`, `SyncCursor` | `players_*` | Profile section switches; where the replay sync got to. |

The first five moved from `skins/` in step 5.4b without moving data (migrations `players.0005` and `skins.0032`, both state-only): they keep their `skins_*` tables and index names, and `BonkAccountLink.bonk_player` (still in `skins`) points here. Renaming a table or index is a separate, real migration.
