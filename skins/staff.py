from django.shortcuts import render

from django_ratelimit.decorators import ratelimit

@ratelimit(key="ip", rate="5/m", block=True)
def staff_page(request):
    staff_members = [
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
            "bio": '''The most og staff that still hasn't been promoted 🔥, and brazilian staph, creator of boykisser skin, pixel artist and photographer (not profissional), and person who makes the server's designs! And kids, always remember, Uncle Saucy needs you in our community! I also make skins btw.''',
            "image": "images/zorroloko.png",
        },
        {
            "name": "Green Ball",
            "role": "Moderator & Lore Writer",
            "bio": "Co-conspirator of the fall of Bonktown",
            "image": "images/greenball.png",
        },
        # add more staff members here
    ]
    return render(request, "skins/staff.html", {"staff_members": staff_members})
