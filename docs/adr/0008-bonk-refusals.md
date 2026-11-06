# ADR 0008: How Bonkverse answers bonk.io refusals

**Status:** accepted, 2026-11-05 (#39; corrected in #40)

**Context.** bonk.io refuses requests with HTTP 200 and
`{"r": "fail", "e": "<code>"}`. When #31 was written the codes for wearing a
skin were unknown, so every refusal was treated as an expired token: the page
opened the bonk.io login modal. Production logs then showed the real codes.
On one evening, of 49 refused wears, 24 were `avatar_too_big`, 24
`ratelimited`, and 1 `token`. For the first two, logging in again can't help,
so the modal reopened after every login. bonk.io's `ratelimited` also appears
in bursts on most days, apparently limited by the server's IP, which every
Bonkverse user shares; what triggers it is unknown.

**Decision.**
- `integrations/bonk_api.py` maps each known code: `password`,
  `username_fail`, `token` → `token_rejected`, `avatar_too_big`,
  `ratelimited` → `rate_limited`. Anything else is `rejected`, logged with
  bonk.io's code.
- **Only `token_rejected` opens the login modal** (401 `auth: "bonk"`).
  Every other wear failure returns a status (422 / 503 / 502) and a `message`
  sentence, with no `auth` tag.
- After any `ratelimited`, the client makes **no bonk.io calls for 120 s** and
  answers `rate_limited` itself, so Bonkverse adds no requests while bonk.io
  is limiting the IP. The pause is per server process.

**Consequences.**
- A new refusal code shows "bonk.io didn't accept…" and appears in the logs
  as `bonk_error=<code>`; add it to the table when it's understood.
- During a pause, everyone sees "bonk.io is limiting requests from Bonkverse"
  for up to two minutes, even if bonk.io has already lifted the limit.
- If bursts continue, share the pause across workers (Redis) and find what
  else sends traffic to bonk.io from our IP.
- Reference: [bonk/api.md](../bonk/api.md).
