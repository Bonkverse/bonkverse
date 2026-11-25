# bonk.io rooms: how creating, joining and chatting work

Research for signing in with a code typed in a bot-hosted room
([ADR 0026](../adr/0026-room-code-sign-in.md)). **Experimental:** read from
bonk.io's client and two community bots, then checked with one live test room
on 2026-11-25 ([results](#live-test-2026-11-25)). Each item says where it
comes from.

Sources:

- **DemystifyBonk**: [UnmatchedBracket/DemystifyBonk](https://github.com/UnmatchedBracket/DemystifyBonk)
  (`Packets.md`, Unlicense), a documented list of bonk.io's packets.

- **client**: bonk.io's game code, as built into Bonkverse/ReplayRenderer
  (`vendor/bonk-core.mjs`, generated from `alpha2s.js`, protocol version 49).
  Line numbers below are in that file.
- **PixelMelt**: [PixelMelt/BonkBot](https://github.com/PixelMelt/BonkBot)
  (`src/bot.js`, `src/utils/constants.js`), a working bot library that hosts
  rooms.
- **WolfRichie**: [WolfRichie/Bonk-Bot](https://github.com/WolfRichie/Bonk-Bot)
  (C#, `BonkClient/Protocol/...`).

Neither community repo has a license: they are used to confirm how the
protocol works, and no code is copied from them.

## Servers and transport

- **Room servers** are `https://<server>.bonk.io/` (`multiplayer.gg` off
  bonk.io), e.g. `b2ny1`. client line 9452.
- **Which server:**
  - To **create** a room, the client uses `createserver` from
    `POST https://bonk2.io/scripts/getrooms.php` `{version, gl, token}`, and
    falls back to `river1`. client 2533, 2565, 22031.
  - To **join**, it calls `POST https://bonk2.io/scripts/getroomaddress.php`
    `{id}` and gets `{r: "success", id, address, server}`. client 13680.
- **socket.io v2 (Engine.IO 3).** PixelMelt uses `socket.io-client@^2.4.0`
  over websocket, path `/socket.io`. Current socket.io clients (v3+) can't talk
  to it. In Python only the old `python-socketio` 4.x speaks this protocol.
- **TLS:** bonk.io's servers send an incomplete Sectigo chain (PixelMelt's
  `scripts/download-cert.js`). PixelMelt then turns certificate checking off.
  **We must not do that.** Supply the missing intermediate
  (`SectigoPublicServerAuthenticationCADVR36`) as an extra CA instead.
- **No peer-to-peer:** the client normally also opens PeerJS (WebRTC)
  connections between players, but has a no-P2P mode (`NetworkEngine.np`) in
  which `peerID` is sent as `""` (client 10040). A bot that only chats needs
  no P2P.

## Messages

Messages are socket.io events with **numeric names**. Client to server
(`connection.emit(n, payload)`) and server to client (`connection.on(n, ...)`)
use separate numbering. PixelMelt's `constants.js` names agree with the
client.

### Creating a room: client → 12, server → 2 and 49

`emit(12, {...})` (client `createRoom`, 9997):

```text
peerID, roomName, maxPlayers, password, dbid, guest, minLevel, maxLevel,
latitude, longitude, country, version (49), hidden, quick (false), mode ("custom"),
guestName (if guest) | token (if signed in), avatar
```

- **Server 2** (`createdRoom`) confirms the room was created.
- **Server 49** (`ROOM_SHARE_LINK`) sends `(autoJoinID, bypass)`. The share
  link is `https://bonk.io/<autoJoinID><bypass>` (PixelMelt `getShareLink`).
  The bypass lets someone with the link skip the room password: the client
  stores it as `autoJoinPassBypass` (client 9520), and in the live test the
  joiner wasn't asked for one.

### Someone joins: server → 4, then the host must answer 11

**This is the "ghost room" problem.** A joiner gets the room's state **from
the host, not from the server**:

1. The joiner sends `emit(13, {joinID, roomPassword, guest, dbid, version,
   peerID, bypass, guestName|token, avatar})` (client 10054).
2. The server sends the joiner **3** (`joinedRoom`: their id, the host id,
   the player list…). The client then shows *"Joined room, awaiting first
   data"* and starts a **6-second timer** (client 9520).
3. The server sends the host **4** (`newPlayerJoined`):
   `(id, peerID, username, guest, level, team, avatar)` (client 9524, 1917).
4. **The host must send `emit(11, {sid: <joiner id>, gs: <game settings>})`**
   (`informInLobby`, client 9815, 759), or `emit(40, {sid, allData})` during
   a game.
5. The server passes it to the joiner as **21** (`recvInLobby`), which clears
   the timer (client 9608).

If step 4 never happens, the joiner sees *"Initial data timeout."* after 6 s
(client 9900): that's the ghost room. A bot host has to answer every 4 with an
11.

### What `gs` must contain

The default settings object (client `class Game`, 6236):

```js
{ map, gt: 2, wl: 3, q: false, tl: false, tea: false, ga: "b", mo: "b", bal: [] }
```

- **`map` can't be `null`:** the joiner's lobby draws it. The real client
  picks one of its built-in maps (`Maps.getOrderedRandomMap(0, "community")`,
  client 1890).
- **A minimal empty map works for a bot:** PixelMelt's host answers with this
  one, and WolfRichie's default lobby state has the same shape.

```js
{ v: 13, s: { re: false, nc: false, pq: 1, gd: 25, fl: false },
  physics: { shapes: [], fixtures: [], bodies: [], bro: [], joints: [], ppm: 12 },
  spawns: [], capZones: [],
  m: { a: "<author>", n: "<map name>", dbv: 2, dbid: -1, authid: -1, date: "",
       rxid: 0, rxn: "", rxa: "", rxdb: 1, cr: [], pub: false, mo: "" } }
```

- **`m.dbid`:** PixelMelt uses a real map id there. Whether `-1` is accepted
  is **unverified**.

### Chat: client → 10, server → 20

- **Sending:** `emit(10, {message})` (client 9810).
- **Receiving:** **20** `(playerId, message)` (client 9605). The host sees
  everyone's messages, so the bot reads the code from here.

### Who is the joiner? (what to trust)

- **Name and guest flag:** the username and `guest` flag in **4** come from
  bonk.io's server. For a signed-in player, the server checked their token
  (`token` in 13), so **a non-guest username in 4 is the real account**.
- **Guests aren't accounts:** they send `guestName` and can call themselves
  anything, including someone else's name. **Verification must refuse
  `guest: true`.**
- **Level:** `level` in 4 is also reported by the server.

### Other events a host may need

| Direction | Number | Meaning (client / PixelMelt name) |
|---|---|---|
| server → | 1 | ping data; answer `emit(1, {id})` (client 9484) |
| server → | 5 | player left `(id, …)` |
| server → | 6 | host left |
| client → | 9 | kick/ban `{banshortid, kickonly}`: `kickonly: true` lets them rejoin (DemystifyBonk; not tested live) |
| client → | 50 | **No Host Swap**: when the host leaves, the room ends instead of passing host (DemystifyBonk, client `sendNoHostSwap`) |
| client → | 18 | timesync request (with an acknowledgement callback) |
| client → | 52 / 53 | change room name / password |

**Unverified:** whether a host must answer pings or time sync to stay
connected, and how long an idle room lives.

## Live test (2026-11-25)

**Setup:**
- **Server:** `b2brazil1`, from `getrooms.php`.
- **Room:** created as a guest (`guestName`, `dbid: 0`, `peerID: ""`): hidden, 2 players, with a password.
- **Initial data:** the bot answered the joiner with the empty-map `gs` above.
- **Joiner:** a signed-in account joined from the share link and typed a 6-character code in chat.
- **TLS:** certificate checking on.

**Message timeline:**

```text
  0.1s  -> 12 create room (guest, peerID "", hidden 1, version 49)
  0.8s  <- 2  ["<socket id>", 1, null]          room created
  1.0s  <- 49 [816187, "dbais"]                 share link https://bonk.io/816187dbais
  1.5s  <- 1  [{}, 3]   -> 1 {id: 3}            server pings every 3 s; the bot answers each
 15.3s  <- 4  [1, "<peer id>", "ButDoge", false, 52, 1, {layers, bc}]
 15.3s  -> 11 {sid: 1, gs: {map: <empty map>, ...}}
 16.8s  -> 10 {message: "Hi ButDoge! ..."}  <- 20 [0, "Hi ButDoge! ..."]  (own message echoed)
 22.6s  <- 20 [1, "W8NMFD "]                    the joiner's code (note the trailing space)
 25.2s  disconnect                              room closed
```

| Question | Result |
|---|---|
| A guest can create a room without P2P | **Yes** (`peerID: ""`, `dbid: 0`) |
| The empty-map `gs` in 11 avoids the ghost room | **Yes**: the joiner reached the lobby and chatted |
| Event 4 reports the real account | **Yes**: username, `guest: false`, level from the server |
| Chat arrives as 20 `(playerId, message)` | **Yes**; the host also gets its own messages back (id 0); trim input |
| Keeping the connection alive | The server sends 1 `[pings, id]` every 3 s; answering `emit(1, {id})` kept it up |
| Closing the room | Disconnecting **without** No Host Swap hands host to the remaining player, so the room lives on (server 6 `[old host, new host, …]`; new host `-1` means closed). Send **50** after creating; then disconnecting ends it. |
| TLS with checking on | **Works** with the Sectigo intermediate added (`NODE_EXTRA_CA_CERTS`) |

**Still open:**
- Does the share link's bypass skip the password prompt? Ask the tester.
- What happens if the host *doesn't* answer pings (how long until the server drops it)?
- How many rooms one IP can host: about **5 per 5 minutes** (reported by a
  bonk.io player). Rooms close after 10 minutes, so that's also ~5 at once.
- Hidden rooms aren't in `getrooms.php`, so "the room is gone" can only be checked by trying the link after closing.
