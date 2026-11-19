# skins

The skin gallery: skins and their images, search, browsing by category, a skin's own page and share link, your skins (edit, delete), upload and publish from the editor, votes, favorites, reports, and wearing a skin on bonk.io. It was the original do-everything app; RFC-0001 Phase 5 moved everything else out, and step 5.6b gave what's left the RFC's layout.

**Owns:** the `Skin` model and what changes it (votes, favorites, reports, images, imports), the gallery pages and the skin-card JSON endpoints. **Does not own:** signing in or the bonk.io session (`accounts`), players and profiles (`players`), leaderboards (`stats`), talking to bonk.io, the render service, Cloudflare or BonkBot (`integrations/`).

## Routes

Names are in the `skins` namespace (`app_name` in `skins/urls.py`): `{% url 'skins:<name>' %}`, `reverse("skins:<name>")`.

All in `skins/urls.py`; views in `skins/views/`, one module per area.

| Path | Name | View |
|---|---|---|
| `/search/` | `search_skins` | `views/search.py` (index-backed, time-limited: [search.md](../search.md)) |
| `/skins/detail/<id>`, `/skins/share/<id>/<uuid>/` | `skin_detail`, `share_skin` | `views/skin_detail.py`, `views/share.py` (old share links: a permanent redirect to the skin page) |
| `/new/`, `/categories/`, `/category/<slug>/` | `new_releases`, `category_index`, `category_detail` | `views/browse.py` (categories and their queries: `categories.py`) |
| `/my-profile/` (redirect to your profile's Skins tab), `/skin/<id>/edit/`, `/skin/<id>/delete/`, `/skins/bulk-delete/` (JSON, POST, owner only) | `my_profile`, `edit_skin`, `delete_skin`, `bulk_delete_skins` | `views/my_skins.py`; edit rules in `editing.py`; the owner tools on the profile's Skins tab are `partials/_skin_owner_dialogs.html`, `js/skin_owner.js`, `css/skin_owner.css` |
| `/upload/` | `upload_skin` | `views/upload.py` (BonkLeagues link → `skin_import.py`) |
| `/skins/<id>/rerender/` | `rerender_skin` | `views/rerender.py` (staff; the re-render itself is `rerender.py`) |
| `/moderation/`, `/moderation/skins/<id>/decide/` | `moderation`, `moderation_decide` | `views/moderation.py` (staff only, `core.auth_guards.staff_required`; the work is `moderation.py`) |
| `/api/` | `api_index` | `views/api_index.py` |
| `/api/skins/<id>/vote/`, `…/favorite/`, `…/report/` | `api_vote_skin`, `api_toggle_favorite`, `report_skin` | `views/votes.py`, `views/report.py` |
| `/api/skins/<id>/wear/`, `/api/skins/wear-code/`, `/api/bonk/login/` | `wear_skin`, `wear_skin_code`, `bonk_login_for_wear` | `views/wear.py` |
| `/api/publish-skin/`, `/api/bot/skins/` | `publish_skin`, `api_bot_submit_skin` | `views/publish.py` (the editor), `views/bot_skins.py` (BonxBot) |
| `/matchmaking/`, `/api/join-matchmaking/` | `matchmaking` | `views/matchmaking.py` |
| `/media/<path>` | | `views/media.py` (rate limit, cache headers) |

## Public entry points for other apps

- `skins/selectors.py`: skin cards (`decorate_skins_for_user`), home strips, top skins, a creator's skins and stats, favorites; reads other pages need about players and links (`bonk_players_named`, `account_links_for`, `flash_friend_counts`).
- `skins/services.py`: `code_image(skin_code, kind)`, images for any skin code (players' worn-skin avatars).

## Inside the app

- `votes.py`: `cast_vote`, the one way vote counters change (ADR 0014); `recount_votes`, `fix_vote_counts` for `audit_vote_counts`.
- `skin_media.py`: the one writer of skin image files and rows (`save_render`; [skin-images.md](../architecture/skin-images.md)).
- `rerender.py`: `rerender(skin)`, shared by the staff button and `rerender_skins`.
- `skin_import.py`: importing a BonkLeagues skin (upload form, BonxBot); `bonxbot_migration.py`: the one-time BonxBot import behind `import_bonxbot_skins`.
- `submitters.py`: who sent a skin in (`Submission`: upload form, editor, BonxBot), kept apart from who made it (`creator`; `creator_source` says where that name came from), and `backfill_submitters` behind `backfill_skin_submitters` for skins added before submitters were stored.
- `editing.py`: what an owner can change: the name and one flat list of tags (`tags_of`, `edit`). Tags are `labels.themes/objects/references`; a removed tag leaves whichever list held it, a new one goes into `themes`; `style`, `colors` and the description are left alone (the description is no longer shown or edited).
- `moderation.py`: the staff report queue (`report_queue`, reports grouped by skin) and its three decisions, `dismiss`, `change_creator` (the new name also becomes the owner; `creator_source = staff`) and `delete`. Each one closes all of the skin's open reports in one transaction and records a `ModerationDecision` (who, what, note, the reporters' ids, old and new creator) that outlives a deleted skin, so reporters and creators can be told later. The Django admin's "Mark as resolved" still works but records no decision.
- `svg_sanitizer.py`, `querysets.py` (`Skin.objects`: search, scores, periods), `categories.py`, `skin_code.py`.
- Featured places: category covers, the home strips and the leaderboards use `Skin.objects.without_open_reports()`, so a skin with an unresolved `SkinReport` drops out of them until staff decide on it on the report queue (`/moderation/`, in the account menu for staff). Search and the skin's own page still show it. Category covers are hand-picked in the admin (`CategoryCover`, one skin per category); a category without a pick shows an empty tile. Covers are never picked automatically, because the most upvoted match can be anything (design review 2026-11-09).

## Management commands

`audit_skin_codes`, `audit_vote_counts`, `audit_rate_limits`, `rerender_skins`, `import_bonxbot_skins`, `init_pg_extensions`, and the local seed commands `populate_all` / `populate_skins` (never in production). Step 5.6a removed six finished one-off commands.

## Models

`Skin`, `SkinVote`, `SkinImage`, `SkinReport` (tables `skins_*`). The event log (`UserEvent`) belongs to `accounts` since 5.6c; skins writes to it through `accounts.services.log_event`. The page frame (`base.html`, header, footer, error pages, shared scripts and styles) left `skins` in 5.6d for the project's `templates/` and `static/`; the skin partials (cards, report modal) and the skin pages' own CSS/JS stay here.
