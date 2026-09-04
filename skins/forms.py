# skins/forms.py

from django import forms
class LoginForm(forms.Form):
    username = forms.CharField(label="Bonk.io Username", max_length=100, strip=False)
    password = forms.CharField(label="Bonk.io Password", widget=forms.PasswordInput, strip=False)
