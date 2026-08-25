"""Root URL configuration for the Karaoke POS project."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("mesas/", include("tables.urls")),
]