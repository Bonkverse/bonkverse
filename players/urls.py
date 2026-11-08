from django.urls import path

from . import views

# Usernames go in the path as-is (URL-encoded); bonk.io names can't contain "/".
urlpatterns = [
    path("player/<str:username>/", views.overview, name="player_profile"),
    path("player/<str:username>/activity/", views.activity, name="player_activity"),
    path("player/<str:username>/level/", views.level, name="player_level"),
    path("player/<str:username>/maps/", views.maps, name="player_maps"),
    path("player/<str:username>/people/", views.people, name="player_people"),
    path("player/<str:username>/skins/", views.skins, name="player_skins"),
    path("settings/profile/", views.profile_settings, name="profile_settings"),
]
