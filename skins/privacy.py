# in any views file, e.g. skins/views.py or a new skins/privacy.py
from django.shortcuts import render
from core.ratelimits import limit


@limit("browse")
def privacy(request):
    return render(request, "skins/privacy.html")
