"""Views for the tables app.

All views require an authenticated user (login_required mixin). The list/overview
page shows every active table with its status as a Bootstrap badge and a manual
toggle button that flips free/occupied. Create and edit use a :class:`TableForm`
via class-based views.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    ListView,
    TemplateView,
    UpdateView,
)
from django.utils.translation import gettext as _

from .forms import TableForm
from .models import Table


class TableListView(LoginRequiredMixin, ListView):
    """Overview page: every active table with status badges + a toggle button."""

    model = Table
    template_name = "tables/table_list.html"
    context_object_name = "tables"
    extra_context = {"title": "Mesas"}

    def get_queryset(self):
        return Table.objects.filter(is_active=True).order_by("name")

    def post(self, request, *args, **kwargs):
        """Handle the manual free/occupied toggle submitted from the overview.

        Only the ``status`` field is flipped; the rest of the row is untouched.
        """
        table_id = request.POST.get("table_id")
        if table_id:
            try:
                table = Table.objects.get(pk=table_id, is_active=True)
            except (Table.DoesNotExist, ValueError):
                messages.error(request, _("Mesa não encontrada."))
            else:
                table.status = (
                    Table.Status.OCCUPIED
                    if table.status == Table.Status.FREE
                    else Table.Status.FREE
                )
                table.save(update_fields=["status", "updated_at"])
                label = (
                    _("ocupada") if table.status == Table.Status.OCCUPIED else _("livre")
                )
                messages.success(
                    request, _('Mesa "{}" marcada como {}.').format(table.name, label)
                )
        return HttpResponseRedirect(reverse_lazy("tables:table-list"))


class TableCreateView(LoginRequiredMixin, CreateView):
    model = Table
    form_class = TableForm
    template_name = "tables/table_form.html"
    extra_context = {"title": "Nova mesa"}

    def get_success_url(self) -> str:
        return reverse_lazy("tables:table-list")


class TableUpdateView(LoginRequiredMixin, UpdateView):
    model = Table
    form_class = TableForm
    template_name = "tables/table_form.html"
    extra_context = {"title": "Editar mesa"}

    def get_success_url(self) -> str:
        return reverse_lazy("tables:table-list")