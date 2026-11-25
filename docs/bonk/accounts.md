# bonk.io accounts and usernames

What bonk.io usernames can look like, and how Bonkverse handles them.
Code: `core/bonk/usernames.py` (`BonkUsername`). Tests: `tests/test_bonk_types.py`.

## bonk.io's rules for new accounts

From the [bonk.io wiki](https://bonkio.fandom.com/wiki/Accounts):

- Letters, numbers, spaces or underscores only
- At most 15 characters
- Can't start with a space or underscore
- Can't contain "Chaz" (the developer)
- No more than one space in a row (a recently added rule)

**These rules are newer than many accounts.** Older names keep whatever was
allowed when they were made, so Bonkverse must not apply these rules to names it
gets from bonk.io.

## What real names look like

Audit of names stored from bonk.io logins (site accounts), friend lists
(players) and legacy Flash friend lists, run 2026-11-03 against production
(read-only). Counts are names that break at least one new-account rule;
names themselves are not recorded here.

| Breaks | Players | Site accounts | Flash friends |
|---|---:|---:|---:|
| Longer than 15 characters | 289 | 6 | 56 |
| Shorter than 3 characters | 101 | 3 | 27 |
| Repeated spaces | 121 | 1 | 52 |
| Characters other than letters, numbers, space, underscore | 34 | 0 | 6 |
| Trailing space | 20 | 1 | 5 |
| Leading space or underscore | 8 | 2 | 1 |
| Starts with "Guest" or "New Player" | 55 | 1 | 5 |
| Contains "Chaz" | 1 | 0 | 1 |
| **Any of the above** | **605** | **12** | **147** |

What that shows:

- **Length 1 to 35.** 35 looks like an older limit (17 names are exactly 35
  long); 20 is another common length, likely an older limit too.
- **Punctuation exists:** `. ! - ; : [ ] ( ) * $ ' < / & ?` all appear.
- **Spaces matter.** Leading, trailing and repeated spaces are part of real
  names, and a name with a leading space can be a different account from the
  same name without it. Never trim a bonk.io username.
- **"Guest…" names are real accounts.** At least one has signed in to
  Bonkverse. Don't treat a "Guest" prefix as a guest.
- **"Chaz" exists** (the developer's own account).

## How Bonkverse handles usernames

- A name from bonk.io (login response, friend list) is stored **exactly as
  bonk.io spells it**. `BonkUsername` only rejects what no account can have:
  empty, over 64 characters (headroom over the 35 seen), or control characters.
- The login form doesn't strip spaces (`LoginForm.username` has `strip=False`).
- Compare names with `core.bonk.same_name(a, b)` (or `BonkUsername.key`):
  case-insensitive, spaces kept. See "One rule for the same name" below.
- Login finds the site account with a case-insensitive match
  (`accounts.sign_in.site_account_for`), preferring an exact spelling if older
  data has more than one. An existing account keeps its stored spelling,
  because skins name their creator by it. A login without a bonk.io id
  matches its `BonkPlayer` the same way.
- Published skins record the signed-in account's name exactly
  (`skins/views/publish.py`); it used to be trimmed (fixed in Phase 2.2).
- Display a name with the capitalization bonk.io returned; never re-case it.

## Case

**Usernames are unique case-insensitively.** Verified 2026-11-03: trying to
register "the saucy tulip" on bonk.io fails with "username taken" because
"The Saucy Tulip" exists. So two accounts never differ only by capitalization,
and a case-insensitive match identifies one account. bonk.io keeps the
capitalization the owner chose; that spelling is what we store and show.

**Login accepts any capitalization.** Verified 2026-11-03: logging in as
"the saucy tulip" signs in to "The Saucy Tulip". The login response returns
the account's own spelling, which is what Bonkverse stores, so a player who
types a different capitalization still lands on the same site account.

## One rule for the same name

Two spellings are the same account when they are equal after lowercasing
**A-Z only** (`core.bonk.usernames.fold`, `same_name`). Every other
character, including accented and other non-English letters, must match
exactly.

Why not the usual tools: each of them also turns some non-English letters
into English ones, and they disagree about which.

| Tool | Used by | Also treats as equal |
|---|---|---|
| Postgres `UPPER()` | `__iexact` | "ı" (U+0131) = "i", "ſ" (U+017F) = "s" |
| Postgres `lower()` | the replay site's name match | "İ" (U+0130) = "i", the Kelvin sign (U+212A) = "k" |
| Python `str.lower()` | cache keys, dict keys | the Kelvin sign = "k" |
| Python `str.casefold()` | | "ſ" = "s", "ß" = "ss", the Kelvin sign = "k" |

Found in the 2026-11-25 audit, checked on Postgres 16 (`en_US.utf8`, the
image's default):

- A profile URL written with a look-alike letter (`/player/Foo%E2%84%AA/`
  for "Fook") found the player's replays and friend list but not the account
  holding their privacy switches, so every hidden section was shown to
  anyone. Now a profile, player or account found under another name than
  the one asked for is not that player's (`players/selectors.py`).
- A login finds its site account by name. A bonk.io account named "admın"
  would have been signed in to the site account "admin". No such bonk.io name
  is known to exist (the audit above found only ASCII punctuation), and
  whether bonk.io would register one is untested; Bonkverse no longer
  depends on it.

So: `__iexact`, `lower()` and `casefold()` may narrow a search, but
`same_name` decides whenever the answer grants something (who is signed in,
whose privacy switches apply, who owns a skin).

- In SQL the same rule is `Lower(Collate(field, "C"))`: under the "C"
  collation Postgres's `lower()` changes only A-Z
  (`public_api/selectors.py`).
- Dicts of players or accounts by name are keyed with `fold`, not
  `lower()`, so a look-alike has its own key and can't answer for, or hide,
  the real name.
- The rule is stricter than bonk.io's may be. If bonk.io counts two
  spellings that differ in a non-English letter's case as one account, a
  login under the other spelling makes a second site account here. Such a
  login logs a WARNING from `accounts.sign_in` ("matched site accounts ...
  only by a look-alike letter", ids only): if it ever appears, look at
  whether it was an attempt or a real player.

## Open questions

- Is "leading space" really a separate account, or bonk.io storing the same
  account's name with a space? Registration with a leading space isn't
  possible today, so these are older accounts.

## Re-running the audit

The query is read-only and writes a CSV on your machine (`*.csv` is
gitignored; never commit it). Ask for `bonk_username_audit.sql` or see
`claude/rfc-0001-progress.md` in the project notes.
