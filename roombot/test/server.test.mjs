import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer, authorized } from "../src/server.mjs";
import { Rooms } from "../src/rooms.mjs";
import { fakeConnect, createdRoom } from "./fake-socket.mjs";

const TOKEN = "t".repeat(40);
const quiet = { info() {}, warn() {}, error() {} };

async function withServer(fn) {
  const { connect, sockets } = fakeConnect();
  const rooms = new Rooms({ connect, locate: async () => ({ server: "b2ny1" }) });
  const server = createServer({ rooms, token: TOKEN, log: quiet });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const call = (path, { method = "GET", body, auth = TOKEN } = {}) =>
    fetch(base + path, {
      method,
      headers: { ...(auth ? { Authorization: `Bearer ${auth}` } : {}), "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  try {
    await fn({ call, sockets, rooms });
  } finally {
    rooms.closeAll("test");
    server.close();
  }
}

test("the token is required and compared exactly", () => {
  assert.equal(authorized(`Bearer ${TOKEN}`, TOKEN), true);
  assert.equal(authorized(`Bearer ${TOKEN}x`, TOKEN), false);
  assert.equal(authorized(TOKEN, TOKEN), false); // no Bearer prefix
  assert.equal(authorized("", TOKEN), false);
  assert.equal(authorized(`Bearer ${TOKEN}`, ""), false); // no token configured: nobody
});

test("every route but /health needs the token", async () => {
  await withServer(async ({ call }) => {
    assert.equal((await call("/health", { auth: null })).status, 200);
    assert.equal((await call("/rooms", { method: "POST", body: { name: "x" }, auth: null })).status, 401);
    assert.equal((await call("/rooms/abcdefghijkl", { auth: "wrong" })).status, 401);
  });
});

test("open a room, read who joined and what they typed, close it", async () => {
  await withServer(async ({ call, sockets }) => {
    const opening = call("/rooms", { method: "POST", body: { name: "ButDoge" } });
    await new Promise((r) => setTimeout(r, 50));
    await createdRoom(sockets[0]);
    const res = await opening;
    assert.equal(res.status, 201);
    const { id, link } = await res.json();
    assert.equal(link, "https://bonk.io/816187dbais");

    sockets[0].receive(4, 1, "peer", "ButDoge", false, 52, 1, {});
    sockets[0].receive(20, 1, " W8NMFD ");
    const view = await (await call(`/rooms/${id}`)).json();
    assert.equal(view.state, "open");
    assert.deepEqual(view.players, [{ username: "ButDoge", guest: false, level: 52 }]);
    assert.equal(view.messages[0].text, "W8NMFD");
    assert.equal(JSON.stringify(view).includes("password"), false);

    const closed = await call(`/rooms/${id}/close`, { method: "POST", body: { message: "Done!" } });
    assert.equal((await closed.json()).state, "closed");
  });
});

test("say something in an open room; a closed or unknown room can't", async () => {
  await withServer(async ({ call, sockets }) => {
    const opening = call("/rooms", { method: "POST", body: { name: "ButDoge" } });
    await new Promise((r) => setTimeout(r, 50));
    await createdRoom(sockets[0]);
    const { id } = await (await opening).json();

    const said = await call(`/rooms/${id}/say`, { method: "POST", body: { message: "That's not the code. 2 tries left." } });
    assert.equal(said.status, 200);
    assert.ok(sockets[0].sent.some(([, data]) => data?.message === "That's not the code. 2 tries left."));
    assert.equal((await call(`/rooms/${id}/say`, { method: "POST", body: { message: " " } })).status, 400);
    assert.equal((await call(`/rooms/${id}/say`, { method: "POST", body: { message: 42 } })).status, 400);
    await call(`/rooms/${id}/say`, { method: "POST", body: { message: "x".repeat(500) } });
    assert.ok(sockets[0].sent.some(([, data]) => data?.message === "x".repeat(120)));

    await call(`/rooms/${id}/close`, { method: "POST", body: {} });
    assert.equal((await call(`/rooms/${id}/say`, { method: "POST", body: { message: "hi" } })).status, 409);
    assert.equal((await call("/rooms/abcdefghijkl/say", { method: "POST", body: { message: "hi" } })).status, 404);
  });
});

test("names must be plain ASCII and short", async () => {
  await withServer(async ({ call }) => {
    for (const name of ["", " ", "x".repeat(65), "Boſsman", 42]) {
      assert.equal((await call("/rooms", { method: "POST", body: { name } })).status, 400, String(name));
    }
  });
});

test("at the limit: 429 with Retry-After", async () => {
  await withServer(async ({ call, rooms }) => {
    rooms.openedAt = Array(5).fill(Date.now());
    const res = await call("/rooms", { method: "POST", body: { name: "ButDoge" } });
    assert.equal(res.status, 429);
    assert.ok(Number(res.headers.get("retry-after")) > 0);
  });
});

test("unknown rooms are 404; huge bodies are refused", async () => {
  await withServer(async ({ call }) => {
    assert.equal((await call("/rooms/abcdefghijkl")).status, 404);
    const big = await call("/rooms", { method: "POST", body: { name: "x".repeat(10_000) } });
    assert.ok([400, 413].includes(big.status));
  });
});
