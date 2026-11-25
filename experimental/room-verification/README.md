# Room-code verification: prototype

**Experimental, not deployed.** A single script that proves the idea in
[ADR 0026](../../docs/adr/0026-room-code-sign-in.md), using the protocol in
[docs/bonk/rooms.md](../../docs/bonk/rooms.md). It passed a live test on
2026-11-25 (results in rooms.md).

## What it does

1. **Opens a room:** asks `getrooms.php` which server to use, then creates one
   **hidden, password-protected, 2-player** room as a guest. It uses no P2P and
   keeps TLS verification on.
2. **Shows the details:** prints the share link, the password and a random
   6-character code, and sends a desktop notification if `notify-send` exists.
3. **Answers joiners** with the empty-map initial data (event 11). Without
   this, joiners get bonk.io's *"Initial data timeout"* (the "ghost room").
4. **Checks the code** typed in chat. Guests are refused, and the joiner gets 3
   tries.
5. **Closes the room** on success, after too many wrong codes, or after 10
   minutes.

## Running it

bonk.io's room servers send an incomplete TLS chain. Don't turn verification
off; add the missing intermediate instead:

```bash
curl -sS -o sectigo-dv-r36.der http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt
openssl x509 -inform DER -in sectigo-dv-r36.der -out sectigo-dv-r36.pem
# SHA-256 fingerprint should be 8C:54:C3:34:B6:6B:A4:E4:26:77:2A:F4:A3:F9:13:6C:19:A1:AE:C7:29:FD:B2:8C:53:5C:07:A5:A4:EF:22:E0
openssl x509 -in sectigo-dv-r36.pem -noout -fingerprint -sha256

npm install
NODE_EXTRA_CA_CERTS=sectigo-dv-r36.pem node roomtest.mjs
```

Then join the printed link **signed in to a bonk.io account** and type the
code in chat. The run's events are written to `result.json`.

## What a real service still needs (ADR 0026)

- **An API:** Bonkverse asks for a room for a claim and gets the link back,
  rather than a script. The code is made and checked by Bonkverse; the service
  only reports what was typed, by whom.
- **A shared secret** between Bonkverse and the service, and a private network.
- **Limits:** a cap on rooms at once, and kicking any extra or unexpected
  player.
- **Robustness:** handling the server dropping the connection or rejecting
  `version: 49` when bonk.io updates.
