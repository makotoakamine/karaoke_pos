"""Forms for the orders app.

The order-taking page is a single form that combines a table selector with a
formset of item lines. Each line carries an item and a quantity. The view is
responsible for validating quantities against current stock inside the
submission transaction, so this form only enforces per-line sanity (quantity
is a positive integer, item is one of the active-with-stock queryset).

Bootstrap classes are declared on the widgets rather than in the template
because the "Adicionar item" helper on the order page clones an already
rendered row — anything not carried by the widget itself would be lost.
"""
from django import forms

from inventory.models import Item
from tables.models import Table


class OrderForm(forms.Form):
    """Top-level form: choose the table the order is placed against."""

    table = forms.ModelChoiceField(
        queryset=Table.objects.filter(is_active=True).order_by("name"),
        label="Mesa",
        empty_label="Selecione a mesa",
        widget=forms.Select(attrs={"class": "form-select"}),
        error_messages={
            "required": "Selecione a mesa para o pedido.",
            "invalid_choice": "Mesa inválida.",
        },
    )


class OrderItemLineForm(forms.Form):
    """One line of the order: an item plus a quantity.

    The item field's queryset is restricted to active items with stock above
    zero so the picker only ever offers sellable goods. The view re-checks
    quantities against current stock inside the submission transaction so a
    race between render and submit cannot oversell.
    """

    item = forms.ModelChoiceField(
        queryset=Item.objects.filter(is_active=True, stock__gt=0).order_by("name"),
        label="Item",
        empty_label="Selecione o item",
        widget=forms.Select(attrs={"class": "form-select"}),
        error_messages={
            "required": "Selecione um item.",
            "invalid_choice": "Item inválido ou sem estoque.",
        },
    )
    quantity = forms.IntegerField(
        label="Quantidade",
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        error_messages={
            "min_value": "A quantidade deve ser no mínimo 1.",
            "invalid": "Informe uma quantidade válida.",
            "required": "Informe a quantidade.",
        },
    )

    def clean_quantity(self) -> int:
        quantity = self.cleaned_data["quantity"]
        if quantity < 1:
            raise forms.ValidationError("A quantidade deve ser no mínimo 1.")
        return quantity


OrderItemLineFormSet = forms.formset_factory(
    OrderItemLineForm,
    extra=1,
    can_delete=False,
)