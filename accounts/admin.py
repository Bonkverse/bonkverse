"""Django admin: site accounts (BonkUser) and Discord links (DiscordLink).

The admin site's login (through bonk.io) is set up in skins/admin.py.
"""

from django.contrib import admin

from .models import BonkUser, DiscordLink


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


@admin.register(DiscordLink)
class DiscordLinkAdmin(admin.ModelAdmin):
    """Discord ↔ bonk.io links for BonxBot. Staff remove a wrong one here."""

    list_display = ("discord_user_id", "bonk_player", "is_default", "source", "verified_at")
    list_filter = ("source", "is_default")
    search_fields = ("=discord_user_id", "bonk_player__username")
    raw_id_fields = ("bonk_player",)
    readonly_fields = ("created_at",)
