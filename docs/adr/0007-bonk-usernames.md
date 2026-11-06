# ADR 0007: bonk.io names are stored exactly; identity is case-insensitive

**Status:** accepted, 2026-11-03 (#30, #31)

**Context.** Code trimmed and sometimes "cleaned" bonk.io usernames, and
matched accounts by exact spelling. A read-only audit of production found 764
stored names that break bonk.io's current new-account rules: real names are
1–35 characters and include punctuation, leading, trailing and repeated
spaces, and registered "Guest…" accounts. The owner verified on bonk.io that
names are unique case-insensitively ("the saucy tulip" can't be registered
because "The Saucy Tulip" exists) and that login accepts any capitalization.

**Decision.**
- `core.bonk.BonkUsername` accepts any name bonk.io returns, **exactly as
  spelled**: never trimmed or normalized. It rejects only empty names, names
  over 64 characters, and control characters.
- Identity comparisons use `BonkUsername.key` (casefold, spaces kept), and
  database lookups that identify an account use `username__iexact`.
- On login, the name bonk.io returns is the canonical spelling. An existing
  site account keeps its stored spelling (skins name their creator by that
  string); if old data holds two accounts differing only in case, the exact
  spelling wins and the collision is logged.
- Tests use made-up names; the audit's real names are never committed.

**Consequences.**
- A player who types their name in any capitalization reaches one account.
- Spaces are significant: " Name" and "Name" are different accounts.
- Renaming stored spellings, or merging case-colliding accounts, is a
  separate data migration if ever needed.
- Details and counts (no names): [bonk/accounts.md](../bonk/accounts.md).
