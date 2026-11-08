# Rate limiting

Two layers. Cloudflare stops floods before they reach Railway; Django limits
every route per visitor and shows a friendly 429.

## Cloudflare (edge)

One WAF rate-limiting rule, **Search Endpoint**: URI path contains `/search`,
50 requests per 10 s per IP, blocks for 10 s. Blocked visitors see Cloudflare's
**error 1015**. Keep it at 50/10 s: search is index-backed now
([ADR 0002](../adr/0002-index-backed-search.md)), and the origin limit (60/min)
is the precise one.

## Django (origin)

Every view is wrapped in `@limit("<tier>")` (`core/ratelimits.py`). Tiers live
in `settings.RATE_LIMITS`; each can be overridden with `RATE_LIMIT_<TIER>`:

| Tier | Default | For |
|---|---|---|
| `browse` | 120/m | Page views: home, categories, leaderboards, profiles |
| `search` | 60/m | Skin and player search |
| `media` | 600/m | Skin images and SVGs under `/media/` |
| `write` | 30/m | Editing/deleting own skins, matchmaking, re-render |
| `vote` | 500/h | Upvote, downvote, favorite |
| `upload` | 10/m | Skin uploads |
| `login` | 15/h, POST only | bonk.io login attempts |
| `submit` | 7/h | Discord server submissions |
| `api` / `api_partner` | 60/m / 300/m, **per API key** | Public API reads (`/api/v1/`), [public-api.md](../architecture/public-api.md) |
| `api_bulk` / `api_bulk_partner` | 10/m / 30/m, **per API key** | `POST /api/v1/lookup/players/` (up to 250 names each) |
| `api_auth_fail` | 20/m, per IP | Failed key checks on `/api/v1/` before that IP waits |

The public API's tiers use `public_api.auth.api_endpoint` instead of `@limit`:
they count per key, add `RateLimit-Limit/-Remaining/-Reset` headers to every
reply, and partner keys use the `*_partner` rate.

**Flow:** `@limit` asks django-ratelimit to count the request in Redis under a
key built from the view and the client IP, in fixed windows. Over the limit:

- Pages get `429.html` with a live countdown; GET pages reload themselves when
  the window ends.
- JSON requests get `{"ok": false, "error": "rate_limited", "retry_after": n}`.
- Both send `Retry-After`.

**Real client IP** (`core/client_ip.py`): behind Railway, `X-Real-IP` is the
connecting address. If that address is Cloudflare's, the visitor is
`CF-Connecting-IP`; otherwise `X-Real-IP` itself. Only on when
`TRUST_PROXY_HEADERS=true` (production default), because locally anyone could
send those headers.

**Redis down:** `RATELIMIT_FAIL_OPEN = True`. Requests go through unlimited
rather than everyone being blocked. Cloudflare still applies.

## Adding a route

Decorate the view with `@limit("<tier>")` (pick the closest tier; add a tier in
settings only if none fits). `tests/test_rate_limits.py` fails if any route has
no tier. See every route and its tier with:

```
python manage.py audit_rate_limits            # all routes
python manage.py audit_rate_limits --missing  # only untiered ones
```

## Looking at counters locally

Keys are `bonkverse:1:rl:<hash>` in Redis:
`redis-cli --scan --pattern 'bonkverse:1:rl:*'`, then `GET` / `TTL` a key.
