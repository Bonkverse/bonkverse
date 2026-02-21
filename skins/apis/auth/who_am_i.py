# skins/apis/auth/who_am_i.py

from django.http import JsonResponse

def me(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"authenticated": False},
            status=401
        )

    return JsonResponse({
        "authenticated": True,
        "user": {
            "id": request.user.id,
            "username": request.user.username,
        },
        "permissions": {
            "publish_skins": True,
        },
    })
