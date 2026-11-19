"""Home, privacy, terms and the staff page.

Owns: what these pages show. Does not own: the home page's data
(`site_pages.selectors.home`).
"""

from django.shortcuts import render

from core.ratelimits import limit
from players.charts import profile_path
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
    members = [
        {
            **m,
            "profile_url": profile_path(m["player"]) if m.get("player") else None,
            "skins_url": profile_path(m["player"], "skins") if m.get("player") else None,
        }
        for m in STAFF_MEMBERS
    ]
    return render(request, "site_pages/staff.html", {"staff_members": members})
