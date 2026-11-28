# ADR 0026: Sign in with a code typed in a bot-hosted room

**Status:** Proposed, experimental.
- **Research:** protocol in [docs/bonk/rooms.md](../bonk/rooms.md).
- **Live test:** a one-file prototype passed on 2026-11-25. A signed-in
  player joined the bot's room, the server reported the real account, and
  the code typed in chat verified it. That prototype became
  [roombot/](../../roombot/).
- **Built, behind settings:** the room service ([roombot/](../../roombot/))
  and the Bonkverse side (`accounts/room_claims.py`,
  `integrations/roombot.py`, `/login/room/`). It stays hidden until
  `ROOMBOT_URL` and `ROOMBOT_TOKEN` are set, and is labelled
  **Experimental** on the site.

## Context

Friend-request sign-in ([ADR 0024](0024-friend-request-sign-in.md)) proves a
claim with *any* friend request from the claimed name to the bot. The request
says nothing about which claim it is for:

- **Accidental takeover:** someone who starts a claim for another player's
  name is signed in as them as soon as that player friend-requests the bot
  for any reason. BonxBot's `/link` uses the same bot account.
- **Easy social engineering:** "add this account for a giveaway" is enough.

The warning on the sign-in pages (PR #190) only makes this harder.

## Decision (proposed)

Prove a claim with a **one-time code typed in a room the bot hosts**:

1. The person types their bonk.io name on Bonkverse. The server creates a
   claim with a random **code**. The code is shown only in that browser,
   valid for 10 minutes and single-use.
2. A room service connects to bonk.io **as a guest** and creates a **hidden,
   password-protected, 2-player** room. It hands Bonkverse the share link
   (`https://bonk.io/<id><bypass>`), which the page shows.
3. The person joins from the link, signed in as that account, and types the
   code in chat.
4. The room service checks what bonk.io's server says about the joiner (event
   4): **`guest` must be false** and the name must match the claim. It then
   reads their chat (event 20), compares the code, closes the room, and tells
   Bonkverse which account proved which claim.
5. The browser that started the claim is signed in, as today.

Why this fixes ADR 0024's problem:

- **The proof names the claim:** the code exists only in the claimer's
  browser. A friend request, or a room joined for another reason, can't prove
  anything.
- **Identity comes from bonk.io's server:** the username in event 4 is
  bonk.io's own check of the joiner's login token. Guests are refused, because
  a guest can use any name.
- **Social engineering:** "join my room and type 4F9K-2Q" is still possible,
  but it's an explicit, unusual request, and the room and page can say what
  the code is for.

### Rules

- **The code:**
  - at least 6 characters, from `secrets`;
  - compared in constant time;
  - tied to one claim, one name and one browser;
  - expires with the claim, and is only good once.
- **The room:**
  - hidden, with a password and 2 slots: the bot plus the joiner;
  - anyone else who gets in (or a second player) is kicked;
  - the room closes on success, on a wrong code (allow a few tries), or after
    10 minutes.
- **Limits:** a cap on concurrent rooms, plus the existing per-name and
  per-browser claim limits.
- **No guests:** a joiner with `guest: true` never proves anything, whatever
  name they show.
- **TLS:** certificate checking stays **on**. Supply the Sectigo intermediate
  bonk.io's servers leave out ([rooms.md](../bonk/rooms.md#servers-and-transport)).

### Where the room service runs

bonk.io's room servers speak **socket.io v2** (Engine.IO 3):

- **Node:** `socket.io-client@2` supports it and is what the working community
  bot uses.
- **Python:** only `python-socketio` 4.x, which is unmaintained.

**Proposed:** a small Node service, private to Railway's network, with a
shared bearer token. Bonkverse calls it to open a room for a claim, and it
calls Bonkverse back (or Bonkverse polls) with the result. The Django side
keeps the claims, codes and sign-in, as in ADR 0024.

## Consequences

- **A new service** to deploy and watch, holding a guest connection to
  bonk.io per active sign-in.
- **Depends on undocumented behaviour:** bonk.io's room protocol (version 49,
  the host answering joiners with event 11) could change; the friend request
  stays as a fallback until the room flow has proven itself.
- **Separate from BonxBot:** BonxBot's `/link` could adopt the same flow later.

## Open questions

- **Remaining live checks:** the items still open in
  [rooms.md](../bonk/rooms.md#live-test-2026-11-25): password bypass from the
  share link, what happens without pings, and rooms per IP.
- **Replace or keep:** does friend-request sign-in stay as a fallback, or go
  away once rooms work?

**Added 2026-11-27.** Each wrong code is answered at once, in the room
("That's not the code. 2 tries left.", through roombot's `POST /rooms/:id/say`)
and on the waiting page; before, nothing was said until the third wrong code
ended the claim.

**Added 2026-11-27: accounts already on Bonkverse.** A room code now works
for any account, not only names no one has here yet (owner decision). It
signs in, lets the account vote with the level the room showed, and takes
back an account only a friend request had claimed. It still gives no tokens
(Wear asks for the password once).

**A code can be relayed.** It proves that the named account typed it, not
that the browser that asked belongs to that person: someone can start a
claim for your name and talk you into typing their code ("type this to
enter the giveaway"). A password can be phished too, but a code looks
harmless. So (owner, 2026-11-27, after butdoge's reviewer bot on #197):

- **On an account that has used its password, a code opens only that
  account.** It doesn't unlock the group or trust the browser, even on the
  main (`groups.after_login(unlock=False)`), and it can't add the account to
  a group (`NeedsPassword`, refused before a room opens and again at the
  finish). It's marked code-only on that browser (`groups.CODE_ONLY_KEY`):
  it doesn't count as "the main signed in here" (removing accounts, "apply
  to all", trusted browsers, changing the main), it can't take other
  accounts into its group, and it leaves no one-click sign-in. A password
  proof counts even on a disconnected link. Accounts that never used a
  password keep the full powers: there's no stronger proof to protect.
- **The proof is kept apart** (`BonkAccountLink.room_proven_at`,
  `room_level`). **A password beats a room code newer than its last
  password**, compared across all the account's links (`sign_in._reclaim`):
  its one-click sign-ins and other sessions end, unless the browser is its
  group's own; an account that never used its password also leaves the group
  it's in (a code may have moved it). A room code takes an account back only
  from a friend request.
- The room greets the player with a warning ("Type the code on YOUR
  Bonkverse screen. Never type a code someone sent you."), as the waiting
  page already does.
- The room's level is stored on the link, not written into the player's XP
  (other pages show XP). No known level and no password proof: no vote yet.
- Staff, superuser and password-holding site accounts can't use room codes
  at all, linked or not: a room proves only the name, and a name can change
  hands on bonk.io (#198 refuses unlinked ones for every way in). A room
  isn't even opened for such a name.

Accepted with it (owner's choice that a code signs in):

- A code-only session is still a session for that one account: it can
  favorite, vote, upload and change that account's own settings until the
  owner's next password sign-in ends it. It gets no tokens (no Wear), no
  group powers, and no one-click comeback.
- A room proves the name, not the bonk.io id. This relies on bonk.io names
  never changing hands (bonk.io has no rename, and names are unique ignoring
  case). If that ever changes, room codes must refuse accounts whose linked
  row has a known id.

Also left as is: claims for any name count toward that name's hourly limit, so
someone can use up a name's room-code tries for an hour; its password still
works. A legitimate owner who used a room code and then signs in with the
password on a browser their group doesn't trust has their other sessions
ended. Friend-request sign-in is to be removed next (ADR 0024).
