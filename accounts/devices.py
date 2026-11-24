"""Browsers Bonkverse recognizes (RFC-0003 phase 5, ADR 0025).

Owns: the device cookie that tells one browser from another, and two kinds
of record keyed by it:

- TrustedDevice: made when a group's main account signs in on a browser, so
  the group's accounts switch there without passwords. Expires 90 days
  after its last use.
- RememberedSignIn: made when any account proves itself on a browser
  (password or friend request), so "Choose an account" signs it back in
  with one click, without bonk.io, for ONE_CLICK_SIGN_IN_DAYS after that
  proof.

Both are listed and removed in Settings, and forgotten on "Sign out of all
accounts" when the person ticks "Also forget this device".
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

from django.conf import settings
from django.utils import timezone

from .models import RememberedSignIn, TrustedDevice

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


# ── One-click sign-in (ADR 0025) ─────────────────────────────────────


def _one_click_cutoff():
    return timezone.now() - timedelta(days=settings.ONE_CLICK_SIGN_IN_DAYS)


def remember_sign_in(request, user) -> None:
    """`user` just proved itself on this browser (password or friend
    request): start (or restart) its one-click window here."""
    RememberedSignIn.objects.update_or_create(
        user=user,
        device_hash=_device_hash(request, create=True),
        defaults={
            "proven_at": timezone.now(),
            "label": label_for(request.headers.get("User-Agent", ""))[:80],
        },
    )


def one_click_ids(request, user_ids) -> set[int]:
    """Which of `user_ids` this browser may sign in with one click."""
    device_hash = _device_hash(request, create=False)
    if device_hash is None:
        return set()
    return set(
        RememberedSignIn.objects.filter(
            user_id__in=list(user_ids),
            device_hash=device_hash,
            proven_at__gte=_one_click_cutoff(),
        ).values_list("user_id", flat=True)
    )


def proven_here_ids(request) -> list[int]:
    """Accounts that proved themselves on this browser within the one-click
    window, most recent proof first."""
    device_hash = _device_hash(request, create=False)
    if device_hash is None:
        return []
    return list(
        RememberedSignIn.objects.filter(device_hash=device_hash, proven_at__gte=_one_click_cutoff())
        .order_by("-proven_at")
        .values_list("user_id", flat=True)
    )


def forget_sign_ins_here(request, user_id: int | None = None) -> None:
    """End one-click sign-in on this browser: for one account, or (None)
    for every account."""
    device_hash = _device_hash(request, create=False)
    if device_hash is None:
        return
    remembered = RememberedSignIn.objects.filter(device_hash=device_hash)
    if user_id is not None:
        remembered = remembered.filter(user_id=user_id)
    remembered.delete()


def remembered_browsers(request, user) -> list[dict]:
    """Settings: the browsers where `user` can sign in with one click, newest
    proof first: id, label, proven, until, and whether it's this browser."""
    here = _device_hash(request, create=False)
    days = timedelta(days=settings.ONE_CLICK_SIGN_IN_DAYS)
    return [
        {
            "id": row.pk,
            "label": row.label or "A browser",
            "proven": row.proven_at,
            "until": row.proven_at + days,
            "this_browser": row.device_hash == here,
        }
        for row in RememberedSignIn.objects.filter(
            user=user, proven_at__gte=_one_click_cutoff()
        ).order_by("-proven_at")
    ]


def remove_remembered(user, row_id: int) -> bool:
    """Stop one-click sign-in for `user` on one browser. Returns whether it
    existed."""
    return bool(RememberedSignIn.objects.filter(user=user, pk=row_id).delete()[0])
