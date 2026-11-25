// Every open room, and the limit on opening them.
//
// bonk.io lets one IP host about 5 rooms per 5 minutes; rooms close after 10
// minutes at most, so at most 5 are open at once.

import { BonkRoom } from "./room.mjs";

export class RoomLimitError extends Error {
  constructor(retryAfterS) {
    super("room limit reached");
    this.retryAfterS = retryAfterS;
  }
}

export class Rooms {
  /**
   * @param {object} opts
   * @param {(url: string) => object} opts.connect
   * @param {() => Promise<object>} opts.locate  {server, lat, long, country}
   * @param {number} [opts.maxPerWindow]
   * @param {number} [opts.windowMs]
   * @param {number} [opts.lifetimeMs]
   * @param {number} [opts.keepClosedMs]  how long a closed room's result stays readable
   * @param {() => number} [opts.now]
   */
  constructor({ connect, locate, maxPerWindow = 5, windowMs = 5 * 60_000, lifetimeMs = 10 * 60_000, keepClosedMs = 15 * 60_000, now = Date.now, botName }) {
    Object.assign(this, { connect, locate, maxPerWindow, windowMs, lifetimeMs, keepClosedMs, now, botName });
    this.rooms = new Map();
    this.openedAt = []; // timestamps of recent opens
  }

  _prune() {
    const t = this.now();
    this.openedAt = this.openedAt.filter((at) => t - at < this.windowMs);
    for (const [id, room] of this.rooms) {
      if (room.state === "closed" && t - room.createdAt > this.keepClosedMs) this.rooms.delete(id);
    }
  }

  /** Open a room for `expectedName`; throws RoomLimitError when at the limit. */
  async open(expectedName) {
    this._prune();
    if (this.openedAt.length >= this.maxPerWindow) {
      const retryAfterS = Math.ceil((this.openedAt[0] + this.windowMs - this.now()) / 1000);
      throw new RoomLimitError(Math.max(1, retryAfterS));
    }
    this.openedAt.push(this.now()); // counts even if bonk.io refuses: it saw the attempt
    const location = await this.locate();
    const room = new BonkRoom({
      connect: this.connect,
      location,
      expectedName,
      lifetimeMs: this.lifetimeMs,
      now: this.now,
      botName: this.botName,
    });
    this.rooms.set(room.id, room);
    await room.open();
    return room;
  }

  get(id) {
    this._prune();
    return this.rooms.get(id) || null;
  }

  openCount() {
    return [...this.rooms.values()].filter((r) => r.state !== "closed").length;
  }

  closeAll(reason) {
    for (const room of this.rooms.values()) room.close(reason);
  }
}
