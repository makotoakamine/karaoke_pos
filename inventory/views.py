"""Views for the inventory app.

All views require an authenticated user (login_required mixin). They are
plain Django class-based views over the :class:`Item` and :class:`Category`
models, using :class:`ItemForm` / :class:`CategoryForm` for create/edit so the
price/stock non-negative validation and the required-category rule are
enforced on every write path.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.db.models.deletion import ProtectedError
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import (
    CreateView,
    DeleteView,
    FormView,
    ListView,
    UpdateView,
)

from .forms import CategoryForm, ItemForm, ItemImportForm
from .importers import SpreadsheetImportError, import_items
from .models import Category, Item


class ItemListView(LoginRequiredMixin, ListView):
    model = Item
    template_name = "inventory/item_list.html"
    context_object_name = "items"
    extra_context = {"title": "Estoque"}

    def get_queryset(self):
        # The list renders every item's category, so fetch it in the same query.
        return super().get_queryset().select_related("category")


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


class ItemImportView(LoginRequiredMixin, FormView):
    """Upload an .xlsx menu and upsert the catalogue from it (#398).

    The work happens in :func:`inventory.importers.import_items`; this view
    only renders its summary on the same page. A file-level failure becomes a
    form error, and the importer guarantees nothing was written in that case.
    """

    form_class = ItemImportForm
    template_name = "inventory/item_import.html"
    extra_context = {"title": "Importar planilha"}

    def form_valid(self, form):
        try:
            result = import_items(form.cleaned_data["file"])
        except SpreadsheetImportError as exc:
            form.add_error("file", str(exc))
            return self.form_invalid(form)
        return self.render_to_response(
            self.get_context_data(form=self.get_form_class()(), result=result)
        )


class CategoryListView(LoginRequiredMixin, ListView):
    model = Category
    template_name = "inventory/category_list.html"
    context_object_name = "categories"
    extra_context = {"title": "Categorias"}

    def get_queryset(self):
        # The item count drives both the column and the "can this be deleted?"
        # hint, so annotate it instead of querying once per row. The explicit
        # order_by is required: annotate() adds a GROUP BY, and Django drops
        # Meta.ordering from grouped queries.
        return (
            super()
            .get_queryset()
            .annotate(item_count=Count("items"))
            .order_by("name")
        )


class CategoryCreateView(LoginRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = "inventory/category_form.html"
    extra_context = {"title": "Nova categoria"}

    def get_success_url(self) -> str:
        return reverse_lazy("inventory:category-list")


class CategoryUpdateView(LoginRequiredMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = "inventory/category_form.html"
    extra_context = {"title": "Editar categoria"}

    def get_success_url(self) -> str:
        return reverse_lazy("inventory:category-list")


class CategoryDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a category, refusing while items still point at it.

    ``Item.category`` is ``PROTECT`` (same convention as ``OrderItem.item``),
    so a category in use must not be deleted and must not blow up either: the
    confirmation page says up front that it is in use, and a POST that gets
    through anyway is turned into a readable message on the list page.
    """

    model = Category
    template_name = "inventory/category_confirm_delete.html"
    extra_context = {"title": "Excluir categoria"}

    def get_success_url(self) -> str:
        return reverse_lazy("inventory:category-list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["item_count"] = self.object.items.count()
        return context

    def form_valid(self, form):
        self.object = self.get_object()
        try:
            self.object.delete()
        except ProtectedError:
            messages.error(
                self.request,
                _(
                    'A categoria "{}" não pode ser excluída porque ainda há '
                    "itens vinculados a ela. Mova ou exclua esses itens primeiro."
                ).format(self.object.name),
            )
        else:
            messages.success(
                self.request, _('Categoria "{}" excluída.').format(self.object.name)
            )
        return HttpResponseRedirect(self.get_success_url())
