from django.shortcuts import render

def skin_editor(request):
    return render(request, 'skins/editor.html')
