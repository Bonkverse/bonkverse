# players

bonk.io players as Bonkverse knows them: profiles built from the replay archive, the player directory and search, the friend graph (bonk.io friends and Flash-era friends), social stats, the XP calculator and profile privacy. The app existed before Phase 5 (profiles, replay sync, privacy); RFC-0001 step 5.4 moved the friend sync, player search APIs and social stats in from `skins/`, and 5.4b moved the player models.

**Owns:** what a profile shows and who may see it, storing friend lists, the skin each player last wore (`worn_skins.py`), syncing names and DBIDs with the replay archive. **Does not own:** signing in or the bonk.io session (`accounts`), talking to bonk.io or the replay archive (`integrations/`), the event log the sync writes to (`skins.events`, until 5.6 decides its home).

## Routes

| Path | Name | What |
|---|---|---|
| `/players/` | `players_directory` | Directory and search (`views.directory`, rules in `search.py`) |
| `/players_search/players/`, `/players_search/flash-friends/` | `players_page`, `flash_friends_page` | Old search pages, kept for old links |
| `/player/<username>/` and `…/activity/`, `level/`, `maps/`, `people/`, `friends/`, `skins/` | `player_profile`, `player_activity`, … | Profile tabs (`views.py`, data from `selectors.py`) |
| `/player/<username>/skin.png`, `…/skin-thumb.png` | `player_skin_avatar`, `player_skin_avatar_thumb` | The player's worn skin as a 512 / 128 px PNG (`views.skin_avatar`, `media` rate tier); 404 when there's none |
| `/settings/profile/` | `profile_settings` | Who sees which profile section |
| `/tools/xp/` (+ `player.json`, `levels.json`) | `xp_calculator`, … | XP calculator |
| `/social-stats/` | `social_stats` | Friend-graph totals and most-connected players (`social_stats.py`) |
| `/api/players/search/`, `/api/flash-friends/search/` | `players_search`, `flash_friends_search` | JSON search (`api.py`) |
| `/api/friends-sync-status/` | `friends_sync_status` | Polled by My Profile's toast after login (`api.py`) |

`<username>` is the `username` converter (`converters.py`, registered in `PlayersConfig.ready()`): `.` and `..` get a `~` in front.

## Public entry points for other apps

`players/services.py`: `queue_friend_sync(account_link_id)`, `sync_flash_friends_for_user(...)`, `adopt_replay_names(...)` (all used by `accounts/sign_in.py`), `record_worn_skin(bonk_id, skin_code, source)` (used by `accounts/sign_in.py` and `skins/wear_skin.py`), `update_visibility(...)`. `players/selectors.py` for reads (profiles, directory, calculator).

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
  worn_skins.py                        # the skin each player last wore (newest sighting wins)
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
| `BonkPlayer` | `skins_bonkplayer` | A bonk.io account (DBID, name, XP, last worn skin). Not the Bonkverse login user. |
| `Friendship` | `skins_friendship` | One undirected friend edge, stored once (low id, high id). |
| `FriendCountHistory` | `skins_friendcounthistory` | Friend count at each sync. |
| `FlashFriend`, `FlashFriendship` | `skins_flashfriend`, `skins_flashfriendship` | Flash-era friends and who imported them. |
| `ProfileVisibility`, `SyncCursor` | `players_*` | Profile section switches; where the replay sync got to. |

The first five moved from `skins/` in step 5.4b without moving data (migrations `players.0005` and `skins.0032`, both state-only): they keep their `skins_*` tables and index names, and `BonkAccountLink.bonk_player` (still in `skins`) points here. Renaming a table or index is a separate, real migration.

## Worn skins

`BonkPlayer.worn_skin_code`, `worn_skin_seen_at` and `worn_skin_source` hold the skin the player last wore in game. `record_worn_skin` stores a sighting only if it parses as a skin (`core.bonk.SkinCode`) and is at least as new as the stored one, in one `UPDATE` so racing sightings can't leave the older one. The code is stored URL-decoded (plain base64).

| Source | When |
|---|---|
| `login` | A bonk.io login (the site's or the wear popup's): the skin in the reply's active slot |
| `wear` | A wear from Bonkverse that bonk.io accepted, into the session's active slot. Wears into another slot don't change what the player wears in game |

It is published as `skin` in `/api/v1/` ([public-api.md](../architecture/public-api.md)) and is the player's avatar everywhere a placeholder used to show:

| Where | How |
|---|---|
| Profile header (512 px) | `profile_base` → `skin_avatar` |
| Player cards, people lists (Overview's "Plays with most", People tab, a map's "Plays it with") | `with_skin_avatars(rows)`, one query per list |
| Friends tab | each row's `s` (the skin's version); the page and `player_friends.js` build the URL from the name |
| XP calculator | `skin` in `/tools/xp/player.json`; `xp_calculator.js` |
| Site header (signed in) and My Profile | `viewer_avatar` from `players/context_processors.py` (lazy): `user_skin_avatars(user)` through their `BonkAccountLink`, one indexed query, cached 5 minutes per user and cleared by `services.forget_user_skin` on sign-in and wear |
 `selectors.with_skin_avatars(rows)` adds the URL to any list of rows in one query; the partial `players/partials/_avatar.html` (and the header in `_layout.html`) passes it as the `--skin` CSS property, drawn as a background over the initials, so an image that can't load shows the initials (an `<img>` would show a broken-image icon). The URL carries `?v=<digest>` of the code, so it changes when the skin does and the week-long edge cache can't serve an old skin.

The image comes from `skins.services.code_image(skin_code, kind)` ([skin-images.md](../architecture/skin-images.md#images-of-a-skin-code)), rendered on the first request for that code.

Not yet: replay sightings for players who never sign in (the replay archive storing the avatar per participant, ADR 0011), and whether the avatar should have a privacy switch (today it's public, like the skin other players see in game).
