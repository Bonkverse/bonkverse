from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseRedirect
from django.urls import reverse
from .models import Skin
from django.db.models import Count
from django.core.paginator import Paginator
import json
from django.contrib import messages
from django_ratelimit.decorators import ratelimit


@login_required
@ratelimit(key="ip", rate="10/m", block=True)
def my_profile(request):
    user       = request.user
    user_skins = Skin.objects.filter(creator__iexact=user.username).order_by("name")
    favorites  = user.favorite_skins.all().order_by("-created_at")

    paginator   = Paginator(user_skins, 20)
    page_number = request.GET.get("page", 1)
    page_obj    = paginator.get_page(page_number)

    # ── Bulk-fetch favorite counts for both lists ─────────────────
    #
    # my_profile.html was calling skin.favorited_by.count() per card —
    # one query per skin. With 20 uploaded skins + N favorites that's
    # 20 + N extra queries. We fetch all counts in 2 queries instead.

    uploaded_ids  = [s.id for s in page_obj]
    favorite_list = list(favorites)
    favorite_ids  = [s.id for s in favorite_list]

    all_ids       = list(set(uploaded_ids + favorite_ids))
    fav_counts    = {
        row["id"]: row["fav_count"]
        for row in (
            Skin.objects
            .filter(id__in=all_ids)
            .annotate(fav_count=Count("favorited_by"))
            .values("id", "fav_count")
        )
    }

    # Attach pre-computed count to each skin object so the template
    # can use skin.fav_count_val instead of skin.favorited_by.count
    for skin in page_obj:
        skin.fav_count_val = fav_counts.get(skin.id, 0)

    for skin in favorite_list:
        skin.fav_count_val = fav_counts.get(skin.id, 0)

    return render(request, "skins/my_profile.html", {
        "skins":         page_obj,
        "favorites":     favorite_list,
        "user":          user,
    })


@login_required
@ratelimit(key="ip", rate="10/m", block=True)
def delete_skin(request, skin_id):
    skin = get_object_or_404(Skin, id=skin_id)
    if skin.creator == request.user.username:
        skin.delete()
    return redirect("my_profile")


@login_required
@ratelimit(key="ip", rate="10/m", block=True)
def edit_skin(request, skin_id):
    skin = get_object_or_404(Skin, id=skin_id)

    if skin.creator != request.user.username:
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
            messages.error(request, "❌ Failed to parse tags JSON.")
            referer = request.POST.get("referer") or request.META.get("HTTP_REFERER") or reverse("my_profile")
            return render(request, "skins/edit_skin.html", {"skin": skin, "referer": referer})

        skin.save()
        messages.success(request, "✅ Skin updated successfully!")
        return redirect("skin_detail", skin_id=skin.id)

    referer = request.META.get("HTTP_REFERER", reverse("my_profile"))
    return render(request, "skins/edit_skin.html", {"skin": skin, "referer": referer})