# players

bonk.io players as Bonkverse knows them: profiles built from the replay archive, the player directory and search, the friend graph (bonk.io friends and Flash-era friends), social stats, the XP calculator and profile privacy. The app existed before Phase 5 (profiles, replay sync, privacy); RFC-0001 step 5.4 moved the friend sync, player search APIs and social stats in from `skins/`, and 5.4b moved the player models.

**Owns:** what a profile shows and who may see it, storing friend lists, the skin each player last wore (`worn_skins.py`), syncing names and DBIDs with the replay archive. **Does not own:** signing in or the bonk.io session (`accounts`), talking to bonk.io or the replay archive (`integrations/`), the event log the sync writes to (`accounts.services.log_event`).

## Routes

Names are in the `players` namespace (`app_name` in `players/urls.py`): `{% url 'players:<name>' %}`, `reverse("players:<name>")`.

| Path | Name | What |
|---|---|---|
| `/players/` | `players_directory` | Directory and search (`views.directory`, rules in `search.py`) |
| `/players_search/players/`, `/players_search/flash-friends/` | `players_page`, `flash_friends_page` | Old search pages, kept for old links |
| `/player/<username>/` and `…/activity/`, `level/`, `maps/`, `people/`, `friends/`, `skins/` | `player_profile`, `player_activity`, … | Profile tabs (`views.py`, data from `selectors.py`) |

**One profile** (design review): there is no separate My profile page any more (`/my-profile/` redirects to your Skins tab). Looking at your own profile, the header adds Upload a skin and Profile settings, and the Skins tab's Created view uses the owner card (Edit name and tags, Copy link, Delete, Select within the page and delete; the skins app's `_skin_owner_dialogs.html` and `js/skin_owner.js`). Everyone else sees the visitor card. After a login that started a friend sync, the first page shows its progress (`context_processors.friend_sync`, `js/friend_sync.js`).
| `/player/<username>/skin.png`, `…/skin-thumb.png` | `player_skin_avatar`, `player_skin_avatar_thumb` | The player's worn skin as a 512 / 128 px PNG (`views.skin_avatar`, `media` rate tier); 404 when there's none |
| `/settings/profile/` | `profile_settings` | Who sees which profile section |
| `/tools/xp/` (+ `player.json`, `levels.json`) | `xp_calculator`, … | XP calculator |
| `/social-stats/` | `social_stats` | Friend-graph totals and most-connected players (`social_stats.py`) |
| `/api/players/search/`, `/api/flash-friends/search/` | `players_search`, `flash_friends_search` | JSON search (`api.py`) |
| `/api/friends-sync-status/` | `friends_sync_status` | Polled by My Profile's toast after login (`api.py`) |

`<username>` is the `username` converter (`converters.py`, registered in `PlayersConfig.ready()`): `.` and `..` get a `~` in front.

## Directory search

The search box is trimmed and finds names containing it. A name equal to it, ignoring case and spaces at the end of the name, comes first: padded accounts ("ako" + 17 spaces) look unpadded wherever they're shown, so typing what you see finds them. The **In replays** view asks the replay site (`/api/players`), which answers any length: the exact name (same rule) first, then, from 3 characters, the most played names starting with it.

The advanced search (`search.py`) has a per-rule **␣** switch next to **Aa**, "ignore spaces at the end of names" (`t0`, `t1` … in the address). With it on, a Name rule compares against the name with its trailing spaces removed (and the typed value too), so "Name is exactly ako" finds the padded account. The replay site's builder has the same switch for Player, Map name and Map author.

## Public entry points for other apps

`players/services.py`: `queue_friend_sync(account_link_id)`, `queue_login_friends(account_link_id, friends, requests)`, `sync_flash_friends_for_user(...)`, `adopt_replay_names(...)` (all used by `accounts/sign_in.py`), `record_worn_skin(bonk_id, skin_code, source)` (used by `accounts/sign_in.py` and `skins/views/wear.py`), `update_visibility(...)`. `players/selectors.py` for reads (profiles, directory, calculator).

## Background work

`tasks.py`:
- `sync_login_friends`, queued at login when bonk.io's login answer carried the friend list: stores it without calling bonk.io.
- `sync_friends`, queued at login otherwise (reads `friends.php`), registered as **`skins.tasks.sync_friends`** (its name before the move, so runs queued during a deploy keep working; pinned by `tests/test_friend_sync_task.py`).
- `sync_replays`, every 5 minutes (`REPLAY_SYNC_INTERVAL_SECONDS`): new players appear a few minutes after their replay reaches the archive.

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

Player profiles (every tab, settings, not found) are on Bonkverse/ui components (`site-page`): their own styles are `players/static/players/css/profile.css` (tokens only), `controls.css` (`bv-seg`) and `charts.css` (the Level chart). `profile.js` keeps the tab row's current tab in view and fades the edge that scrolls; `profile_settings.js` saves each switch as it's flipped (the view answers `Accept: application/json` with `{"ok": true}`). The Players page is on components too (`directory.css`, plus `profile.css` for avatars and small text): cards are one link with a worn-skin avatar, a level pill, a labelled Member pill and two stats, and the DBID small under the name (also on the profile header). The XP calculator is on components too (`xp_calculator.css`, `controls.css`, `charts.css`, `profile.css`). It never opens empty: it loads `?player=`, else the signed-in viewer's own linked account (`views._calculator_player`), and until a player loads (or if loading fails) the plan shows an example, a new account going for level 100, with a note saying so. The old `player_profile.css` is gone: every player page is on components.

Review rules the profile follows: the level is shown once (the header leaves it out when the Overview's level card shows it); a stretch of more than `charts.GAP_DAYS` without replays in which the level rose is drawn dashed (sparkline and Level chart); modes are a sorted bar list (`charts.mode_bars`), and a room split that is all one kind is a sentence, not a full bar; People is one list with a `?list=with|team|against` switch; names wrap instead of being cut off.

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

The first five moved from `skins/` in step 5.4b without moving data (migrations `players.0005` and `skins.0032`, both state-only): they keep their `skins_*` tables and index names, and `accounts.BonkAccountLink.bonk_player` points here. Renaming a table or index is a separate, real migration.

## Worn skins

`BonkPlayer.worn_skin_code`, `worn_skin_seen_at` and `worn_skin_source` hold the skin the player last wore in game. `record_worn_skin` stores a sighting only if it parses as a skin (`core.bonk.SkinCode`) and is at least as new as the stored one, in one `UPDATE` so racing sightings can't leave the older one. The code is stored URL-decoded (plain base64).

| Source | When |
|---|---|
| `login` | A bonk.io login (the site's or the wear popup's): the skin in the reply's active slot. An empty slot is bonk.io's default skin (`DEFAULT_SKIN_CODE`), so a new account's avatar is the plain ball, and it replaces an older replay sighting |
| `wear` | A wear from Bonkverse that bonk.io accepted, into the session's active slot. Wears into another slot don't change what the player wears in game |
| `replay` | The replay sync (`replay_sync.py`): each name's newest skin in a batch of replays, dated by when the replay was collected (or its estimated day for cycle 5 and the backlog). Stored by name with `record_replay_skins`, one `UPDATE` per batch, on every BonkPlayer with that name (DBID-less copies too), and without touching `updated_at` (the DBID push's cursor) |

Login and wear are stored by `bonk_id`; replays by name, because replays only carry names. Replays send skins as `{layers, bc}`; `core.bonk.SkinCode.from_avatar` writes the skin code the way the editor does (dense layers, empty slots dropped, since only order changes the drawing).

To fill in skins for names synced before skins were sent, read the archive once more: `python manage.py sync_replays --names-only --from-start` (about 210 batches of 5,000 replays; run it again until it says "up to date"). Names already known are skipped; only skins are written.

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

Not yet: whether the avatar should have a privacy switch (today it's public, like the skin other players see in game).
