// A stand-in for a socket.io v2 connection to a bonk.io room server.
export class FakeSocket {
  constructor() {
    this.handlers = new Map();
    this.sent = []; // [event, payload]
    this.closed = false;
  }
  on(event, fn) {
    this.handlers.set(event, fn);
    return this;
  }
  emit(event, payload) {
    this.sent.push([event, payload]);
  }
  close() {
    this.closed = true;
    this.handlers.get("disconnect")?.("io client disconnect");
  }
  /** The server sends `event` with `args` to the bot. */
  receive(event, ...args) {
    this.handlers.get(event)?.(...args);
  }
  sentOf(event) {
    return this.sent.filter(([e]) => e === event).map(([, p]) => p);
  }
}

/** A connect() that hands out FakeSockets and keeps them. */
export function fakeConnect() {
  const sockets = [];
  const connect = (url) => {
    const s = new FakeSocket();
    s.url = url;
    sockets.push(s);
    return s;
  };
  return { connect, sockets };
}

/** Plays the server side of creating a room (as seen live on 2026-11-25). */
export async function createdRoom(socket) {
  socket.receive("connect");
  socket.receive(2, "socket-id", 1, null);
  socket.receive(49, 816187, "dbais");
  await new Promise((r) => setImmediate(r));
}
