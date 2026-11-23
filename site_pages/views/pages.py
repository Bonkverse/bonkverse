"""Home, privacy, terms and the staff page.

Owns: what these pages show. Does not own: the home page's data
(`site_pages.selectors.home`).
"""

from django.conf import settings
from django.shortcuts import redirect, render

from core.ratelimits import limit
from site_pages import selectors

# The team page (site_pages/staff.html). "player" is their bonk.io name: the
# card links to their profile and their skins (design review: no raw search
# URLs in bios). Leave it out when we don't know it.
STAFF_MEMBERS = [
    {
        "name": "The Saucy Tulip",
        "role": "Owner & Developer",
        "bio": "Yerrrr. Hi all! I'm the creator of Bonkverse.io and owner of the Bonkverse Discord. I like to build cool stuff for the Bonk.io community.",
        "image": "images/saucy.png",
    },
    {
        "name": "ButteredToast55",
        "role": "Co-Owner & Events Manager",
        "bio": "Co-owner of Bonkverse.io and hosts many of our community events and tournaments. I love food 🫂",
        "image": "images/bt55.png",
        "player": "ButteredToast55",
    },
    {
        "name": "Zorroloko CRZ",
        "role": "Moderator & Furry Specialist",
        "bio": """The most og staff that still hasn't been promoted 🔥, and brazilian staph, creator of boykisser skin, pixel artist and photographer (not profissional), and person who makes the server's designs! And kids, always remember, Uncle Saucy needs you in our community! I also make skins btw.""",
        "image": "images/zorroloko.png",
    },
    {
        "name": "Green Ball",
        "role": "Moderator & Lore Writer",
        "bio": "Co-conspirator of the fall of Bonktown",
        "image": "images/greenball.png",
    },
]


@limit("browse")
def home(request):
    return render(request, "site_pages/home.html", selectors.home())


@limit("browse")
def privacy(request):
    return render(request, "site_pages/privacy.html")


@limit("browse")
def terms(request):
    return render(request, "site_pages/terms.html")


@limit("browse")
def staff_page(request):
    return render(request, "site_pages/staff.html", {"staff_members": STAFF_MEMBERS})


@limit("browse")
def ui_gallery(request):
    """/ui/: the Bonkverse/ui component gallery, synced with the package
    (scripts/sync_ui.py). Its unhashed static path, because the gallery
    loads its own files by relative URL."""
    return redirect(f"{settings.STATIC_URL}ui/index.html")
