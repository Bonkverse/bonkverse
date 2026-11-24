"""Trusted browsers for a group of bonk.io accounts (RFC-0003 phase 5).

Owns: the device cookie that tells one browser from another, and the
TrustedDevice records: made when a group's main account signs in on a
browser, listed and removed in Settings, forgotten on "Sign out of all
accounts" when the person ticks "Also forget this device", and expired 90
days after their last use.
Does not own: which accounts a browser may switch to (groups.py reads
`is_trusted` for that).

The cookie holds a random id, signed so it can't be forged; the database
keeps only its SHA-256, so a database copy can't be turned into a cookie.
`DeviceCookieMiddleware` gives a browser its id the first time a trust is
made there.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta

from django.utils import timezone

from .models import TrustedDevice

COOKIE = "bv_device"
COOKIE_SALT = "accounts.devices"
COOKIE_MAX_AGE = 400 * 24 * 3600  # browsers cap cookies at 400 days
TRUST_DAYS = 90
# last_used_at is written at most this often per device.
TOUCH_EVERY = timedelta(hours=12)


class DeviceCookieMiddleware:
    """Reads this browser's device id (`request.bv_device`), and sets the
    cookie on the way out when `devices.trust` gave the browser a new one."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw = request.get_signed_cookie(COOKIE, default=None, salt=COOKIE_SALT)
        request.bv_device = raw
        request.bv_device_new = False
        response = self.get_response(request)
        if request.bv_device_new and request.bv_device:
            response.set_signed_cookie(
                COOKIE,
                request.bv_device,
                salt=COOKIE_SALT,
                max_age=COOKIE_MAX_AGE,
                secure=request.is_secure(),
                httponly=True,
                samesite="Lax",
            )
        return response


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _device_hash(request, *, create: bool) -> str | None:
    raw = getattr(request, "bv_device", None)
    if raw is None and create:
        raw = secrets.token_urlsafe(32)
        request.bv_device = raw
        request.bv_device_new = True
    return _hash(raw) if raw else None


def label_for(user_agent: str) -> str:
    """A rough browser and OS name for the settings list, e.g. "Chrome on
    Windows". Unknown parts are left out."""
    ua = user_agent or ""
    browser = next(
        (
            name
            for pattern, name in (
                (r"Edg/", "Edge"),
                (r"OPR/|Opera", "Opera"),
                (r"Firefox/", "Firefox"),
                (r"Chrome/|CriOS/", "Chrome"),
                (r"Safari/", "Safari"),
            )
            if re.search(pattern, ua)
        ),
        "",
    )
    system = next(
        (
            name
            for pattern, name in (
                (r"iPhone|iPad|iPod", "iOS"),
                (r"Android", "Android"),
                (r"Windows", "Windows"),
                (r"Mac OS X|Macintosh", "macOS"),
                (r"CrOS", "ChromeOS"),
                (r"Linux", "Linux"),
            )
            if re.search(pattern, ua)
        ),
        "",
    )
    if browser and system:
        return f"{browser} on {system}"
    return browser or system or "A browser"


def trust(request, group) -> None:
    """The main signed in on this browser: trust it for `group` (or refresh
    the trust), giving the browser a device cookie if it has none."""
    device_hash = _device_hash(request, create=True)
    TrustedDevice.objects.update_or_create(
        group=group,
        device_hash=device_hash,
        defaults={
            "last_used_at": timezone.now(),
            "label": label_for(request.headers.get("User-Agent", ""))[:80],
        },
    )


def is_trusted(request, group_id: int) -> bool:
    """Whether this browser is trusted for the group and was used within
    TRUST_DAYS. Touches last_used_at (at most every TOUCH_EVERY)."""
    device_hash = _device_hash(request, create=False)
    if device_hash is None:
        return False
    now = timezone.now()
    device = TrustedDevice.objects.filter(
        group_id=group_id,
        device_hash=device_hash,
        last_used_at__gte=now - timedelta(days=TRUST_DAYS),
    ).first()
    if device is None:
        return False
    if now - device.last_used_at > TOUCH_EVERY:
        TrustedDevice.objects.filter(pk=device.pk).update(last_used_at=now)
    return True


def forget_this(request, group_id: int) -> None:
    """Stop trusting this browser for the group."""
    device_hash = _device_hash(request, create=False)
    if device_hash:
        TrustedDevice.objects.filter(group_id=group_id, device_hash=device_hash).delete()


def listed(request, group_id: int) -> list[dict]:
    """The group's trusted browsers for Settings, newest use first: id,
    label, since, last used, and whether it's this browser."""
    here = _device_hash(request, create=False)
    cutoff = timezone.now() - timedelta(days=TRUST_DAYS)
    return [
        {
            "id": device.pk,
            "label": device.label or "A browser",
            "since": device.created_at,
            "last_used": device.last_used_at,
            "this_browser": device.device_hash == here,
        }
        for device in TrustedDevice.objects.filter(
            group_id=group_id, last_used_at__gte=cutoff
        ).order_by("-last_used_at")
    ]


def remove(group_id: int, device_id: int) -> bool:
    """Stop trusting one of the group's browsers. Returns whether it existed."""
    return bool(TrustedDevice.objects.filter(group_id=group_id, pk=device_id).delete()[0])
