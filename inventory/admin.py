"""Admin registration for the inventory app."""
from django.contrib import admin

from .models import Item


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "stock", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    list_editable = ("stock", "is_active")
    ordering = ("name",)