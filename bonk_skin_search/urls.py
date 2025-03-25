"""
URL configuration for bonk_skin_search project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from skins.search import search_skins
from skins.upload import upload_skin
from skins.upload import upload_skin, autocomplete_creator
from django.conf import settings
from django.conf.urls.static import static
from skins.login import login_view, logout_view
from skins.my_profile import my_profile, edit_skin, delete_skin




urlpatterns = [
    path('admin/', admin.site.urls),
    path("search/", search_skins, name="search_skins"),
    path("", search_skins, name="home"),  # Home page is now the search page
    path('upload/', upload_skin, name="upload_skin"),  # New Upload Page
    path('autocomplete-creator/', autocomplete_creator, name='autocomplete_creator'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('my-profile/', my_profile, name='my_profile'),
    path('skin/<int:skin_id>/delete/', delete_skin, name='delete_skin'),
    path('skin/<int:skin_id>/edit/', edit_skin, name='edit_skin'),

]