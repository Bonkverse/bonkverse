// Prototype / live test of room-code verification (docs/bonk/rooms.md,
// docs/adr/0026-room-code-sign-in.md). Not production code: see README.md.
// One hidden, password-protected, 2-player room as a guest; answers joins with
// the empty-map initial data; checks a code typed in chat. TLS verification is
// ON (the missing Sectigo intermediate comes from NODE_EXTRA_CA_CERTS).
import { createRequire } from "node:module";
import { execFile } from "node:child_process";
import { randomInt, randomBytes } from "node:crypto";
import fs from "node:fs";
const require = createRequire(import.meta.url);
const io = require("socket.io-client");

const LIFETIME_MS = 10 * 60_000;
const MAX_TRIES = 3;
const t0 = Date.now();
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1).padStart(6)}s]`, ...a);
const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
// Desktop notifications if notify-send exists (Linux); harmless otherwise.
const notify = (title, body, urgency = "normal") =>
  execFile("notify-send", ["-a", "Bonkverse test", "-u", urgency, title, esc(body)], () => {});

const ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"; // no 0/O, 1/I/L
const code = Array.from({ length: 6 }, () => ALPHABET[randomInt(ALPHABET.length)]).join("");
const password = randomBytes(6).toString("base64url");
// Which server to create on, and the location the client would send: one
// request to getrooms.php, as the game does for a guest (gl=y asks for location).
const loc = await fetch("https://bonk2.io/scripts/getrooms.php", {
  method: "POST",
  body: new URLSearchParams({ version: "49", gl: "y", token: "" }),
})
  .then((r) => r.json())
  .catch(() => ({}));
const server = loc.createserver || "b2ny1";

const EMPTY_MAP = {
  v: 13,
  s: { re: false, nc: false, pq: 1, gd: 25, fl: false },
  physics: { shapes: [], fixtures: [], bodies: [], bro: [], joints: [], ppm: 12 },
  spawns: [],
  capZones: [],
  m: { a: "Bonkverse", n: "Verification", dbv: 2, dbid: -1, authid: -1, date: "", rxid: 0, rxn: "", rxa: "", rxdb: 1, cr: [], pub: false, mo: "" },
};
const gs = { map: EMPTY_MAP, gt: 2, wl: 3, q: false, tl: false, tea: false, ga: "b", mo: "b", bal: [] };

const result = { server, code, events: [], joined: null, verified: false, notes: [] };
const players = new Map();
let tries = 0;
let closing = false;

log(`connecting to https://${server}.bonk.io (TLS verification on)`);
const socket = io(`https://${server}.bonk.io`, { transports: ["websocket"], reconnection: false });

// Record every message the server sends (for the research doc).
const onevent = socket.onevent;
socket.onevent = function (packet) {
  const [name, ...args] = packet.data;
  const summary = JSON.stringify(args).slice(0, 220);
  result.events.push({ t: Date.now() - t0, name, summary });
  log(`<- ${name}`, summary);
  onevent.call(this, packet);
};

function send(n, payload) {
  log(`-> ${n}`, JSON.stringify(payload ?? null).slice(0, 220));
  payload === undefined ? socket.emit(n) : socket.emit(n, payload);
}
function chat(message) {
  send(10, { message });
}
function finish(why) {
  if (closing) return;
  closing = true;
  log("closing:", why);
  result.notes.push(`closed: ${why}`);
  setTimeout(() => {
    socket.close();
    fs.writeFileSync("result.json", JSON.stringify(result, null, 2));
    log("done; room closed by disconnecting");
    setTimeout(() => process.exit(0), 500);
  }, 2500);
}

socket.on("connect", () => {
  log("connected");
  send(12, {
    peerID: "", // no P2P (the client's "np" mode)
    roomName: "Bonkverse verification test",
    maxPlayers: 2,
    password,
    dbid: 0, // what the client sends for a guest
    guest: true,
    guestName: "BVerifyTest",
    minLevel: 0,
    maxLevel: 999,
    latitude: loc.lat ?? 0,
    longitude: loc.long ?? 0,
    country: loc.country || "US",
    version: 49,
    hidden: 1,
    quick: false,
    mode: "custom",
    avatar: { layers: [], bc: 4492543 },
  });
});
socket.on("connect_error", (e) => {
  log("connect_error", e?.message);
  notify("Bonkverse test: can't connect", String(e?.message), "critical");
  result.notes.push(`connect_error: ${e?.message}`);
  finish("connect error");
});
socket.on("disconnect", (r) => log("disconnected:", r));

socket.on(1, (_pings, id) => send(1, { id })); // ping: answer like the client
socket.on(2, () => log("room created"));
socket.on(49, (autoJoinID, bypass) => {
  const link = `https://bonk.io/${autoJoinID}${bypass}`;
  result.link = link;
  log(`SHARE LINK: ${link}  password: ${password}  code: ${code}`);
  notify(
    "Bonkverse test room is open",
    `Join (signed in, not as guest): ${link}\nIf asked, password: ${password}\nThen type in chat: ${code}`,
    "critical"
  );
});
socket.on(4, (id, peerID, username, guest, level, team) => {
  players.set(id, { username, guest, level });
  result.joined = { id, username, guest, level, team, peerID: peerID ? "(set)" : "" };
  log(`player ${id} joined: ${JSON.stringify(result.joined)}`);
  send(11, { sid: id, gs }); // initial data: without this the joiner times out after 6 s
  notify("Someone joined the test room", `${username} (${guest ? "GUEST" : "account"}, level ${level})`);
  setTimeout(() => chat(`Hi ${username}! Type the verification code to finish (test).`), 1500);
});
socket.on(5, (id) => {
  log(`player ${id} left`);
  if (!result.verified) notify("Test room", `${players.get(id)?.username ?? id} left before verifying`);
});
socket.on(20, (id, message) => {
  const p = players.get(id);
  if (!p) return; // the bot's own messages
  const typed = String(message).trim().toUpperCase();
  if (p.guest) {
    chat("Guests can't verify: sign in to your bonk.io account and join again.");
    notify("Test room", `Refused: ${p.username} is a guest`);
    result.notes.push(`refused guest ${p.username}`);
    return;
  }
  if (typed === code) {
    result.verified = { username: p.username, level: p.level };
    chat(`Verified as ${p.username} (test). Closing the room.`);
    notify("Verified!", `${p.username} typed the right code. Closing the room.`, "critical");
    finish("verified");
  } else if (++tries >= MAX_TRIES) {
    chat("Too many wrong codes. Closing.");
    notify("Test room", "Too many wrong codes; closing", "critical");
    finish("too many wrong codes");
  } else {
    chat(`That's not the code (${MAX_TRIES - tries} tries left).`);
  }
});

setTimeout(() => {
  notify("Test room", "10 minutes passed; closing the room");
  finish("timeout");
}, LIFETIME_MS);
