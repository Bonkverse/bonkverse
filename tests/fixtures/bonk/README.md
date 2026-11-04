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
| `login_success.json` | `login_legacy.php` | synthetic |
| `login_wrong_password.json` | `login_legacy.php` (HTTP 200 with failure body) | synthetic (community) |
| `login_unknown_username.json` | `login_legacy.php` (HTTP 200 with failure body) | synthetic (community) |
| `friends_success.json` | `friends.php` (includes a blank name and a bad id on purpose) | synthetic |
| `friends_token_expired.json` | `friends.php` | synthetic: the real code for a stale token is unknown |
| `avatar_update_success.json` | `avatar_update.php` | synthetic |
| `avatar_update_token_expired.json` | `avatar_update.php` | synthetic: the real code for a stale token is unknown |
