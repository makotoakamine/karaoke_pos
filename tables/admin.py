"""Admin registration for the tables app."""
from django.contrib import admin

from .models import Table


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("name", "seats", "status", "is_active", "updated_at")
    list_filter = ("status", "is_active")
    search_fields = ("name",)
    list_editable = ("status", "is_active")
    ordering = ("name",)