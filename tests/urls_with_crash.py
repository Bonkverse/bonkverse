"""The real URL conf plus one route that always raises, for testing the 500 page."""

from django.urls import path

from bonk_skin_search.urls import urlpatterns as site_urlpatterns


def crash(request):
    raise RuntimeError("boom: deliberate test crash")


urlpatterns = [path("__crash__/", crash), *site_urlpatterns]
