from django.shortcuts import render
import requests
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def join_matchmaking(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            response = requests.post('https://bonkbot-api-production.up.railway.app/join-matchmaking', json=data)

            return JsonResponse(response.json(), status=response.status_code)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


def matchmaking_page(request):
    return render(request, 'skins/matchmaking.html')