# in any views file, e.g. skins/views.py or a new skins/privacy.py
from django.shortcuts import render

def privacy(request):
    return render(request, "skins/privacy.html")