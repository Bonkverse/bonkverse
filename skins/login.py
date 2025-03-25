# skins/views.py

from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from .models import BonkUser
from .forms import LoginForm
import requests
from django.contrib import messages

def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']

            # Send credentials to Bonk.io login API
            response = requests.post("https://bonk2.io/scripts/login_legacy.php", data={
                "username": username,
                "password": password
            })

            if "success" in response.text.lower():
                user, created = BonkUser.objects.get_or_create(username=username)
                login(request, user)
                messages.success(request, "Logged in successfully!")
                return redirect('my_profile')  # You'll build this view next
            else:
                messages.error(request, "Bonk.io login failed. Check your credentials.")
    else:
        form = LoginForm()

    return render(request, 'skins/login.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.success(request, "Logged out!")
    return redirect('home')
