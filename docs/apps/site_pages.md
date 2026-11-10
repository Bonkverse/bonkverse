# site_pages

The site's own pages: the home page, privacy, terms, the staff page, and small tools that don't belong to a domain (the map decoder). Created in RFC-0001 Phase 5.1.

**Owns:** what these pages show. **Does not own:** the skins on the home page (`skins.selectors.home_strips`), the page frame and skin partials (`skins/base.html`, `skins/partials/`, until step 5.6), the map decoder service call (`integrations/map_decoder.py`), the XP calculator (`players`).

## Routes

| Path | Name | View |
|---|---|---|
| `/` | `home` | `views/pages.py: home`: four skin strips (newest, random, most favorited, trending) |
| `/privacy/` | `privacy` | `views/pages.py: privacy` |
| `/terms/` | `terms` | `views/pages.py: terms` |
| `/staff/` | `staff` | `views/pages.py: staff_page`: the team, from `STAFF_MEMBERS` |
| `/tools/map-decode/` | `map_decode_page` | `views/tools.py: map_decode_page` |
| `/api/tools/map-decode/` | `api_map_decode` | `views/tools.py: api_map_decode` (POST `encoded`; 400 / 502 / 503 as in [integrations.md](../architecture/integrations.md)) |

All are rate-limited `browse`, except the decode API (`search`).

## Files

```
site_pages/
  views/pages.py, views/tools.py
  urls.py                         # included at "" from bonk_skin_search/urls.py
  templates/site_pages/           # home, privacy, terms, staff, map_decoder
  static/site_pages/css/          # privacy.css, terms.css
  static/site_pages/js/           # map_decoder.js
```

No models. The changelog was retired in 5.1 (it had no page and no visible banner); its `Changelog` model and `skins_changelog` table were deleted in 5.1b (`skins/migrations/0029_delete_changelog.py`, rows not kept, owner decision).

## Changing the staff page

Edit `STAFF_MEMBERS` in `views/pages.py`; images are in `skins/static/images/`.
