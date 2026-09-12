"""Root URL configuration for the Karaoke POS project."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("estoque/", include("inventory.urls")),
    path("mesas/", include("tables.urls")),
    path("comandas/", include("tabs.urls")),
    path("pedidos/", include("orders.urls")),
]

# Serve user-uploaded media in development so the config page's alert sound
# FileField resolves to a working URL on a fresh checkout. In production a
# reverse proxy serves MEDIA_URL directly; this block is only active when
# DEBUG is on.
if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)