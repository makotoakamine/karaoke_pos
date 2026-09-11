"""Views for the tabs app.

All views require an authenticated user (login_required mixin). The overview
lists the open tabs by default and reaches the closed ones through a filter on
the same URL (``?status=closed``), so closed tabs are never mixed into the open
list. Closing a tab is a POST to the overview, mirroring the free/occupied
toggle :class:`tables.views.TableListView` already uses.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import CreateView, ListView, UpdateView

from .forms import TabForm
from .models import Tab

CLOSED_FILTER = "closed"


class TabListView(LoginRequiredMixin, ListView):
    """Overview page: open tabs by default, closed ones behind ``?status=closed``."""

    model = Tab
    template_name = "tabs/tab_list.html"
    context_object_name = "tabs"

    def showing_closed(self) -> bool:
        return self.request.GET.get("status") == CLOSED_FILTER

    def get_queryset(self):
        status = Tab.Status.CLOSED if self.showing_closed() else Tab.Status.OPEN
        return (
            Tab.objects.filter(status=status)
            .select_related("table")
            .order_by("-closed_at" if self.showing_closed() else "-created_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["showing_closed"] = self.showing_closed()
        context["title"] = "Comandas fechadas" if self.showing_closed() else "Comandas"
        return context

    def post(self, request, *args, **kwargs):
        """Close the tab whose id was submitted from the overview.

        Only open tabs can be closed; reopening is out of scope, so this is a
        one-way action rather than the two-way toggle /mesas/ uses.
        """
        tab_id = request.POST.get("tab_id")
        if tab_id:
            try:
                tab = Tab.objects.get(pk=tab_id, status=Tab.Status.OPEN)
            except (Tab.DoesNotExist, ValueError):
                messages.error(request, _("Comanda não encontrada ou já fechada."))
            else:
                tab.close()
                messages.success(
                    request, _('Comanda "{}" fechada.').format(tab.name)
                )
        return HttpResponseRedirect(reverse_lazy("tabs:tab-list"))


class TabCreateView(LoginRequiredMixin, CreateView):
    model = Tab
    form_class = TabForm
    template_name = "tabs/tab_form.html"
    extra_context = {"title": "Nova comanda"}

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request, _('Comanda "{}" aberta.').format(self.object.name)
        )
        return response

    def get_success_url(self) -> str:
        return reverse_lazy("tabs:tab-list")


class TabUpdateView(LoginRequiredMixin, UpdateView):
    model = Tab
    form_class = TabForm
    template_name = "tabs/tab_form.html"
    extra_context = {"title": "Editar comanda"}

    def get_success_url(self) -> str:
        # Editing a closed tab lands back on the closed listing rather than on
        # the open one it no longer belongs to.
        url = str(reverse_lazy("tabs:tab-list"))
        if self.object.status == Tab.Status.CLOSED:
            return f"{url}?status={CLOSED_FILTER}"
        return url
