# public_api

What other sites and bots can read from Bonkverse (`/api/v1/`), the API keys
that let them, and the developer portal where people request and manage keys
(`/developers/`). It existed before Phase 5. How the API behaves, its
endpoints and how to issue or revoke a key: [architecture/public-api.md](../architecture/public-api.md);
why: [ADR 0011](../adr/0011-public-api.md).

**Owns:** `ApiKey`, `ApiTermsAcceptance`, the key format and lookup
(`keys.py`), reading the key from a request and per-key rate limits
(`auth.py`), the reply envelope (`responses.py`), the portal's rules
(`services.py`), the `/api/v1/` views and the portal pages.
**Does not own:** the data it serves. Players come from `players.selectors`
(profile, worn skin, account age, profile path) and the replay site
(`integrations/replays.py`).

## Routes

Two URL files, two namespaces:
- `public_api/urls.py`, included at `/api/v1/`: namespace `public_api`.
- `public_api/portal_urls.py`, included at `/developers/`: namespace `developers`
  (`developers`, `developer_terms`, `developer_keys`, `developer_revoke_key`).

API routes use the `api` and `api_bulk` rate tiers, counted per key (`auth.py`).

## Files

```
public_api/
  models.py        # ApiKey (hashed secret, prefix, tier), ApiTermsAcceptance
  keys.py          # key format ("bvk_<prefix>_<secret>"), hashing, lookup
  auth.py          # Bearer key from the request, 401s, per-key limits, last used
  selectors.py     # player entries, built from players.selectors
  services.py      # portal rules: API terms, key limit per account, create / revoke
  responses.py     # {"ok": true, "data": ...} / {"ok": false, "error": ...}
  views/           # api.py (/api/v1/) and portal.py (/developers/)
  templates/developers/, static/public_api/
  management/commands/  # create_api_key, revoke_api_key
```

Admin: API keys and terms acceptances (`/admin/public_api/`).
