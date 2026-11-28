// Private HTTP API for Bonkverse (integrations/roombot.py). Every route but
// /health needs `Authorization: Bearer <ROOMBOT_TOKEN>`.
//
//   POST /rooms {"name": "..."}       -> 201 {id, link, expires_in} | 429 {retry_after}
//   GET  /rooms/:id                   -> {id, state, link, players, messages, ...}
//   POST /rooms/:id/close {"message"} -> {id, state}
//   GET  /health                      -> {ok, open}

import http from "node:http";
import { createHash, timingSafeEqual } from "node:crypto";
import { RoomLimitError } from "./rooms.mjs";

const MAX_BODY = 4 * 1024;
const NAME_MAX = 64;
const sha256 = (s) => createHash("sha256").update(String(s)).digest();

export function authorized(header, token) {
  if (!token) return false;
  const given = /^Bearer (.+)$/.exec(header || "")?.[1] ?? "";
  return timingSafeEqual(sha256(given), sha256(token)); // equal lengths, constant time
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (c) => {
      size += c.length;
      if (size <= MAX_BODY) chunks.push(c); // past the limit: drain, keep nothing
    });
    req.on("end", () => {
      if (size > MAX_BODY) return reject(Object.assign(new Error("too_large"), { status: 413 }));
      try {
        resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {});
      } catch {
        reject(Object.assign(new Error("bad_json"), { status: 400 }));
      }
    });
  });
}

const send = (res, status, body, headers = {}) => {
  res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", ...headers });
  res.end(JSON.stringify(body));
};

export function createServer({ rooms, token, log = console }) {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://x");
    try {
      if (req.method === "GET" && url.pathname === "/health") {
        return send(res, 200, { ok: true, open: rooms.openCount() });
      }
      if (!authorized(req.headers.authorization, token)) return send(res, 401, { error: "unauthorized" });

      if (req.method === "POST" && url.pathname === "/rooms") {
        const { name } = await readJson(req);
        if (typeof name !== "string" || !name.trim() || name.length > NAME_MAX || !/^[\x20-\x7e]+$/.test(name)) {
          return send(res, 400, { error: "bad_name" });
        }
        try {
          const room = await rooms.open(name.trim());
          log.info(`room ${room.id} opened`);
          return send(res, 201, { id: room.id, link: room.link, expires_in: Math.round(rooms.lifetimeMs / 1000) });
        } catch (err) {
          if (err instanceof RoomLimitError) {
            return send(res, 429, { error: "busy", retry_after: err.retryAfterS }, { "Retry-After": String(err.retryAfterS) });
          }
          log.warn(`room open failed: ${err.message}`);
          return send(res, 502, { error: "bonk_unreachable" });
        }
      }

      const match = /^\/rooms\/([A-Za-z0-9_-]{8,40})(\/close|\/say)?$/.exec(url.pathname);
      if (match) {
        const room = rooms.get(match[1]);
        if (!room) return send(res, 404, { error: "not_found" });
        if (req.method === "GET" && !match[2]) return send(res, 200, room.view());
        if (req.method === "POST" && match[2] === "/close") {
          const { message } = await readJson(req);
          room.close("closed_by_bonkverse", typeof message === "string" ? message.slice(0, 120) : undefined);
          return send(res, 200, { id: room.id, state: "closed" });
        }
        if (req.method === "POST" && match[2] === "/say") {
          const { message } = await readJson(req);
          if (typeof message !== "string" || !message.trim()) return send(res, 400, { error: "bad_message" });
          const said = room.say(message.slice(0, 120));
          return send(res, said ? 200 : 409, said ? { id: room.id, said: true } : { error: "not_open" });
        }
      }
      return send(res, 404, { error: "not_found" });
    } catch (err) {
      if (err.status) return send(res, err.status, { error: err.message });
      log.error("roombot error", err);
      return send(res, 500, { error: "internal" });
    }
  });
}
