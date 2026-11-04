"""Django admin: skins and site accounts.

Admins sign in through the normal bonk.io login, not the admin's own password
form (site accounts have no usable password). /admin/login/ therefore
redirects to /login/ and comes back to the admin afterwards.
"""

from urllib.parse import urlencode

from django import forms
from django.contrib import admin
from django.shortcuts import redirect, render
from django.urls import reverse

from .models import BonkUser, Skin


def _login_through_bonk(request, extra_context=None):
    """Replace the admin login form with the site's bonk.io login."""
    next_url = request.GET.get("next") or reverse("admin:index")
    if request.user.is_authenticated and request.user.is_staff:
        return redirect(next_url)
    return redirect(f"{reverse('login')}?{urlencode({'next': next_url})}")


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


@admin.register(Skin)
class SkinAdmin(admin.ModelAdmin):
    actions = [bulk_update_creator]


@admin.register(BonkUser)
class BonkUserAdmin(admin.ModelAdmin):
    """Site accounts. Passwords are not shown or editable: there are none."""

    list_display = ("username", "is_staff", "is_superuser", "date_joined", "last_login")
    list_filter = ("is_staff", "is_superuser")
    search_fields = ("username",)
    ordering = ("username",)
    fields = ("username", "is_staff", "is_superuser", "groups", "date_joined", "last_login")
    readonly_fields = ("username", "date_joined", "last_login")
    filter_horizontal = ("groups",)

    def has_add_permission(self, request):
        # Accounts are created by signing in with bonk.io.
        return False
