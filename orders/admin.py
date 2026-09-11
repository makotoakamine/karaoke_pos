"""Admin registration for the orders app."""
from django.contrib import admin

from .models import Order, OrderItem


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "tab", "table", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("tab__name", "table__name")
    list_select_related = ("tab", "table")
    ordering = ("-created_at",)


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "item", "quantity", "unit_price")
    list_filter = ("item",)
    search_fields = ("item__name",)
    list_select_related = ("order", "item")
    ordering = ("-order__created_at",)