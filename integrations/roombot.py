"""The room service (roombot/), which hosts bonk.io rooms for room-code sign-in
(ADR 0026, experimental).

Owns: the request shapes, the timeouts, the bearer token, and turning every
failure into a result with an error instead of an exception.
Does not own: codes, claims or signing in (accounts/room_claims.py).

Free of Django at import time; the functions at the bottom read the URL and
token from settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

OPEN_TIMEOUT = (5.0, 25.0)  # opening waits for bonk.io to create the room
READ_TIMEOUT = (3.0, 5.0)


@dataclass(frozen=True)
class Player:
    username: str
    guest: bool
    level: int


@dataclass(frozen=True)
class Message:
    username: str
    guest: bool
    text: str


@dataclass(frozen=True)
class Room:
    id: str
    link: str = ""
    open: bool = True
    players: list[Player] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)


@dataclass(frozen=True)
class RoomResult:
    room: Room | None = None
    error: str | None = None  # "busy", "unavailable", "not_found", or a short reason
    retry_after: int = 0  # seconds, when busy


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def open_room(base_url: str, token: str, name: str) -> RoomResult:
    """Ask the room service for a room for `name`. Never raises."""
    try:
        reply = requests.post(
            f"{base_url}/rooms", json={"name": name}, headers=_headers(token), timeout=OPEN_TIMEOUT
        )
    except requests.RequestException as exc:
        logger.warning("room service unreachable: %s", type(exc).__name__)
        return RoomResult(error="unavailable")
    if reply.status_code == 429:
        try:
            retry = int(reply.json().get("retry_after", 60))
        except (ValueError, AttributeError):
            retry = 60
        return RoomResult(error="busy", retry_after=max(1, retry))
    if reply.status_code != 201:
        logger.warning("room service refused to open a room: %s", reply.status_code)
        return RoomResult(error="unavailable")
    try:
        data = reply.json()
        return RoomResult(room=Room(id=str(data["id"]), link=str(data["link"])))
    except (ValueError, KeyError, TypeError):
        return RoomResult(error="unavailable")


def read_room(base_url: str, token: str, room_id: str) -> RoomResult:
    """Who is in the room and what they typed. Never raises."""
    try:
        reply = requests.get(
            f"{base_url}/rooms/{room_id}", headers=_headers(token), timeout=READ_TIMEOUT
        )
    except requests.RequestException as exc:
        logger.warning("room service unreachable: %s", type(exc).__name__)
        return RoomResult(error="unavailable")
    if reply.status_code == 404:
        return RoomResult(error="not_found")
    if reply.status_code != 200:
        return RoomResult(error="unavailable")
    try:
        data = reply.json()
        return RoomResult(
            room=Room(
                id=str(data["id"]),
                link=str(data.get("link") or ""),
                open=data.get("state") == "open",
                players=[
                    Player(str(p["username"]), p.get("guest") is True, int(p.get("level") or 0))
                    for p in data.get("players", [])
                ],
                messages=[
                    Message(str(m["username"]), m.get("guest") is True, str(m.get("text", "")))
                    for m in data.get("messages", [])
                ],
            )
        )
    except (ValueError, KeyError, TypeError):
        return RoomResult(error="unavailable")


def close_room(base_url: str, token: str, room_id: str, message: str = "") -> bool:
    """Close the room, saying `message` in it first. Never raises."""
    try:
        reply = requests.post(
            f"{base_url}/rooms/{room_id}/close",
            json={"message": message} if message else {},
            headers=_headers(token),
            timeout=READ_TIMEOUT,
        )
    except requests.RequestException:
        return False
    return reply.status_code == 200


def say_in_room(base_url: str, token: str, room_id: str, message: str) -> bool:
    """Say `message` in the open room (a wrong code, say). Never raises."""
    try:
        reply = requests.post(
            f"{base_url}/rooms/{room_id}/say",
            json={"message": message},
            headers=_headers(token),
            timeout=READ_TIMEOUT,
        )
    except requests.RequestException:
        return False
    return reply.status_code == 200


# ── With settings ─────────────────────────────────────────────────────


def configured() -> bool:
    from django.conf import settings

    return bool(getattr(settings, "ROOMBOT_URL", "") and getattr(settings, "ROOMBOT_TOKEN", ""))


def _conf():
    from django.conf import settings

    return settings.ROOMBOT_URL, settings.ROOMBOT_TOKEN


def open_room_for(name: str) -> RoomResult:
    return open_room(*_conf(), name)


def read(room_id: str) -> RoomResult:
    return read_room(*_conf(), room_id)


def close(room_id: str, message: str = "") -> bool:
    return close_room(*_conf(), room_id, message)


def say(room_id: str, message: str) -> bool:
    return say_in_room(*_conf(), room_id, message)
