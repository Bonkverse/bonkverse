# # skins/views.py

# from django.shortcuts import render, redirect
# from django.contrib.auth import login, logout
# from .models import BonkUser
# from .forms import LoginForm
# import requests
# from django.contrib import messages

# def login_view(request):
#     if request.method == 'POST':
#         form = LoginForm(request.POST)
#         if form.is_valid():
#             username = form.cleaned_data['username']
#             password = form.cleaned_data['password']

#             # Send credentials to Bonk.io login API
#             response = requests.post("https://bonk2.io/scripts/login_legacy.php", data={
#                 "username": username,
#                 "password": password
#             })

#             if "success" in response.text.lower():
#                 user, created = BonkUser.objects.get_or_create(username=username)
#                 login(request, user)
#                 messages.success(request, "Logged in successfully!")
#                 return redirect('my_profile')  # You'll build this view next
#             else:
#                 messages.error(request, "Bonk.io login failed. Check your credentials.")
#     else:
#         form = LoginForm()

#     return render(request, 'skins/login.html', {'form': form})

# def logout_view(request):
#     logout(request)
#     messages.success(request, "Logged out!")
#     return redirect('home')

# skins/login.py

from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib import messages
from .models import BonkUser
from .forms import LoginForm
from ratelimit.decorators import ratelimit

import json
import requests
from requests.exceptions import RequestException, JSONDecodeError

BONK_LOGIN_URL = "https://bonk2.io/scripts/login_legacy.php"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    ),
    "Origin": "https://bonk.io",
    "Referer": "https://bonk.io/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username'].strip()
            password = form.cleaned_data['password']

            s = requests.Session()
            try:
                resp = s.post(
                    BONK_LOGIN_URL,
                    data={"username": username, "password": password},
                    headers=BROWSER_HEADERS,
                    timeout=12,
                )
            except RequestException as e:
                messages.error(request, f"Network error talking to Bonk.io: {e}")
                return render(request, 'skins/login.html', {'form': form})

            # Try JSON first
            data = None
            try:
                data = resp.json()
            except JSONDecodeError:
                # Log a hint server-side so you can see Cloudflare/HTML
                snippet = resp.text[:400].replace("\n", " ")
                print(f"[bonkverse] Non-JSON login response ({resp.status_code}): {snippet}")

            if data and data.get("r") == "success" and data.get("token"):
                # Optionally store token if you’ll use it later
                request.session["bonk_token"] = data["token"]
                request.session["bonk_username"] = data.get("username", username)
                request.session["bonk_user_id"] = data.get("id")

                user, _ = BonkUser.objects.get_or_create(username=username)
                login(request, user)
                messages.success(request, "Logged in successfully!")
                return redirect('my_profile')
            else:
                # More helpful error message
                detail = (data or {}).get("r") or (data or {}).get("error") or "unknown error"
                messages.error(request, f"Bonk.io login failed: {detail}. Check your credentials.")

    else:
        form = LoginForm()

    return render(request, 'skins/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.success(request, "Logged out!")
    return redirect('home')
