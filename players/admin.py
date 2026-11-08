from django.contrib import admin

from .models import ProfileVisibility


@admin.register(ProfileVisibility)
class ProfileVisibilityAdmin(admin.ModelAdmin):
    list_display = ("user", "level_history", "activity", "play_partners", "skins", "updated_at")
    search_fields = ("user__username",)
    raw_id_fields = ("user",)
