# skins/api.py
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
from datetime import timedelta
from django_ratelimit.decorators import ratelimit
import json, secrets, requests
from django.core.exceptions import ValidationError

def add_cors_headers(response):
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

@csrf_exempt
@ratelimit(key="ip", rate="5/m", block=True)
def index(request):
    message = "This is the Bonkverse.io API!"
    return render(request, "skins/apis/index.html", {"message": message})