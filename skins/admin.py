"""Django admin: skins, and the admin site's login.

Admins sign in through the normal bonk.io login, not the admin's own password
form (site accounts have no usable password). /admin/login/ therefore
redirects to /login/ and comes back to the admin afterwards.
"""

from urllib.parse import urlencode

from django import forms
from django.contrib import admin
from django.shortcuts import redirect, render
from django.utils.html import format_html
from django.urls import reverse

from .categories import CATEGORIES
from .models import CategoryCover, Skin, SkinReport


def _login_through_bonk(request, extra_context=None):
    """Replace the admin login form with the site's bonk.io login."""
    next_url = request.GET.get("next") or reverse("admin:index")
    if request.user.is_authenticated and request.user.is_staff:
        return redirect(next_url)
    return redirect(f"{reverse('accounts:login')}?{urlencode({'next': next_url})}")


admin.site.login = _login_through_bonk
admin.site.site_header = "Bonkverse admin"
admin.site.site_title = "Bonkverse admin"


class BulkUpdateCreatorForm(forms.Form):
    _selected_action = forms.CharField(widget=forms.MultipleHiddenInput)
    new_creator = forms.CharField(label="New Creator Name", max_length=255)


@admin.action(description="Update creator to specified name")
def bulk_update_creator(modeladmin, request, queryset):
    if "apply" in request.POST:
        form = BulkUpdateCreatorForm(request.POST)
        if form.is_valid():
            new_creator = form.cleaned_data["new_creator"]
            count = queryset.update(creator=new_creator)
            modeladmin.message_user(request, f"Updated {count} skins.")
            return None
    else:
        form = BulkUpdateCreatorForm(
            initial={"_selected_action": request.POST.getlist(admin.ACTION_CHECKBOX_NAME)}
        )

    return render(
        request,
        "admin/bulk_update_creator.html",
        {
            "skins": queryset,
            "form": form,
            "title": "Update Creator Name",
            "action": "bulk_update_creator",
        },
    )


def skin_image(skin, size=48):
    """A skin's image, linked to its page, for admin lists and forms."""
    if skin is None or not skin.image_url:
        return "-"
    return format_html(
        '<a href="{}" target="_blank" rel="noopener"><img src="{}" alt="" width="{}" '
        'height="{}" loading="lazy"></a>',
        skin.get_absolute_url(),
        skin.image_url,
        size,
        size,
    )


@admin.register(Skin)
class SkinAdmin(admin.ModelAdmin):
    actions = [bulk_update_creator]
    list_display = ["image", "name", "creator", "created_at"]
    list_display_links = ["name"]
    search_fields = ["name", "creator"]
    readonly_fields = ["preview"]

    @admin.display(description="Image")
    def image(self, obj):
        return skin_image(obj)

    @admin.display(description="Preview")
    def preview(self, obj):
        return skin_image(obj, 160)


class CategoryCoverForm(forms.ModelForm):
    category = forms.ChoiceField(
        choices=[(slug, meta["label"]) for slug, meta in CATEGORIES.items()]
    )

    class Meta:
        model = CategoryCover
        fields = ["category", "skin"]


@admin.register(CategoryCover)
class CategoryCoverAdmin(admin.ModelAdmin):
    """Pick each category's cover on /categories/ (one skin per category)."""

    form = CategoryCoverForm
    list_display = ["image", "category", "skin", "updated_at"]
    list_display_links = ["category"]
    list_select_related = ["skin"]
    raw_id_fields = ["skin"]
    readonly_fields = ["preview"]

    @admin.display(description="Cover")
    def image(self, obj):
        return skin_image(obj.skin)

    @admin.display(description="Preview")
    def preview(self, obj):
        return skin_image(obj.skin, 160)


@admin.action(description="Mark as resolved (the skin shows in featured places again)")
def resolve_reports(modeladmin, request, queryset):
    count = queryset.update(resolved=True)
    modeladmin.message_user(request, f"Resolved {count} reports.")


@admin.register(SkinReport)
class SkinReportAdmin(admin.ModelAdmin):
    """Open reports hide a skin from category covers, the home carousels and
    leaderboards (Skin.objects.without_open_reports). Resolving them brings
    it back; deleting the skin removes it everywhere."""

    actions = [resolve_reports]
    list_display = ["image", "skin", "reason", "reporter", "created_at", "resolved"]
    list_display_links = ["skin"]
    list_filter = ["resolved", "reason"]
    list_select_related = ["skin", "reporter"]
    raw_id_fields = ["skin", "reporter"]
    readonly_fields = ["preview"]

    @admin.display(description="Skin image")
    def image(self, obj):
        return skin_image(obj.skin)

    @admin.display(description="Preview")
    def preview(self, obj):
        return skin_image(obj.skin, 160)
