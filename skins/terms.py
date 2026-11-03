from django.shortcuts import render
from core.ratelimits import limit


@limit("browse")
def terms(request):
    return render(request, "skins/terms.html")
