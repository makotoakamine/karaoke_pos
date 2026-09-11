"""Admin registration for the inventory app."""
from django.contrib import admin

from .models import Category, Item


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "updated_at")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "stock", "is_active", "updated_at")
    list_filter = ("is_active", "category")
    search_fields = ("name",)
    list_editable = ("stock", "is_active")
    ordering = ("name",)
