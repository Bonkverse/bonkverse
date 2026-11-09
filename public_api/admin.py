from django.contrib import admin, messages

from .models import ApiKey


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    """Keys are created with `manage.py create_api_key` (the only time the
    full key is shown); here staff can see who has one and revoke it."""

    list_display = ("name", "display_prefix", "tier", "contact", "is_active", "last_used_at")
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
