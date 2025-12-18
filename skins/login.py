# skins/login.py

from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib import messages
from django_ratelimit.decorators import ratelimit
from django.core import signing

from .models import BonkUser, BonkPlayer, BonkAccountLink
from .forms import LoginForm
from .friends_sync import sync_friends_for_player
from .flash_friends_sync import sync_flash_friends_for_user

import os
import time
import threading
import logging
import requests
from requests.exceptions import RequestException
from json import JSONDecodeError

logger = logging.getLogger(__name__)

BONK_LOGIN_URL   = "https://bonk2.io/scripts/login_legacy.php"
BONK_FRIENDS_URL = "https://bonk2.io/scripts/friends.php"

# Configurable timeouts
CONNECT_TIMEOUT = float(os.getenv("BONK_CONNECT_TIMEOUT", "4"))
READ_TIMEOUT    = float(os.getenv("BONK_READ_TIMEOUT", "8"))
REQ_TIMEOUT     = (CONNECT_TIMEOUT, READ_TIMEOUT)

# Optional background sync toggle
SYNC_FRIENDS_ON_LOGIN = os.getenv("SYNC_FRIENDS_ON_LOGIN", "1").lower() in ("1", "true", "yes")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    ),
    "Origin": "https://bonk.io",
    "Referer": "https://bonk.io/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch_friends(token: str) -> dict:
    """Fetch *regular* friends (not flash) from friends.php"""
    r = requests.post(
        BONK_FRIENDS_URL,
        data={"token": token, "task": "getfriends"},
        headers=BROWSER_HEADERS,
        timeout=REQ_TIMEOUT,
    )
    r.raise_for_status()
    try:
        return r.json()
    except JSONDecodeError:
        return {"r": "error", "error": "Non-JSON response from friends.php"}


def _sync_friends_bg(current_bonk_id: int | None, current_username: str, token: str) -> None:
    """
    Background sync for regular friends only (from friends.php).
    Flash friends are synced immediately during login.
    """
    t0 = time.monotonic()
    try:
        payload = _fetch_friends(token)

        if payload.get("r") != "success":
            logger.warning("friends sync skipped: %s", payload.get("error") or payload)
            return

        stats = sync_friends_for_player(
            current_bonk_id=current_bonk_id,
            current_username=current_username,
            friends_json=payload,
        )

        logger.info("regular friends synced for %s: %s (%.2fs)",
                    current_username, stats, time.monotonic() - t0)

    except Exception:
        logger.exception("background friends sync failed for %s", current_username)


@ratelimit(key="ip", rate="15/h", method="POST", block=True)
def login_view(request):
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            typed_username = form.cleaned_data["username"].strip()
            password = form.cleaned_data["password"]

            s = requests.Session()
            try:
                resp = s.post(
                    BONK_LOGIN_URL,
                    data={"username": typed_username, "password": password},
                    headers=BROWSER_HEADERS,
                    timeout=REQ_TIMEOUT,
                )
            except RequestException as e:
                messages.error(request, f"Network error talking to Bonk.io: {e}")
                return render(request, "skins/login.html", {"form": form})

            data = None
            try:
                data = resp.json()
            except JSONDecodeError:
                snippet = resp.text[:400].replace("\n", " ")
                logger.warning("[bonkverse] Non-JSON login response (%s): %s", resp.status_code, snippet)

            if data and data.get("r") == "success" and data.get("token"):
                token = data["token"]
                bonk_username = data.get("username") or typed_username
                bonk_user_id  = data.get("id")

                # Session (no password stored)
                request.session["bonk_token"] = token
                request.session["bonk_username"] = bonk_username
                request.session["bonk_user_id"] = bonk_user_id

                # Site account
                user, _ = BonkUser.objects.get_or_create(username=bonk_username)
                login(request, user)

                # BonkPlayer + AccountLink
                if bonk_user_id:
                    try:
                        player, _ = BonkPlayer.objects.update_or_create(
                            bonk_id=int(bonk_user_id),
                            defaults={"username": bonk_username},
                        )
                        signed_token = signing.dumps({"t": token}, salt="bonk_token")
                        BonkAccountLink.objects.update_or_create(
                            user=user,
                            bonk_player=player,
                            defaults={
                                "token_encrypted": signed_token,
                                "scopes": {"friends": True},
                                "active": True,
                            },
                        )
                    except Exception:
                        logger.exception("[bonkverse] Could not persist account link")

                # 🔹 Flash friends sync immediately (from login response)
                try:
                    flash_stats = sync_flash_friends_for_user(user=user, friends_json=data)
                    logger.info("flash friends synced at login for %s: %s", bonk_username, flash_stats)
                except Exception:
                    logger.exception("flash friends immediate sync failed for %s", bonk_username)

                # 🔹 Async regular friends sync
                if SYNC_FRIENDS_ON_LOGIN:
                    threading.Thread(
                        target=_sync_friends_bg,
                        args=(bonk_user_id, bonk_username, token),
                        daemon=True,
                    ).start()
                    messages.info(request, "Syncing your regular friends in the background…")

                messages.success(request, "Logged in successfully!")
                return redirect("my_profile")

            # Failed login
            detail = (data or {}).get("r") or (data or {}).get("error") or "unknown error"
            messages.error(request, f"Bonk.io login failed: {detail}. Check your credentials.")

    else:
        form = LoginForm()

    return render(request, "skins/login.html", {"form": form})


def logout_view(request):
    for k in ("bonk_token", "bonk_username", "bonk_user_id"):
        request.session.pop(k, None)
    logout(request)
    messages.success(request, "Logged out!")
    return redirect("home")
