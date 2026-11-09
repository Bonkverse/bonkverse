# skins/forms.py

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
