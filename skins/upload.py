"""The upload form: adding a skin from a BonkLeagues short link.

Owns: the /upload/ page, the form's own rules (required fields, which name
characters are allowed, the short-link format) and the messages people see.
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
from skins.events import log_event
from skins.skin_import import NAME_MAX_LENGTH, ImportFailure, import_bonkleagues_skin
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

    if not skin_name or not bonkleagues_link:
        messages.error(request, "All fields are required.")
        return render(request, TEMPLATE)

    if not re.match(skin_name_pattern, skin_name):
        messages.error(
            request, "Skin name can only contain letters, numbers, spaces, and underscores."
        )
        return render(request, TEMPLATE)

    if len(skin_name) > NAME_MAX_LENGTH:
        messages.error(request, f"Skin name must be under {NAME_MAX_LENGTH} characters.")
        return render(request, TEMPLATE)

    if not re.match(bonk_url_pattern, bonkleagues_link):
        messages.error(request, "Invalid Bonkleagues link format.")
        return render(request, TEMPLATE)

    result = import_bonkleagues_skin(bonkleagues_link, skin_name, request.user.username)

    if result.error:
        logger.warning(
            "upload failed | error=%s | detail=%s | link=%s",
            result.error,
            result.detail,
            bonkleagues_link,
        )
        messages.error(request, FAILURE_MESSAGES.get(result.error, FALLBACK_MESSAGE))
        return render(request, TEMPLATE)

    if not result.created:
        messages.error(request, "This Bonkleagues link has already been submitted!")
        return redirect("upload_skin")

    messages.success(request, "Skin uploaded successfully!")
    log_event(request.user, "skin_uploaded", skin=result.skin, source="bonkleagues")
    return redirect(reverse("search_skins") + "?" + urlencode({"q": result.skin.name}))
