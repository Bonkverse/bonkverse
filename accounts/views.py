"""The /login/ and /logout/ pages, /api/me/, and switching accounts.

Owns: the login, logout and who-am-I views, and the actions on a person's
bonk.io accounts (switch, add, remove, make main; the rules are in
groups.py).
Does not own: the sentences shown when a login is turned down
(login_messages.py), trying the bonk.io login and the limit on wrong
passwords (login_attempts.py), what a successful login does (sign_in.py:
site account, account link, Flash friends, queueing the friend sync), or
talking to bonk.io (integrations/bonk_api.py).
"""

import json
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.ratelimits import limit
from players import selectors as player_selectors

from . import (
    appearance,
    bot_account,
    bot_check,
    devices,
    groups,
    known_accounts,
    link_claims,
    used_here,
)
from .forms import LoginForm
from .login_attempts import attempt_login
from .login_messages import login_failure_message
from .models import BonkUser
from .sign_in import sign_in, sign_in_with_one_click


@limit("login", method="POST")
def login_view(request):
    """Log in with a bonk.io account.

    `?add=1` while signed in is "Add account" (RFC-0003 phase 5): the account
    logged in to joins the signed-in account's group and both stay signed in
    on this browser. `?username=` fills in the name (the account menu's
    "Sign in" for a group account not signed in here).
    """
    adding = request.user.is_authenticated and "1" in (
        request.POST.get("add"),
        request.GET.get("add"),
    )
    if request.method != "POST":
        chooser = _account_chooser(request)
        if chooser:
            # Signed out, with accounts used here before: "Choose an account".
            return render(
                request,
                "accounts/choose_account.html",
                {"choices": chooser, "next": request.GET.get("next", "")},
            )
        initial = {"username": request.GET.get("username", "")[:100]}
        return _render_login(request, LoginForm(initial=initial), adding=adding)

    form = LoginForm(request.POST)
    if not form.is_valid():
        return _render_login(request, form, adding=adding)

    remember = form.cleaned_data["remember"]
    attempt = attempt_login(
        request,
        form.cleaned_data["username"],
        form.cleaned_data["password"],
        via="page",
        remember=remember,
    )
    if not attempt.ok:
        retry_after = attempt.retry_after
        messages.error(
            request,
            f"Bonk.io login failed: {login_failure_message(attempt.error, retry_after)}",
        )
        # The page keeps the Login button off until the wait ends, so players
        # don't resubmit into it (6 tries in a minute on 2026-11-09).
        return _render_login(request, form, retry_after=retry_after, adding=adding)

    user = sign_in(request, attempt.result, remember=remember, add=adding)
    if adding:
        messages.success(request, f"Added {user.username}. You're now using it.")
    else:
        messages.success(request, "Logged in successfully!")

    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("players:player_profile", request.user.username)


def _render_login(request, form, *, retry_after=None, adding=False):
    """The login page, with the "not a bot" check when this visitor's next
    try needs it (bot_check.py)."""
    return render(
        request,
        "accounts/login.html",
        {
            "form": form,
            "retry_after": retry_after,
            "adding": adding,
            # "Used on this browser": add without proving again (used_here.py).
            "used_here": used_here.rows(request) if adding else [],
            "friend_requests": bot_account.configured(),
            "turnstile_site_key": bot_check.site_key_if_wanted(request),
        },
    )


@require_POST
@limit("write")
def logout_view(request):
    """POST only (the header's Log out is a form), so another site can't
    sign people out with a link or an <img>.

    `scope=this` signs out of the account in use only and switches to
    another one still signed in on this browser; anything else signs out of
    every account here.
    """
    if not request.user.is_authenticated:
        return redirect("site_pages:home")
    leaving = request.user.username
    now = groups.sign_out(
        request,
        everywhere_here=request.POST.get("scope") != "this",
        # "Also forget this device" under "Sign out of all accounts".
        forget_device=request.POST.get("forget") == "on",
    )
    if now is None:
        messages.success(request, "Logged out!")
        return redirect("site_pages:home")
    messages.success(request, f"Signed out of {leaving}. You're now using {now.username}.")
    return redirect(_back(request))


def _account_chooser(request) -> list[dict]:
    """The login page's "Choose an account" (accounts/known_accounts.py): the
    accounts used on this browser, each with its picture and the way it last
    signed in, or [] to show the plain form (signed in, a name given, or
    "Use another account")."""
    if request.user.is_authenticated or request.GET.get("username") or request.GET.get("other"):
        return []
    known = known_accounts.accounts(request)
    if not known:
        return []
    names = [a["username"] for a in known]
    codes = player_selectors.worn_skin_codes(names)
    ids = _site_ids(names)
    one_click = devices.one_click_ids(request, ids.values())
    for account in known:
        code = codes.get(account["username"].lower())
        account["thumbnail"] = (
            player_selectors.skin_avatar_url(account["username"], code) if code else None
        )
        # Proved itself here recently: one click signs it in (ADR 0025).
        account["one_click"] = ids.get(account["username"].casefold()) in one_click
    return known


def _site_ids(names: list[str]) -> dict[str, int]:
    """Site account ids by casefolded name, for the chooser's names (at most
    known_accounts.MAX_ACCOUNTS)."""
    match = Q()
    for name in names:
        match |= Q(username__iexact=name)
    found: dict[str, int] = {}
    for pk, username in BonkUser.objects.filter(match).order_by("pk").values_list("pk", "username"):
        found.setdefault(username.casefold(), pk)
    return found


@require_POST
@limit("write")
def one_click_sign_in(request):
    """The chooser's one click: sign an account back in on a browser where
    it proved itself within ONE_CLICK_SIGN_IN_DAYS, with no bonk.io call
    (ADR 0025). Past that, it goes to the way it last signed in."""
    name = (request.POST.get("username") or "")[:64]
    user = BonkUser.objects.filter(username__iexact=name).order_by("pk").first() if name else None
    if user is None or user.pk not in devices.one_click_ids(request, [user.pk]):
        way = known_accounts.way_in(request, name)
        target = (
            "accounts:friend_request_login"
            if way == known_accounts.FRIEND_REQUEST
            else "accounts:login"
        )
        query = {"username": name}
        if _safe_next(request):
            query["next"] = _safe_next(request)
        return redirect(f"{reverse(target)}?{urlencode(query)}")
    sign_in_with_one_click(request, user)
    messages.success(request, f"Welcome back, {user.username}.")
    return redirect(_safe_next(request) or reverse("players:player_profile", args=[user.username]))


@require_POST
@limit("write")
def forget_known_account(request):
    """The chooser's Remove: take one account off this browser's list and
    end its one-click sign-in here."""
    name = (request.POST.get("username") or "")[:64]
    known_accounts.forget(request, name)
    user = BonkUser.objects.filter(username__iexact=name).first() if name else None
    if user is not None:
        devices.forget_sign_ins_here(request, user.pk)
    return redirect(reverse("accounts:login") + _next_query(request))


def _next_query(request) -> str:
    next_url = _safe_next(request)
    return f"?next={next_url}" if next_url else ""


@limit("login", method="POST")
def friend_request_login(request):
    """Sign in, or add an account, with a friend request instead of a
    password (accounts/link_claims.py, RFC-0003 phase 6). GET: the name
    form. POST: start the claim and go to the waiting page."""
    adding = request.user.is_authenticated and "1" in (
        request.POST.get("add"),
        request.GET.get("add"),
    )
    name = (request.POST.get("username") or request.GET.get("username") or "")[:100]
    next_url = _safe_next(request)
    if request.method == "POST":
        try:
            claim = link_claims.start(request, name, add=adding)
        except link_claims.ClaimProblem as problem:
            messages.error(request, problem.message)
        else:
            url = reverse("accounts:friend_request_wait", args=[claim.pk])
            return redirect(f"{url}?next={next_url}" if next_url else url)
    return render(
        request,
        "accounts/friend_request_login.html",
        {
            "adding": adding,
            "username": name,
            "bot_name": bot_account.bot_name(),
            "available": bot_account.configured(),
            "next": next_url,
        },
    )


@limit("browse")
def friend_request_wait(request, claim_id):
    """The waiting page: send the friend request now; the page checks."""
    try:
        state = link_claims.status(request, claim_id)
    except link_claims.ClaimProblem as problem:
        messages.error(request, problem.message)
        return redirect("accounts:friend_request_login")
    if state["status"] == "done":
        return redirect(_safe_next(request) or reverse("players:profile_settings"))
    claim_name = link_claims.claimed_name(claim_id)
    return render(
        request,
        "accounts/friend_request_wait.html",
        {
            "claim_id": claim_id,
            "state": state,
            "name": claim_name,
            "bot_name": bot_account.bot_name(),
            "next": _safe_next(request),
        },
    )


@require_POST
@limit("browse")
def friend_request_status(request, claim_id):
    """The waiting page's check (every few seconds): pending, done (now
    signed in, or the account added), expired or refused."""
    try:
        state = link_claims.status(request, claim_id)
    except link_claims.ClaimProblem as problem:
        return JsonResponse({"status": "refused", "message": problem.message}, status=403)
    if state["status"] == "done":
        state["redirect"] = _safe_next(request) or reverse("players:profile_settings")
    return JsonResponse(state)


def _safe_next(request) -> str:
    """`next` from the query or form when it points at this site, else ""."""
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return ""


@login_required
@require_POST
@limit("write")
def switch_account(request):
    """The account menu's switch: use another account signed in here."""
    try:
        user = groups.switch(request, _account_id(request.POST.get("account")))
    except groups.NotAllowed as refusal:
        messages.error(request, refusal.message)
    else:
        messages.success(request, f"You're now using {user.username}.")
    return redirect(_back(request))


@login_required
@require_POST
@limit("write")
def remove_account(request):
    """Settings: take an account out of the group (it keeps its own history)."""
    account_id = _account_id(request.POST.get("account"))
    name = next(
        (row["username"] for row in groups.accounts_for(request) if row["id"] == account_id), ""
    )
    try:
        groups.remove(request, account_id)
    except groups.NotAllowed as refusal:
        messages.error(request, refusal.message)
    else:
        messages.success(
            request,
            f"Removed {name} from your accounts. Its favorites, votes and uploads stay with it.",
        )
    return redirect(_back(request))


@login_required
@require_POST
@limit("write")
def make_main_account(request):
    """Settings: make another account the group's main."""
    account_id = _account_id(request.POST.get("account"))
    try:
        groups.make_main(request, account_id)
    except groups.NotAllowed as refusal:
        messages.error(request, refusal.message)
    else:
        messages.success(request, "Main account changed.")
    return redirect(_back(request))


@login_required
@require_POST
@limit("write")
def show_on_profiles_view(request):
    """Settings: turn "Also plays as…" on (show=1) or off for the group."""
    show = request.POST.get("show") == "1"
    try:
        groups.show_on_profiles(request, show)
    except groups.NotAllowed as refusal:
        messages.error(request, refusal.message)
    else:
        messages.success(
            request,
            "Your profiles now list your other accounts."
            if show
            else "Your profiles no longer list your other accounts.",
        )
    return redirect(_back(request))


@login_required
@require_POST
@limit("write")
def remove_trusted_browser(request):
    """Settings: stop trusting one of the group's browsers."""
    try:
        groups.remove_browser(request, _account_id(request.POST.get("device")))
    except groups.NotAllowed as refusal:
        messages.error(request, refusal.message)
    else:
        messages.success(request, "That browser is no longer trusted.")
    return redirect(_back(request))


@login_required
@require_POST
@limit("write")
def remove_one_click_browser(request):
    """Settings: stop one-click sign-in for the account in use on one
    browser (ADR 0025)."""
    if devices.remove_remembered(request.user, _account_id(request.POST.get("browser"))):
        messages.success(request, "That browser will ask you to sign in again.")
    else:
        messages.error(request, "That browser isn't on the list.")
    return redirect(_back(request))


@login_required
@require_POST
@limit("write")
def add_used_here(request):
    """Add the ticked accounts used on this browser to your accounts, after
    "These accounts are mine" (used_here.py, ADR 0025)."""
    if request.POST.get("confirm") != "on":
        messages.error(request, "Tick \u201cThese accounts are mine\u201d to add them.")
        return redirect(_back(request))
    ids = [_account_id(value) for value in request.POST.getlist("account")]
    try:
        added = used_here.add(request, ids)
    except groups.NotAllowed as refusal:
        messages.error(request, refusal.message)
    else:
        names = ", ".join(account.username for account in added)
        messages.success(request, f"Added {names}. Switch between them from the account menu.")
    return redirect(_back(request))


def _account_id(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _back(request) -> str:
    """Where an account action returns to: `next` on this site, else the
    accounts list in settings."""
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return reverse("players:profile_settings") + "#accounts"


@limit("browse")
def me(request):
    """Who is signed in, for the skin editor and the shared header on the
    replay and docs sites (401 when nobody is). `avatar` is the absolute URL
    of their worn skin's thumbnail, the picture bonkverse.io's own header
    shows, or null before a skin has been seen."""
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)

    return JsonResponse(_me_body(request))


def _me_body(request) -> dict:
    """/api/me/'s answer for a signed-in visitor. `accounts` lists the
    person's bonk.io accounts for the shared header's switcher (RFC-0003
    phase 5): every account in the group, which is in use, which is the
    main, which are signed in on this browser (only those can be switched to
    without a password), which Wear can act as, and each one's picture (its
    worn skin, as the header shows it; null when there's none)."""
    thumbnail = player_selectors.user_skin_avatars(request.user).get("thumbnail")
    return {
        "authenticated": True,
        "user": {
            "id": request.user.id,
            "username": request.user.username,
            "avatar": request.build_absolute_uri(thumbnail) if thumbnail else None,
            "appearance": appearance.for_api(request.user),
        },
        "accounts": _with_avatars(request, groups.accounts_for(request)),
        "permissions": {
            "publish_skins": True,
        },
    }


def _with_avatars(request, rows: list[dict]) -> list[dict]:
    """Each account row with `avatar`: an absolute URL of its worn-skin
    thumbnail (cached per account), so the other sites' switchers can show
    it as bonkverse.io's header does. One account: no extra queries."""
    if len(rows) < 2:
        own = rows[0] if rows else None
        if own is not None:
            thumbnail = player_selectors.user_skin_avatars(request.user).get("thumbnail")
            own["avatar"] = request.build_absolute_uri(thumbnail) if thumbnail else None
        return rows
    by_id = {account.pk: account for account in groups.members(request.user)}
    for row in rows:
        account = by_id.get(row["id"])
        thumbnail = (
            player_selectors.user_skin_avatars(account).get("thumbnail") if account else None
        )
        row["avatar"] = request.build_absolute_uri(thumbnail) if thumbnail else None
    return rows


# The header on Bonkverse's other sites switches through this. They can't
# send bonkverse.io's CSRF token (it's host-only), so instead: a JSON body
# and a custom header, which a browser only sends cross-origin after a CORS
# preflight that only our own origins pass (CORS_ALLOWED_ORIGINS), and the
# Origin checked again here.
SWITCH_HEADER = "X-Bonkverse-Switch"


@csrf_exempt
@require_POST
@limit("write")
def api_switch_account(request):
    """POST {"account": id} with the X-Bonkverse-Switch header: use another
    account signed in on this browser. Answers like /api/me/."""
    if not request.headers.get(SWITCH_HEADER):
        return JsonResponse({"ok": False, "error": "missing_header"}, status=400)
    origin = request.headers.get("Origin")
    if origin and origin not in _own_origins(request):
        return JsonResponse({"ok": False, "error": "bad_origin"}, status=403)
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=401)
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        body = {}
    try:
        groups.switch(request, _account_id(body.get("account")))
    except groups.NotAllowed as refusal:
        return JsonResponse(
            {"ok": False, "error": "not_allowed", "message": refusal.message}, status=403
        )
    return JsonResponse({"ok": True, **_me_body(request)})


def _own_origins(request) -> set[str]:
    return set(settings.CORS_ALLOWED_ORIGINS) | {f"{request.scheme}://{request.get_host()}"}
