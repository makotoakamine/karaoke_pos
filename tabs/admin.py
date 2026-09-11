"""Admin registration for the tabs app."""
from django.contrib import admin

from .models import Tab


@admin.register(Tab)
class TabAdmin(admin.ModelAdmin):
    list_display = ("name", "table", "status", "created_at", "closed_at")
    list_filter = ("status",)
    search_fields = ("name",)
    ordering = ("-created_at",)
