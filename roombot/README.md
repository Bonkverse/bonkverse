# roombot: room-code sign-in service (experimental)

Hosts bonk.io rooms for room-code sign-in
([ADR 0026](../docs/adr/0026-room-code-sign-in.md); protocol in
[docs/bonk/rooms.md](../docs/bonk/rooms.md)). Bonkverse asks for a room for a
name. A person joins it signed in to that bonk.io account and types the code
Bonkverse showed them. Bonkverse reads what was typed and decides.

**Experimental:** it relies on bonk.io's undocumented room protocol (version
49), which can change.

## API

Every route except `/health` requires `Authorization: Bearer $ROOMBOT_TOKEN`.

| Route | Answer |
|---|---|
| `POST /rooms` `{"name": "ButDoge"}` | `201 {id, link, expires_in}`, `429 {retry_after}` when busy, `502` if bonk.io can't be reached |
| `GET /rooms/:id` | `{id, state, closed_reason, link, expected_name, players[], messages[]}` |
| `POST /rooms/:id/close` `{"message": "..."}` | says the message in the room, then closes it |
| `POST /rooms/:id/say` `{"message": "..."}` | says the message in the open room (Bonkverse answers each wrong code this way); `409` if the room isn't open |
| `GET /health` | `{ok, open}` |

## What a room does

- **Creates the room:** hidden, 2 players (the bot and the person), password
  set (the share link skips it), created as a guest with no P2P.
- **Sends No Host Swap (50)**, so the room ends when the bot leaves. Without
  it, bonk.io would hand host to the person and the room would stay open.
- **Answers every join with the initial data (11)**, an empty map.
  Without it, joiners get "Initial data timeout" (a "ghost room").
- **Kicks anyone it can't verify,** after explaining why, so the right player
  can join: a guest (who can use any name), or someone with another name.
  Kick is `9 {banshortid, kickonly: true}`, which isn't tested live yet.
- **Records what players type** (at most 20 messages, 40 characters each).
  Codes are checked by Bonkverse, never here.
- **Answers bonk.io's pings,** and closes after 10 minutes, or when Bonkverse
  closes it.

## Limits

bonk.io lets one IP host about **5 rooms per 5 minutes**, so the service opens
at most 5 per 5 minutes and answers `429` with `Retry-After` past that. Rooms
last at most 10 minutes, so no more than 5 are open at a time.

## TLS

bonk.io's room servers leave the intermediate certificate out of their chain.
Verification stays **on**: the Dockerfile trusts the missing intermediate
(`certs/`, Sectigo Public Server Authentication CA DV R36, SHA-256
`8C:54:C3:34:…:EF:22:E0`) through `NODE_EXTRA_CA_CERTS`.

## Running

```bash
npm install
npm test                                  # no network: a fake bonk.io socket
ROOMBOT_TOKEN=$(openssl rand -hex 32) \
NODE_EXTRA_CA_CERTS=certs/sectigo-public-server-authentication-ca-dv-r36.pem \
npm start                                 # listens on $PORT (8080)
```

**Deploying:** see "Room-code sign-in service" in
[docs/operations/configuration.md](../docs/operations/configuration.md).
In short:
- **The service:** a new Railway service with root directory `roombot`,
  builder Dockerfile, healthcheck `/health`, restart on failure, one replica,
  and **no public domain**, all set in its Settings (new services can't use a
  `railway.json`; see ADR 0027).
- **On roombot:** set `ROOMBOT_TOKEN` (`openssl rand -hex 32`) and `PORT=8080`.
- **On the web service:** set `ROOMBOT_URL=http://${{roombot.RAILWAY_PRIVATE_DOMAIN}}:8080`
  and `ROOMBOT_TOKEN=${{roombot.ROOMBOT_TOKEN}}`.

Room-code sign-in stays hidden on the site until `ROOMBOT_URL` is set.
