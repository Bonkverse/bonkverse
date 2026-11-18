from django.urls import path

from .views import bot as views

# Mounted at /api/bot/ (BonxBot's read endpoints; see views/bot.py). Skin
# submissions, POST /api/bot/skins/, live in skins/urls.py. Usernames use the
# profile pages' <username:…> converter ("." and ".." are "~." and "~..").
app_name = "bot_api"

urlpatterns = [
    path("skins/search/", views.search_skins, name="search_skins"),
    path("skins/random/", views.random, name="random_skin"),
    path("skins/latest/", views.latest, name="latest_skins"),
    path("skins/<int:skin_id>/", views.skin, name="skin"),
    path("players/<username:username>/", views.player, name="player"),
    path("maps/decode/", views.decode_map, name="decode_map"),
    path("collection/", views.collect, name="collect"),
]
