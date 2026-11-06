from django.contrib.auth.decorators import login_required
from core.ratelimits import limit
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.urls import reverse
from .models import Skin
from django.db.models import Sum
from django.core.paginator import Paginator
import json
from django.contrib import messages
from .pagination_utils import elided_page_range
from .selectors import decorate_skins_for_user


def _add_edit_labels(skins):
    """Pre-serialize labels so the "Edit Skin" menu item can carry them as a
    data attribute (the template can't JSON-encode a dict itself)."""
    for skin in skins:
        skin.labels_json = json.dumps(skin.labels or {})


@login_required
@limit("browse")
def my_profile(request):
    user = request.user
    user_skins = Skin.objects.filter(creator__iexact=user.username).order_by("name")
    favorites = user.favorite_skins.all().order_by("-created_at")

    paginator = Paginator(user_skins, 20)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # Favorite counts for every card on the page in one query. The cards
    # here don't show the visitor's own vote or favorite state, so no user.
    favorite_list = list(favorites)
    decorate_skins_for_user([*page_obj, *favorite_list])
    _add_edit_labels(page_obj)

    # ── Profile header stats ───────────────────────────────────────
    # One aggregate query — total upvotes across every skin this user
    # created. Nothing else here needs a new query: skin/favorite
    # counts below reuse objects we already built above.
    total_upvotes = (
        Skin.objects.filter(creator__iexact=user.username).aggregate(total=Sum("upvotes"))["total"]
        or 0
    )

    # Popped (not just read) so the toast only fires once, right after
    # the login redirect that set it — not on every subsequent profile
    # page load or refresh.
    show_friend_sync_toast = request.session.pop("show_friend_sync_toast", False)

    return render(
        request,
        "skins/my_profile.html",
        {
            "skins": page_obj,
            "favorites": favorite_list,
            "user": user,
            "show_friend_sync_toast": show_friend_sync_toast,
            "total_skins": paginator.count,
            "total_favorites": len(favorite_list),
            "total_upvotes": total_upvotes,
            "base_qs": "",
            "elided_range": elided_page_range(page_obj),
        },
    )


@login_required
@limit("browse")
def my_skins_partial(request):
    """
    Returns just the My Skins card grid + pagination for a given page.
    Powers instant (no full-page-reload) pagination on the My Skins tab,
    so a multi-select in progress survives paging instead of being wiped
    by navigation — see the "Go to page N" flow in my_profile.html.
    """
    user = request.user
    user_skins = Skin.objects.filter(creator__iexact=user.username).order_by("name")

    paginator = Paginator(user_skins, 20)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    decorate_skins_for_user(page_obj)
    _add_edit_labels(page_obj)

    return render(
        request,
        "skins/partials/_my_skins_cards.html",
        {
            "skins": page_obj,
            "elided_range": elided_page_range(page_obj),
            "base_qs": "",
        },
    )


@login_required
@limit("write")
def delete_skin(request, skin_id):
    skin = get_object_or_404(Skin, id=skin_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if skin.creator != request.user.username:
        if is_ajax:
            return JsonResponse({"ok": False, "error": "You don't own this skin."}, status=403)
        return redirect("my_profile")

    skin.delete()

    if is_ajax:
        return JsonResponse({"ok": True, "deleted_ids": [skin_id]})
    return redirect("my_profile")


@login_required
@limit("write")
def bulk_delete_skins(request):
    """
    Deletes multiple skins owned by the current user in one request.
    Powers the multi-select "Delete N skins" flow on my_profile — this
    is the only path that flow uses; there is no non-JS fallback since
    multi-select is inherently a JS-driven interaction.
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required."}, status=405)

    raw_ids = request.POST.getlist("skin_ids")
    try:
        ids = [int(i) for i in raw_ids]
    except ValueError:
        return JsonResponse({"ok": False, "error": "Invalid skin id."}, status=400)

    if not ids:
        return JsonResponse({"ok": False, "error": "No skins selected."}, status=400)

    # Scope strictly to skins this user owns — a spoofed id list can
    # only ever delete the subset the requester actually created.
    owned_qs = Skin.objects.filter(id__in=ids, creator__iexact=request.user.username)
    deleted_ids = list(owned_qs.values_list("id", flat=True))
    owned_qs.delete()

    return JsonResponse({"ok": True, "deleted_ids": deleted_ids})


@login_required
@limit("write")
def edit_skin(request, skin_id):
    skin = get_object_or_404(Skin, id=skin_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if skin.creator != request.user.username:
        if is_ajax:
            return JsonResponse({"ok": False, "error": "You don't own this skin."}, status=403)
        return redirect("my_profile")

    if request.method == "POST":
        new_name = request.POST.get("name", "").strip()
        if new_name:
            skin.name = new_name

        new_description = request.POST.get("description", "").strip()
        skin.description = new_description if new_description else None

        raw_labels = request.POST.get("labels")
        try:
            skin.labels = json.loads(raw_labels) if raw_labels else None
        except json.JSONDecodeError:
            if is_ajax:
                return JsonResponse({"ok": False, "error": "Failed to parse tags."}, status=400)
            messages.error(request, "❌ Failed to parse tags JSON.")
            referer = (
                request.POST.get("referer")
                or request.META.get("HTTP_REFERER")
                or reverse("my_profile")
            )
            return render(request, "skins/edit_skin.html", {"skin": skin, "referer": referer})

        skin.save()

        if is_ajax:
            return JsonResponse(
                {
                    "ok": True,
                    "skin": {
                        "id": skin.id,
                        "name": skin.name,
                        "description": skin.description or "",
                        "labels": skin.labels or {},
                    },
                }
            )

        messages.success(request, "✅ Skin updated successfully!")
        return redirect("skin_detail", skin_id=skin.id)

    if is_ajax:
        return JsonResponse({"ok": False, "error": "GET not supported here."}, status=400)

    referer = request.META.get("HTTP_REFERER", reverse("my_profile"))
    return render(request, "skins/edit_skin.html", {"skin": skin, "referer": referer})
