"""Home, privacy, terms and the staff page.

Owns: what these pages show. Does not own: the skins on the home page
(`skins.selectors.home_strips`).
"""

from django.shortcuts import render

from core.ratelimits import limit
from skins.selectors import home_strips

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
        "bio": "Co-owner of Bonkverse.io and hosts many of our community events and tournaments. I love food and here are my skins 🫂  https://bonkverse.io/search/?q=ButteredToast55&mode=creator&sort=newest&tz_offset=240",
        "image": "images/bt55.png",
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
    return render(request, "site_pages/home.html", home_strips())


@limit("browse")
def privacy(request):
    return render(request, "site_pages/privacy.html")


@limit("browse")
def terms(request):
    return render(request, "site_pages/terms.html")


@limit("browse")
def staff_page(request):
    return render(request, "site_pages/staff.html", {"staff_members": STAFF_MEMBERS})
