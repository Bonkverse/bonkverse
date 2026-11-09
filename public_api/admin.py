from django.contrib import admin, messages

from .models import ApiKey, ApiTermsAcceptance


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    """Partner keys are created with `manage.py create_api_key`; anyone signed
    in makes standard keys at /developers/keys/. The full key is shown only
    then. Here staff see who has one, raise a key to partner, and revoke."""

    list_display = (
        "name",
        "display_prefix",
        "tier",
        "owner",
        "contact",
        "is_active",
        "last_used_at",
    )
    list_filter = ("tier", "is_active")
    search_fields = ("name", "prefix", "contact", "owner__username")
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at", "revoked_at")
    actions = ["revoke_keys"]

    def has_add_permission(self, request):
        return False

    @admin.display(description="Key")
    def display_prefix(self, obj):
        return f"bvk_{obj.prefix}_…"

    @admin.action(description="Revoke selected keys")
    def revoke_keys(self, request, queryset):
        count = 0
        for key in queryset.filter(is_active=True):
            key.revoke()
            count += 1
        self.message_user(request, f"Revoked {count} key(s).", messages.SUCCESS)


@admin.register(ApiTermsAcceptance)
class ApiTermsAcceptanceAdmin(admin.ModelAdmin):
    """Who agreed to which version of the API terms (developer portal)."""

    list_display = ("user", "version", "accepted_at")
    list_filter = ("version",)
    search_fields = ("user__username",)
    readonly_fields = ("user", "version", "accepted_at")

    def has_add_permission(self, request):
        return False
