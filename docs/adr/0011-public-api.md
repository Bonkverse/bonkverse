# ADR 0011: A public, versioned API for other sites, with keys

**Status:** accepted, 2026-11-08

**Context.** Other sites now want Bonkverse data. The first is Luna's
competitive leaderboard, which wants each listed player's level, when it was
last seen, and later their skin. Until now every Bonkverse endpoint served
Bonkverse's own pages. Player data lives in two databases: replay numbers in
the replay site's (served by ReplayRenderer's `/api/player*`, open and
unversioned), and accounts and privacy switches (`ProfileVisibility`) in
Bonkverse's. A partner calling the replay site directly would also get
levels that a player hid on bonkverse.io.

**Decision.**
- One public API, in Django, at `bonkverse.io/api/v1/` (`public_api/`). It
  combines replay data (through `integrations/replays.py`) with Bonkverse
  data and applies each player's `ProfileVisibility`: a hidden Level
  section means no level here either (`status: "private"`).
- Every request needs an API key (`Authorization: Bearer bvk_…`). Keys are
  issued by hand (`manage.py create_api_key`), stored as SHA-256 hashes,
  revocable, and tied to a name and contact. No sessions or cookies, so no
  CSRF.
- Limits count per key, with `RateLimit-*` headers; partner keys get a
  higher tier. Failed key checks are limited per IP.
- Replies use RFC-0001's envelope (`{"ok", "data"}` / `{"ok", "error"}`).
  Within v1, fields and error codes are only added, never renamed or
  removed; a breaking change is `/api/v2/`.
- Only replay-derived data is published. XP from a player's own bonk.io
  login (`BonkPlayer.xp`) was given to Bonkverse, not to other sites.
- Times say what was observed: `seen_at` is when a replay showing that
  level was collected, not when the level changed.
- The guide for people using the API lives in the platform docs site,
  `Bonkverse/docs` (docs.bonkverse.io/api), as RFC-0001 places
  cross-service contracts ([ADR 0012](0012-docs-site.md)). How to run the
  API stays in this repo: `docs/architecture/public-api.md`.

**Consequences.**
- Partners depend on Bonkverse being up, and on the replay site behind it
  (503 `upstream_unavailable` when it isn't). Answers are cached per
  player for `PLAYER_PROFILE_CACHE_SECONDS`.
- ReplayRenderer's player API is still open. Bonkverse's privacy switches
  only hold for callers that use this API; closing the replay API to
  Bonkverse alone is a follow-up.
- Each player's `skin` (added 2026-11-14) is their newest worn skin
  Bonkverse has seen (`BonkPlayer.worn_skin_*`): at their bonk.io login, a
  wear from Bonkverse, or in a replay. ReplayFetcher stores the skin per
  participant row (`avatars`, `replay_participants.avatar_hash`) and the
  replay sync brings each name's newest one in.
- Every PR that changes `/api/v1/` links a matching `Bonkverse/docs` PR,
  merged together (the PR template asks).
- Reference: [architecture/public-api.md](../architecture/public-api.md).
