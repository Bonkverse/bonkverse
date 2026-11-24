"""The /login/ form: a bonk.io username and password, never stripped (bonk.io
names can start or end with spaces)."""

from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(
        label="bonk.io username",
        max_length=100,
        strip=False,
        widget=forms.TextInput(attrs={"class": "bv-input", "autocomplete": "username"}),
    )
    password = forms.CharField(
        label="bonk.io password",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "bv-input", "autocomplete": "current-password"}),
    )
    # "Keep me connected for Wear": ask bonk.io for a remember-me token
    # (RFC-0003 Part 2). Ticked by default; the page says what it stores.
    # Rendered by hand in login.html, so the field loop skips it.
    remember = forms.BooleanField(required=False, initial=True)
