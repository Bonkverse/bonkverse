# bonk.io response fixtures

JSON bodies returned by bonk.io's account endpoints, used by tests to fake
bonk.io with the `responses` library. Per RFC-0001 these double as the
reference for the undocumented API in `docs/bonk/`.

Rules:
- Tokens are always scrubbed (`SCRUBBED-...`). Never commit a live token,
  password, or real player's private data.
- Prefer bodies captured from real responses over hand-written ones.
  A fixture marked `synthetic` below was written by hand from the code's
  expectations and should be replaced with a recorded body when convenient.

| File | Endpoint | Source |
|------|----------|--------|
| `login_success.json` | `login_legacy.php` | synthetic |
| `login_wrong_password.json` | `login_legacy.php` (HTTP 200 with failure body) | synthetic |
| `avatar_update_success.json` | `avatar_update.php` | synthetic |
| `avatar_update_token_expired.json` | `avatar_update.php` | synthetic |
