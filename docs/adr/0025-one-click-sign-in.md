# ADR 0025: One-click sign-in from "Choose an account"

**Status:** accepted, 2026-11-24 (RFC-0003, after phase 6)

**Context.** A Bonkverse sign-in lasts 90 days and needs no bonk.io while it
lasts (ADR 0022, 0023). But after signing out, getting back in meant a bonk.io
password or a friend request: Bonkverse had no proof of its own. The login
page's "Choose an account" (`known_accounts.py`) only filled in the name, so a
player who signs out and back in still spent a bonk.io login each time. The
owner wanted it to work like Google's or Discord's account chooser: click the
account, you're in. RFC-0003 left Bonkverse's own sign-in methods (passkeys,
Discord) out of scope; this is the first, for browsers already used.

**Decision.**
- **A proven sign-in remembers the browser for that account.** Each password
  or friend-request sign-in writes a `RememberedSignIn` (account, hash of the
  browser's `bv_device` cookie, rough browser name, `proven_at`). Only the
  hash is stored, as for trusted browsers.
- **One click for `ONE_CLICK_SIGN_IN_DAYS` (30) after the last proof.** In
  that window the chooser's account is a button (`POST /login/choose/`) that
  signs it in with no bonk.io call. A one-click sign-in does not extend the
  window: after 30 days the account opens the way it last signed in, and the
  proof starts a new window. The owner chose "straight in, but ask after a
  while" over always asking (Google) and never asking (Discord).
- **Same as any other sign-in otherwise.** A main signed in this way unlocks
  its group here (`groups.after_login`); this browser already holds the
  group's 90-day trust from the main's last proof.
- **Ending it.** The chooser's Remove ends it for that account on this
  browser; "Also forget this device" ends it for every account here;
  Settings → "One-click sign-in" lists the account's browsers with Remove,
  so a browser left behind can be ended from elsewhere.

- **The same proof adds accounts to a group** (`used_here.py`). Signed in,
  a person sees "Used on this browser": accounts proven here within the
  window and in no group. They tick the ones that are theirs, confirm
  "These accounts are mine", and the accounts join their group with no
  password and no bonk.io call. It's offered on "Add a bonk.io account", in
  Settings, and once on the first page after a sign-in (a banner linking to
  the add page). Accounts already in a group are never offered: moving one
  needs a fresh password or friend request, so a friend who once signed in
  on your computer can't be pulled out of their group. The owner chose this
  over re-proving each account (2026-11-24).

**Consequences.**
- Signing out and back in costs bonk.io nothing for 30 days, so password
  logins fall to new browsers, a monthly proof, and Wear without remember-me.
- Anyone at the computer can click back in during the window, like the
  90-day session the sign-out ended. "Also forget this device" is the shared
  computer's answer, and the chooser says so.
- A stolen `bv_device` cookie signs in for the rest of the window, like a
  stolen session cookie; both are HttpOnly.
- Joining a group is lasting (one vote per skin, switching), unlike a
  30-day one-click; the explicit tick and confirm are the guard, and an
  account added by mistake is removed in Settings.
- Next: passkeys, so a new device can sign in without bonk.io too.
