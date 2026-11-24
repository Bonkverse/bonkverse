# bonk.io response fixtures

JSON bodies returned by bonk.io's account endpoints, used by tests to fake
bonk.io with the `responses` library. Per RFC-0001 these double as the
reference for the undocumented API in `docs/bonk/api.md`.

Rules:
- Tokens are always scrubbed (`SCRUBBED-...`). Never commit a live token,
  password, or real player's private data. Names are made up.
- Prefer bodies captured from real responses over hand-written ones.
  A fixture marked `synthetic` below was written by hand and should be
  replaced with a recorded body when convenient (see "Recording a fixture"
  in `docs/bonk/api.md`).
- `synthetic (community)` means the field names and codes match what other
  open-source bonk.io clients rely on, but no body was recorded by us.

| File | Endpoint | Source |
|------|----------|--------|
| `login_success.json` | `login_legacy.php` | synthetic; `avatar1`–`avatar5` synthetic (community): DemystifyBonk's field names, real skin codes in slots 1–2, slot 3 empty, slot 4 null |
| `login_success_with_friends.json` | `login_legacy.php` | keys and their order from a real answer captured with bonk.io's own client (2026-11-23); values made up (the real answer had 1,229 friends). No `requests` key. `rememberToken` was `""` |
| `login_auto_success.json` | `login_auto.php` | keys from real answers recorded by the lab (2026-11-24): the login answer's keys without `rememberToken`; values made up |
| `login_auto_not_found.json` | `login_auto.php` (HTTP 200 with failure body) | recorded by the lab (2026-11-24): a revoked remember-me token |
| `login_clearauto_success.json` | `login_clearauto.php` | recorded by the lab (2026-11-24) |
| `login_wrong_password.json` | `login_legacy.php` (HTTP 200 with failure body) | synthetic (community) |
| `login_unknown_username.json` | `login_legacy.php` (HTTP 200 with failure body) | synthetic (community) |
| `friends_success.json` | `friends.php` (includes a blank name and a bad id on purpose) | synthetic |
| `friends_token_expired.json` | `friends.php` | synthetic: copies the recorded `avatar_update.php` code |
| `avatar_update_success.json` | `avatar_update.php` | recorded 2026-11-03 (identical to the old synthetic body) |
| `avatar_update_token_expired.json` | `avatar_update.php` | recorded: same body for a genuinely expired token (2026-11-05) and a tampered one (2026-11-03) |
| `avatar_update_too_big.json` | `avatar_update.php` | from production logs 2026-11-03 (old code logged bonk.io's raw body; no token in it) |
| `ratelimited.json` | `login_legacy.php` and `avatar_update.php` | from production logs, Oct 30 onward (same source) |
