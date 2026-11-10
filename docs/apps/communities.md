# communities

The Discord server directory: the list of bonk.io community servers, filtering by text and tag, a page per server with its member history, submitting a server, and the hourly member-count refresh. Created in RFC-0001 Phase 5.2.

**Owns:** which servers are listed and how, the submit rules (permanent invites only, one entry per server, only existing tags), snapshots of member and online counts. **Does not own:** the Discord API call (`integrations/discord_api.py`, see [integrations.md](../architecture/integrations.md)), the page frame (`skins/base.html`).

## Routes

| Path | Name | View |
|---|---|---|
| `/serverlist/` | `list` | `views/pages.py: server_list` (`?q=` text, `?tag=` repeatable) |
| `/<uuid:server_id>/` | `detail` | `views/pages.py: server_detail`: last 30 snapshots, oldest first |
| `/submit/` | `submit_server` | `views/pages.py: submit_server_page` |
| `/api/discords/submit/` | `api_submit_server` | `views/submit.py: submit_server` (POST `invite`, `tags`; rate limit `submit`) |

The detail path sits at the site root (`/<uuid>/`), which is why it's matched by UUID only.

## Layers

- `selectors.py`: `listed_servers(query, tag_names)`, `all_tags()`, `recent_snapshots(server)`, `next_refresh_at()` (last run of the refresh schedule + `REFRESH_INTERVAL`).
- `services.py`: `submit_server(invite, tag_names) -> SubmitResult` with a `SubmitOutcome`; `extract_invite_code()`. The view turns each outcome into the message people see.
- `tasks.py`: `refresh_discord_servers`, hourly from `CELERY_BEAT_SCHEDULE["refresh-discord-servers"]`. One lookup per second, stalest first, stops on a second 429, at most once per run (`acks_late=False`). Details: [background-work.md](../architecture/background-work.md).
- `management/commands/populate_discord.py`: local seed data.

**Task name:** the refresh is registered as `skins.tasks.refresh_discord_servers` (`selectors.REFRESH_TASK`), its name from before the move, so the saved schedule row, its "last run" (shown as "next refresh" on the list page) and any run queued during a deploy keep working. Its log lines come from logger `communities.tasks`. `tests/test_communities.py` pins this.

## Models

`communities/models.py`: `DiscordTag`, `DiscordServer` (UUID primary key, unique `guild_id`, `tags` many-to-many), `DiscordServerSnapshot` (indexed on server + time). Moved from `skins/` in 5.2b **without moving data**: they keep the tables `skins_discordtag`, `skins_discordserver`, `skins_discordserver_tags` and `skins_discordserversnapshot` (`db_table` on each model and on `tags`), and the snapshot index keeps its name. Don't rename them; Django would rename the real tables. Not registered in `/admin`.

## Open product question

Servers whose invite has died stay listed (the refresh counts them as `not_found` and leaves the row). Hiding them after some failed refreshes is undecided.
