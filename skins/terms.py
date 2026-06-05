from django.shortcuts import render

def terms(request):
    return render(request, "skins/terms.html")