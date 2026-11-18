"""The upload form: adding a skin from a BonkLeagues short link.

Owns: the /upload/ page, the form's own rules (required fields, which name
characters are allowed, the short-link format), asking "Did you make this
skin?" when BonkLeagues credits someone else, and the messages people see.
Does not own: fetching, checking and storing the skin. That is
skins/skin_import.py, shared with BonxBot submissions, which also matches a
link already on the site in any spelling.
"""

import logging
import re
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from core.ratelimits import limit
from accounts.services import log_event
from skins.models import CreatorSource, SubmissionSource
from skins.skin_import import (
    NAME_MAX_LENGTH,
    ImportFailure,
    existing_skin,
    fetch_skin_cached,
    import_bonkleagues_skin,
)
from skins.submitters import Submission, resolve_creator
from skins.svg_sanitizer import TOO_LARGE_MESSAGE

logger = logging.getLogger(__name__)

bonk_url_pattern = r"^https://bonkleagues\.io/s/([A-Za-z0-9]{7})$"
skin_name_pattern = r"^[A-Za-z0-9_ ]+$"

TEMPLATE = "skins/upload.html"

# What people see when an import fails, by ImportFailure code. Details stay
# in the server log.
FAILURE_MESSAGES = {
    ImportFailure.FETCH_FAILED: (
        "Couldn't get that skin from BonkLeagues right now. "
        "Check the link opens on BonkLeagues, then try again in a minute."
    ),
    ImportFailure.SVG_TOO_LARGE: TOO_LARGE_MESSAGE,
    ImportFailure.UNSAFE_SVG: "This skin's image failed our SVG safety check, so it wasn't added.",
    ImportFailure.STORAGE_FAILED: "Something went wrong saving the skin. Please try again.",
    ImportFailure.INVALID_LINK: "Invalid Bonkleagues link format.",
    ImportFailure.LINK_TOO_LONG: "Invalid Bonkleagues link format.",
}
FALLBACK_MESSAGE = "Couldn't add that skin. Please try again."


@login_required(login_url="/login/")
@limit("upload")
def upload_skin(request):
    if request.method != "POST":
        return render(request, TEMPLATE)

    skin_name = request.POST.get("skin_name", "").strip()
    bonkleagues_link = request.POST.get("bonkleagues_link", "").strip()
    problem = _form_problem(skin_name, bonkleagues_link)
    if problem:
        messages.error(request, problem)
        return render(request, TEMPLATE)

    if existing_skin(bonkleagues_link):
        return _already_submitted(request)

    fetched = fetch_skin_cached(bonkleagues_link)
    if fetched.error:
        return _failed(request, ImportFailure.FETCH_FAILED, fetched.error, bonkleagues_link)

    author = fetched.skin.author
    choice = resolve_creator(request.user.username, author, _made_it(request.POST))
    if choice is None:
        # BonkLeagues credits someone else: ask before crediting anyone.
        check = {"author": author, "skin_name": skin_name, "link": bonkleagues_link}
        return render(request, TEMPLATE, {"creator_check": check})

    result = import_bonkleagues_skin(
        bonkleagues_link,
        skin_name,
        choice.creator,
        submission=Submission(SubmissionSource.WEBSITE, choice.source, user=request.user),
        fetch=fetch_skin_cached,
    )
    if result.error:
        return _failed(request, result.error, result.detail, bonkleagues_link)
    if not result.created:
        return _already_submitted(request)

    messages.success(request, _success_message(choice))
    log_event(request.user, "skin_uploaded", skin=result.skin, source="bonkleagues")
    return redirect(reverse("skins:search_skins") + "?" + urlencode({"q": result.skin.name}))


def _form_problem(skin_name: str, link: str) -> str | None:
    """What's wrong with the form, in words for the uploader, or None."""
    if not skin_name or not link:
        return "All fields are required."
    if not re.match(skin_name_pattern, skin_name):
        return "Skin name can only contain letters, numbers, spaces, and underscores."
    if len(skin_name) > NAME_MAX_LENGTH:
        return f"Skin name must be under {NAME_MAX_LENGTH} characters."
    if not re.match(bonk_url_pattern, link):
        return "Invalid Bonkleagues link format."
    return None


def _made_it(post) -> bool | None:
    """The uploader's answer to "Did you make this skin?", or None if not asked yet."""
    return {"yes": True, "no": False}.get(post.get("made_it"))


def _success_message(choice) -> str:
    if choice.source == CreatorSource.BONKLEAGUES:
        return (
            f"Skin uploaded! It's credited to {choice.creator}, and you're listed as the uploader."
        )
    return "Skin uploaded successfully!"


def _already_submitted(request):
    messages.error(request, "This Bonkleagues link has already been submitted!")
    return redirect("skins:upload_skin")


def _failed(request, error: str, detail: str, link: str):
    logger.warning("upload failed | error=%s | detail=%s | link=%s", error, detail, link)
    messages.error(request, FAILURE_MESSAGES.get(error, FALLBACK_MESSAGE))
    return render(request, TEMPLATE)
