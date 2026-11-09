"""The developer portal, mounted at /developers/ (views/portal.py).
developers.bonkverse.io redirects here (a Cloudflare redirect rule)."""

from django.urls import path

from .views import portal

urlpatterns = [
    path("", portal.index, name="developers"),
    path("terms/", portal.terms, name="developer_terms"),
    path("keys/", portal.keys, name="developer_keys"),
    path("keys/<str:prefix>/revoke/", portal.revoke_key, name="developer_revoke_key"),
]
