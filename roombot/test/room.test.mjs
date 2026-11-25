import { test, mock } from "node:test";
import assert from "node:assert/strict";
import { BonkRoom, OUT, nameKey } from "../src/room.mjs";
import { Rooms, RoomLimitError } from "../src/rooms.mjs";
import { fakeConnect, createdRoom } from "./fake-socket.mjs";

const location = { server: "b2brazil1", lat: 1, long: 2, country: "BR" };

async function openRoom(expectedName = "ButDoge") {
  const { connect, sockets } = fakeConnect();
  const room = new BonkRoom({ connect, location, expectedName, lifetimeMs: 600_000 });
  const opening = room.open();
  const socket = sockets[0];
  await createdRoom(socket);
  const link = await opening;
  return { room, socket, link };
}

test("creates a hidden 2-player guest room without P2P, on the server bonk.io named", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { socket, link } = await openRoom();
    assert.equal(socket.url, "https://b2brazil1.bonk.io");
    const [create] = socket.sentOf(OUT.CREATE);
    assert.equal(create.guest, true);
    assert.equal(create.peerID, "");
    assert.equal(create.dbid, 0);
    assert.equal(create.hidden, 1);
    assert.equal(create.maxPlayers, 2);
    assert.equal(create.version, 49);
    assert.ok(create.password.length >= 8);
    assert.equal(link, "https://bonk.io/816187dbais");
  } finally {
    mock.timers.reset();
  }
});

test("asks for no host swap, so leaving ends the room instead of handing it over", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { socket } = await openRoom();
    assert.deepEqual(socket.sentOf(OUT.NO_HOST_SWAP), [undefined]);
  } finally {
    mock.timers.reset();
  }
});

test("answers pings like bonk.io's client", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { socket } = await openRoom();
    socket.receive(1, { 0: 12 }, 4);
    assert.deepEqual(socket.sentOf(OUT.PING_REPLY), [{ id: 4 }]);
  } finally {
    mock.timers.reset();
  }
});

test("sends the joiner the initial data at once (no ghost room) and greets them", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { room, socket } = await openRoom();
    socket.receive(4, 1, "peer", "ButDoge", false, 52, 1, {});
    const [initial] = socket.sentOf(OUT.INITIAL_DATA);
    assert.equal(initial.sid, 1);
    assert.equal(initial.gs.map.v, 13);
    assert.deepEqual(initial.gs.map.physics.bodies, []);
    mock.timers.tick(3000);
    assert.match(socket.sentOf(OUT.CHAT)[0].message, /Hi ButDoge! Type the code/);
    assert.deepEqual(socket.sentOf(OUT.KICK), []);
    assert.deepEqual(room.view().players, [{ username: "ButDoge", guest: false, level: 52 }]);
  } finally {
    mock.timers.reset();
  }
});

test("guests are told to sign in, and kicked", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { socket } = await openRoom();
    socket.receive(4, 1, "peer", "ButDoge", true, 0, 1, {}); // a guest can pick any name
    mock.timers.tick(3000);
    assert.match(socket.sentOf(OUT.CHAT)[0].message, /Guests can't sign in/);
    assert.deepEqual(socket.sentOf(OUT.KICK), [{ banshortid: 1, kickonly: true }]);
  } finally {
    mock.timers.reset();
  }
});

test("someone else is kicked so the right player can join", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { socket } = await openRoom("ButDoge");
    socket.receive(4, 1, "peer", "Someone", false, 10, 1, {});
    mock.timers.tick(3000);
    assert.match(socket.sentOf(OUT.CHAT)[0].message, /This room is for ButDoge/);
    assert.deepEqual(socket.sentOf(OUT.KICK), [{ banshortid: 1, kickonly: true }]);
  } finally {
    mock.timers.reset();
  }
});

test("names compare by ASCII case only (no casefold lookalikes)", () => {
  assert.equal(nameKey("ButDoge"), nameKey("BUTDOGE"));
  assert.notEqual(nameKey("Boſsman"), nameKey("Bossman"));
  assert.notEqual(nameKey("Boßman"), nameKey("Bossman"));
});

test("records players' messages trimmed, never the bot's own echo", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { room, socket } = await openRoom();
    socket.receive(4, 1, "peer", "ButDoge", false, 52, 1, {});
    socket.receive(20, 0, "Hi ButDoge! Type the code shown on Bonkverse.");
    socket.receive(20, 1, "W8NMFD ");
    const { messages } = room.view();
    assert.equal(messages.length, 1);
    assert.equal(messages[0].text, "W8NMFD");
    assert.equal(messages[0].username, "ButDoge");
    assert.equal(messages[0].guest, false);
  } finally {
    mock.timers.reset();
  }
});

test("closes after its lifetime, and can be closed with a goodbye", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { room, socket } = await openRoom();
    room.close("verified", "Done!");
    assert.deepEqual(socket.sentOf(OUT.CHAT).at(-1), { message: "Done!" });
    mock.timers.tick(2000);
    assert.equal(socket.closed, true);
    assert.equal(room.view().state, "closed");

    const other = await openRoom();
    mock.timers.tick(600_000);
    assert.equal(other.socket.closed, true);
    assert.equal(other.room.view().closed_reason, "expired");
  } finally {
    mock.timers.reset();
  }
});

test("at most 5 rooms per 5 minutes (bonk.io's per-IP limit)", async () => {
  let t = 0;
  const { connect, sockets } = fakeConnect();
  const rooms = new Rooms({ connect, locate: async () => location, now: () => t });
  try {
    for (let i = 0; i < 5; i++) {
      const opening = rooms.open("ButDoge");
      await new Promise((r) => setImmediate(r));
      await createdRoom(sockets[i]);
      await opening;
    }
    await assert.rejects(
      rooms.open("ButDoge"),
      (err) => err instanceof RoomLimitError && err.retryAfterS === 300
    );
    t = 5 * 60_000; // the window has passed
    const opening = rooms.open("ButDoge");
    await new Promise((r) => setImmediate(r));
    await createdRoom(sockets[5]);
    assert.match((await opening).link, /^https:\/\/bonk\.io\//);
  } finally {
    rooms.closeAll("test"); // also clears the rooms' 10-minute timers
  }
});
