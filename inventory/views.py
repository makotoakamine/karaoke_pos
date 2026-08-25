"""Views for the inventory app.

All views require an authenticated user (login_required mixin). They are
plain Django class-based views over the :class:`Item` model, using
:class:`ItemForm` for create/edit so the price/stock non-negative validation
is enforced on every write path.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    ListView,
    UpdateView,
)

from .forms import ItemForm
from .models import Item


class ItemListView(LoginRequiredMixin, ListView):
    model = Item
    template_name = "inventory/item_list.html"
    context_object_name = "items"
    extra_context = {"title": "Estoque"}


class ItemCreateView(LoginRequiredMixin, CreateView):
    model = Item
    form_class = ItemForm
    template_name = "inventory/item_form.html"
    extra_context = {"title": "Novo item"}

    def get_success_url(self) -> str:
        return reverse_lazy("inventory:item-list")


class ItemUpdateView(LoginRequiredMixin, UpdateView):
    model = Item
    form_class = ItemForm
    template_name = "inventory/item_form.html"
    extra_context = {"title": "Editar item"}

    def get_success_url(self) -> str:
        return reverse_lazy("inventory:item-list")


class ItemDeleteView(LoginRequiredMixin, DeleteView):
    model = Item
    template_name = "inventory/item_confirm_delete.html"
    extra_context = {"title": "Excluir item"}

    def get_success_url(self) -> str:
        return reverse_lazy("inventory:item-list")