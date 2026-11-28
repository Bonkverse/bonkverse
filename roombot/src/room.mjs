// One bonk.io room hosted by the bot, for one sign-in (docs/adr/0026).
//
// Protocol (docs/bonk/rooms.md): connect to https://<server>.bonk.io with
// socket.io v2, create a hidden 2-player room as a guest (12), ask for "no
// host swap" (50) so the room ends when the bot leaves, answer every join (4)
// with the initial data (11) or the joiner hits bonk.io's 6 s "Initial data
// timeout" (a "ghost room"), answer pings (1), and record what players type
// (20). The code itself is checked by Bonkverse, not here.

import { randomBytes } from "node:crypto";

// Socket.io event numbers (bonk.io protocol 49).
export const OUT = { PING_REPLY: 1, KICK: 9, CHAT: 10, INITIAL_DATA: 11, CREATE: 12, NO_HOST_SWAP: 50 };
export const IN = { PING: 1, CREATED: 2, JOINED: 4, LEFT: 5, HOST_LEFT: 6, CHAT: 20, SHARE_LINK: 49 };

export const PROTOCOL_VERSION = 49;
const MAX_MESSAGES = 20;
const MAX_MESSAGE_LENGTH = 40;

// bonk.io names are ASCII; compare like the database's lower() does (only
// ASCII letters fold), never casefold(): "ſ".casefold() == "s" let lookalike
// names match in BonxBot's /link.
export const nameKey = (name) => String(name).replace(/[A-Z]/g, (c) => c.toLowerCase());

const EMPTY_MAP = {
  v: 13,
  s: { re: false, nc: false, pq: 1, gd: 25, fl: false },
  physics: { shapes: [], fixtures: [], bodies: [], bro: [], joints: [], ppm: 12 },
  spawns: [],
  capZones: [],
  m: { a: "Bonkverse", n: "Sign in", dbv: 2, dbid: -1, authid: -1, date: "", rxid: 0, rxn: "", rxa: "", rxdb: 1, cr: [], pub: false, mo: "" },
};
export const INITIAL_GAME_SETTINGS = { map: EMPTY_MAP, gt: 2, wl: 3, q: false, tl: false, tea: false, ga: "b", mo: "b", bal: [] };

/**
 * A room for one expected bonk.io account.
 *
 * @param {object} opts
 * @param {(url: string) => object} opts.connect  socket.io v2 client factory
 * @param {{server: string, lat?: number, long?: number, country?: string}} opts.location
 * @param {string} opts.expectedName  the bonk.io name the claim is for
 * @param {number} opts.lifetimeMs  closes by itself after this long
 * @param {() => number} [opts.now]
 */
export class BonkRoom {
  constructor({ connect, location, expectedName, lifetimeMs, now = Date.now, botName = "Bonkverse" }) {
    this.id = randomBytes(12).toString("base64url");
    this.expectedName = expectedName;
    this.state = "opening"; // opening | open | closed
    this.closedReason = null;
    this.link = null;
    this.players = new Map(); // bonk player id -> {username, guest, level}
    this.messages = []; // {username, guest, text, at}
    this.createdAt = now();
    this._now = now;
    this._location = location;
    this._connect = connect;
    this._botName = botName;
    this._lifetimeMs = lifetimeMs;
    this._password = randomBytes(9).toString("base64url");
  }

  /** Connect and create the room; resolves with the share link. */
  open({ timeoutMs = 15_000 } = {}) {
    return new Promise((resolve, reject) => {
      const fail = (reason) => {
        this.close(reason);
        reject(new Error(reason));
      };
      const timer = setTimeout(() => fail("open_timeout"), timeoutMs);
      const socket = (this._socket = this._connect(`https://${this._location.server}.bonk.io`));

      socket.on("connect", () => {
        socket.emit(OUT.CREATE, {
          peerID: "", // no P2P: the bot only chats
          roomName: "Bonkverse sign-in",
          maxPlayers: 2,
          password: this._password, // the share link carries the bypass
          dbid: 0, // what bonk.io's client sends for a guest
          guest: true,
          guestName: this._botName,
          minLevel: 0,
          maxLevel: 999,
          latitude: this._location.lat ?? 0,
          longitude: this._location.long ?? 0,
          country: this._location.country || "US",
          version: PROTOCOL_VERSION,
          hidden: 1,
          quick: false,
          mode: "custom",
          avatar: { layers: [], bc: 4492543 },
        });
      });
      socket.on("connect_error", () => fail("connect_error"));
      socket.on("disconnect", () => this._closed(this.closedReason || "disconnected"));

      socket.on(IN.PING, (_pings, id) => socket.emit(OUT.PING_REPLY, { id }));
      // Without this, the server hands host to the player when the bot
      // leaves, and the room stays open (HOST_LEFT with a new host id).
      socket.on(IN.CREATED, () => socket.emit(OUT.NO_HOST_SWAP));
      socket.on(IN.SHARE_LINK, (autoJoinId, bypass) => {
        clearTimeout(timer);
        this.link = `https://bonk.io/${autoJoinId}${bypass}`;
        this.state = "open";
        this._lifetime = setTimeout(() => this.close("expired"), this._lifetimeMs);
        resolve(this.link);
      });
      socket.on(IN.JOINED, (id, _peerId, username, guest, level) => this._joined(id, username, guest, level));
      socket.on(IN.LEFT, (id) => this.players.delete(id));
      socket.on(IN.CHAT, (id, message) => this._chat(id, message));
    });
  }

  _joined(id, username, guest, level) {
    const player = { username: String(username), guest: guest === true, level: Number(level) || 0 };
    this.players.set(id, player);
    // Initial data first: the joiner's client is waiting for it (6 s).
    this._socket.emit(OUT.INITIAL_DATA, { sid: id, gs: INITIAL_GAME_SETTINGS });
    if (player.guest) {
      // A guest can use any name, so a guest's code proves nothing.
      this._say(`Guests can't sign in. Log in to your bonk.io account first, then join again.`);
      this._kick(id);
    } else if (nameKey(player.username) !== nameKey(this.expectedName)) {
      this._say(`This room is for ${this.expectedName}.`);
      this._kick(id);
    } else {
      this._say(`Hi ${player.username}! Type the code shown on Bonkverse.`);
    }
  }

  _chat(id, message) {
    const player = this.players.get(id);
    if (!player || this.messages.length >= MAX_MESSAGES) return; // id 0 is the bot itself
    this.messages.push({
      username: player.username,
      guest: player.guest,
      text: String(message).trim().slice(0, MAX_MESSAGE_LENGTH),
      at: this._now(),
    });
  }

  _say(message) {
    setTimeout(() => this._socket?.emit(OUT.CHAT, { message }), 800);
  }

  _kick(id) {
    // Unverified live: kick is 9 {banshortid, kickonly: true} per bonk.io's
    // client (ban) and DemystifyBonk; it frees the slot for the real player.
    setTimeout(() => this._socket?.emit(OUT.KICK, { banshortid: id, kickonly: true }), 2500);
  }

  /** Close the room (it ends: no host swap). Optionally say something first. */
  close(reason, message) {
    if (this.state === "closed" || this.state === "closing") return;
    this.closedReason = this.closedReason || reason;
    clearTimeout(this._lifetime);
    if (message && this._socket && this.state === "open") {
      this._socket.emit(OUT.CHAT, { message });
      setTimeout(() => this._socket.close(), 1500);
      this.state = "closing";
    } else {
      this._socket?.close();
      this._closed(reason);
    }
  }

  _closed(reason) {
    this.closedReason = this.closedReason || reason;
    this.state = "closed";
    clearTimeout(this._lifetime);
  }

  /** What Bonkverse reads (never the password or the bypass beyond the link). */
  view() {
    return {
      id: this.id,
      state: this.state === "closing" ? "closed" : this.state,
      closed_reason: this.closedReason,
      link: this.link,
      expected_name: this.expectedName,
      players: [...this.players.values()],
      messages: this.messages,
    };
  }
}
