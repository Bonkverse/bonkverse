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
- Compare names with `BonkUsername.key` (case-insensitive, spaces kept).

## Open questions

- # BONK: Does bonk.io treat usernames case-insensitively at login and in
  friend lists? Not verified. The audit's case-only duplicate check would
  answer part of it.
- Known bug: `apis/publish_skin.py` strips the creator name, so a creator whose
  name has leading/trailing spaces is saved without them.

## Re-running the audit

The query is read-only and writes a CSV on your machine (`*.csv` is
gitignored; never commit it). Ask for `bonk_username_audit.sql` or see
`claude/rfc-0001-progress.md` in the project notes.
