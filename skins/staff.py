from django.shortcuts import render

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
            "name": "Black_Queen",
            "role": "Lore Maker & Chaos Engineer",
            "bio": "Hi hi! I'm Black Queen, lead Bonkverse lore maker and chaos engineer <3",
            "image": "images/bq.png",
        },
        {
            "name": "Zorroloko CRZ",
            "role": "Moderator & Furry Specialist",
            "bio": "I'm the furriest of all staphs :) (brazilian soccer phonk rahhh)",
            "image": "images/zorroloko.png",
        },
        {
            "name": "Lolmsana",
            "role": "Moderator & Map Maker",
            "bio": "Listening to twenty øne piløts",
            "image": "images/lolmsana.png",
        },
        {
            "name": "Green Ball",
            "role": "Moderator & Lore Designer",
            "bio": "Co-conspirator of the fall of Bonktown",
            "image": "images/greenball.png",
        },
        {
            "name": "Madslolll",
            "role": "Moderator & Minecraft Conoisseur",
            "bio": "I couldn't think of a bio so I made Saucy make one for me :/",
            "image": "images/maddy.png",
        },
        # add more staff members here
    ]
    return render(request, "skins/staff.html", {"staff_members": staff_members})
