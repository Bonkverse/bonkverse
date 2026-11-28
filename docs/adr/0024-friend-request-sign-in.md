# ADR 0024: Signing in with a friend request

**Status:** accepted, 2026-11-24 (RFC-0003 phase 6)

**Context.** Bonkverse asked every player for their bonk.io password, which
some won't give a fan site, and every password login spends the login budget
bonk.io gives this IP. BonxBot has linked Discord users to bonk.io accounts
since 2026-11-17 without passwords: the player sends a friend request from
the account to a bot bonk.io account, which only its owner can do.

**Decision.**
- **Friend request is a way to sign in, and to add an account**, beside the
  password (`/login/friend/`). A request from NAME to the bot account, sent
  within 10 minutes after the claim started, proves NAME. A main signed in
  this way unlocks its group, the same as a password (ADR 0023).
- **The same bot account as BonxBot**, read with the same rules, until
  BonxBot uses the site in phase 7: names compare ignoring case, not spaces;
  request dates are US Eastern; a request proves at most one claim; matched
  requests are deleted at once, unmatched ones only when older than any
  claim can be, so neither side deletes the other's fresh requests. Requests
  are deleted, never accepted.
- **Read only while needed.** The worker checks every 30 s, but reads the
  bot's requests only while a claim is pending: one `friends.php` call for
  every claim. The bot's session comes from one password login with
  remember-me, then `login_auto.php`, kept encrypted in the cache; a refused
  bot password waits 30 minutes before trying again.
- **Only the browser that started a claim can finish it** (the claim id is
  in its session), and only once.
- **Two claims for one name when its request arrives: both are refused.**
  There's no telling whose request it was. A name can be claimed at most 4
  times an hour, and starting claims is in the `login` rate tier.
- **A friend request proves control, not level.** Such an account gets no
  tokens (Wear asks for the password once) and can't vote until it logs in
  once with its password (`BonkAccountLink.password_proven_at`; every link
  from before this ADR was made by password).

**Alternatives considered.**
- *A room bot* (join a room, type a code): what LevelBot did. More to run,
  and a friend request already does the job.
- *A separate bot account for the site*: no overlap with BonxBot, but
  players would learn two names for a few weeks.
- *Friend request only for adding accounts*: keeps passwords as the only
  sign-in, but the main reason to offer it is players who won't type one.

- **A bonk.io pause holds claims instead of expiring them** (added
  2026-11-24). A login pause stops every bonk.io call, the bot's request
  check included, so a claim could run out unchecked. Pending claims are
  kept until 5 minutes after the pause ends, the waiting page says when
  checking resumes (and to resend the request if it's gone: BonxBot deletes
  requests older than 11 minutes), and no new claim starts during a pause.

- **Only accounts no one has here yet** (security fix, 2026-11-25). A
  friend request carries only the sender's name, id and time, so it proves
  that *someone* waiting on a claim for that name received a request from
  it, not that the sender started the claim. Reported in Discord: a person
  waiting on a claim for your name could sign in as you when you friended
  the bot for any reason (BonxBot's `/link` uses the same bot). So a claim
  can't start for a name already on Bonkverse (a site account or an active
  link), and a proven claim is refused if the account is owned by then
  (`link_claims.already_on_site`). Owned accounts sign in with their
  password, or with one click on a browser they proved themselves on.
  This replaces "a friend-request sign-in to the main unlocks the group".
- **The password takes it back** (`sign_in._reclaim`). When an account only
  ever proven by friend request signs in with its password, on a browser
  where its group's main isn't signed in and that the group doesn't trust,
  it leaves its group, its one-click sign-ins end, and every other session
  holding it ends (`tasks.end_other_sessions`, on the worker). A new
  account claimed first by someone else therefore goes back to its owner.
- Phase 7 sends BonxBot's `/link` through the site's claims, so a `/link`
  and another claim for the same name meet the "two pending claims for one
  name are both refused" rule instead of feeding each other.

**Consequences.**
- Anyone who can send a friend request from an account can sign in as it,
  the same trust bonk.io itself gives that session. Someone signed in to a
  player's bonk.io on a shared computer could do this; the password route
  has the same exposure.
- The bot account's password is now on the site (`BONK_BOT_PASSWORD`),
  as it is on BonxBot. Its remember-me token is encrypted under
  `BONK_TOKEN_KEYS`.

**Removed 2026-11-27.** Friend-request sign-in is gone from Bonkverse
(owner: "I'd rather not have people's accounts be in danger even if there's
a small chance of risk"). A friend request can't show who started the claim
it proves; room codes (ADR 0026) do the same job without that weakness.

- `/login/friend/…` addresses send people to room codes (keeping `add`, the
  name and `next`); an open waiting page is told friend requests are gone
  (`410`). Claims still waiting at deploy were refused (migration
  `accounts.0014`). Old rows stay as history.
- Accounts that came in by friend request are left as they are; voting
  still needs a password or room code. Their one-click sign-ins end (the
  same migration), so whoever got in that way doesn't keep a month of
  one-click access; the next sign-in needs a room code or the password.
  Chooser entries that last signed in by friend request open the room-code
  way.
- Accepted: during the deploy, an old web process could still start a
  friend claim; it can't be finished by the new code and stays inert.
- Removed: `link_claims` matching and the worker's `check-link-claims`,
  `bot_account.py`, `BonkClient.delete_friend_request`, the
  `BONK_BOT_USERNAME` / `BONK_BOT_PASSWORD` settings. BonxBot still uses the
  same bot account for its own `/link` until phase 7.
