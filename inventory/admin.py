"""Admin registration for the inventory app."""
from django.contrib import admin

from .models import Category, Item, NoteSuggestion


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "updated_at")
    search_fields = ("name",)
    ordering = ("name",)


class NoteSuggestionInline(admin.TabularInline):
    """Chips are edited on the item form (#230); mirror that shape in the admin."""

    model = NoteSuggestion
    extra = 1
    fields = ("text",)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    inlines = [NoteSuggestionInline]
    list_display = ("name", "category", "price", "stock", "is_active", "requires_kitchen_preparation", "updated_at")
    list_filter = ("is_active", "requires_kitchen_preparation", "category")
    search_fields = ("name",)
    list_editable = ("stock", "is_active", "requires_kitchen_preparation")
    ordering = ("name",)
