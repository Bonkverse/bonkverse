# ADR 0023: A person's bonk.io accounts are a group of site accounts

**Status:** accepted, 2026-11-24 (RFC-0003 phase 5, PR 1)

**Context.** Many players have several bonk.io accounts (alts). RFC-0003 rev. 2
decided on an account switcher: the accounts are "separate, but grouped".
Each has its own profile, favorites, votes and uploads. The account in use
decides Wear, credit, votes, favorites and the header. Switching needs no
password, appearance is shared, and removing an account takes its history
with it.

The site already has one site account (`BonkUser`) per bonk.io name: sign-in
finds or creates it by username, `Skin.is_owned_by` compares names, and
favorites, votes, privacy and submissions point at `BonkUser`. Two shapes
were possible:

1. **One site account per person**, with each bonk.io account as a link under
   it. Every table that's per account today (favorites, votes, privacy,
   reports, submissions) would need a column for which link was in use, plus
   a backfill, and the username-based rules (ownership, profiles, credit)
   would read from the active link instead of `request.user`.
2. **One site account per bonk.io account, as today, plus a group** that ties
   a person's site accounts together.

**Decision.** Shape 2.
- `AccountGroup` (`main`), and `BonkUser.account_group` and `joined_group_at`.
  A group never has a single member.
- **The account in use is `request.user`.** Switching logs the browser in as
  another account of the group, so everything that reads `request.user` (Wear
  through `active_link`, uploads, votes, favorites, the header, `/api/me/` for
  the other sites) follows with no change. The session's bonk.io identity is
  reset to the new account's latest link.
- **Switching only between accounts signed in on this browser.** The session
  keeps their ids (`groups.SIGNED_IN_KEY`) across Django's session flush. The
  group's other accounts show "Sign in" (a password login). This is the
  new-device guard in its strictest form until trusted devices (phase 5,
  PR 3) relax it.
- **Only "Add account" groups.** That's `/login/?add=1`, or a Wear popup login
  with a different account. A plain login while signed in replaces the
  session as before, so logging in to a friend's account on your browser
  doesn't group it. Adding an account that's in another group moves it: the
  password proves who controls it now.
- **Removing:** the account itself, or the main while signed in here. Two
  becoming one deletes the group; the main leaving hands main to the next.
- **Shared:** appearance is written to every member when it changes, and a
  joining account takes the group's. API keys and the Discord link follow in
  PR 2.
- **The other sites switch through `/api/me/switch/`.** They can't send
  bonkverse.io's host-only CSRF token, so the endpoint takes JSON plus a
  custom `X-Bonkverse-Switch` header (a cross-site form can't send one, and
  CORS lets only our origins), and it checks `Origin` itself too.
- Site accounts that hold links to several bonk.io accounts from before this
  change are converted by `group_linked_accounts` (dry run by default). Their
  history stays on the site account it was saved under.

**Alternatives considered.**
- *Shape 1 (one site account per person)*: the "who's in use" column on every
  per-account table, its backfill, and the move of every username rule would
  touch most of the site. Removing an account would mean splitting rows out.
  With shape 2 removal changes one field.
- *Switching to any account in the group without signing in here*: what
  trusted devices will allow on a device the group used before. Without them,
  anyone who learns one account's password (shared, sold) could open all of
  the group's accounts on a new browser.
- *Grouping on any login while signed in* (as some sites do): one login to a
  friend's account would join it to your group.

**Consequences.**
- One vote per group (RFC-0003) isn't enforced yet. Separate accounts could
  always vote separately, so nothing gets worse; PR 2 counts a group's votes
  once and adds the level-5 rule.
- `is_staff` and other permissions stay per account. Staff tools see groups in
  a later PR.
- A person's site accounts are still found by username. The privacy of the
  grouping (who can see "also plays as…") arrives with per-account privacy in
  PR 2; until then nothing public shows a group.
