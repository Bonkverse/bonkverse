// Entry point: `node src/index.mjs`. See ../README.md.
import { createRequire } from "node:module";
import { Rooms } from "./rooms.mjs";
import { createServer } from "./server.mjs";
import { PROTOCOL_VERSION } from "./room.mjs";

const require = createRequire(import.meta.url);
const io = require("socket.io-client"); // v2: bonk.io's room servers speak socket.io v2

const token = process.env.ROOMBOT_TOKEN || "";
if (token.length < 32) {
  console.error("ROOMBOT_TOKEN must be set (32+ characters); refusing to start");
  process.exit(1);
}
const port = Number(process.env.PORT || 8080);
const LOCATION_TTL_MS = 10 * 60_000;

// Which server to create rooms on, as bonk.io's client asks for a guest
// (getrooms.php with gl=y returns createserver and the location it sends).
let located = null;
async function locate() {
  if (located && Date.now() - located.at < LOCATION_TTL_MS) return located.value;
  const reply = await fetch("https://bonk2.io/scripts/getrooms.php", {
    method: "POST",
    body: new URLSearchParams({ version: String(PROTOCOL_VERSION), gl: "y", token: "" }),
    signal: AbortSignal.timeout(10_000),
  }).then((r) => r.json());
  const value = {
    server: /^[a-z0-9]+$/.test(reply.createserver || "") ? reply.createserver : "b2ny1",
    lat: Number(reply.lat) || 0,
    long: Number(reply.long) || 0,
    country: typeof reply.country === "string" ? reply.country.slice(0, 2) : "US",
  };
  located = { at: Date.now(), value };
  return value;
}

// TLS verification stays on: the Dockerfile sets NODE_EXTRA_CA_CERTS to the
// Sectigo intermediate bonk.io's servers leave out of their chain.
const connect = (url) => io(url, { transports: ["websocket"], reconnection: false, timeout: 10_000 });

const rooms = new Rooms({ connect, locate, botName: process.env.ROOMBOT_NAME || "Bonkverse" });
const server = createServer({ rooms, token });
server.listen(port, () => console.log(`roombot listening on ${port}`));

for (const signal of ["SIGTERM", "SIGINT"]) {
  process.on(signal, () => {
    rooms.closeAll("shutdown");
    server.close();
    setTimeout(() => process.exit(0), 2000);
  });
}
