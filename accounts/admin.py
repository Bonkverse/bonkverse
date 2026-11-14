"""Django admin: site accounts (BonkUser).

The admin site's login (through bonk.io) is set up in skins/admin.py.
"""

from django.contrib import admin

from .models import BonkUser


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
