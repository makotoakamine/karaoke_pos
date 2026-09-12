"""Forms for the orders app.

The order-taking page is a single form that combines a tab selector (plus an
optional table, which is only delivery context for the waiter) with a formset
of item lines. Each line carries an item, a quantity and an optional free-text
note for the kitchen (#229). The view is responsible for validating quantities
against current stock inside the submission transaction, so this form only
enforces per-line sanity (quantity is a positive integer, item is one of the
active-with-stock queryset).

Bootstrap classes are declared on the widgets rather than in the template so
every rendered line carries its own styling, wherever it is rendered.
"""
from django import forms

from inventory.models import Item
from tables.models import Table
from tabs.models import Tab


class OrderForm(forms.Form):
    """Top-level form: the tab the order is placed against, plus its table.

    The tab is what the order actually belongs to, so it is mandatory and only
    *open* tabs are offered — billing against a closed comanda is exactly the
    mistake this queryset exists to prevent. The table is optional: it only
    tells the waiter where to deliver, and an order taken at the bar has none.
    """

    tab = forms.ModelChoiceField(
        queryset=Tab.objects.filter(status=Tab.Status.OPEN).order_by("name"),
        label="Comanda",
        empty_label="Selecione a comanda",
        widget=forms.Select(attrs={"class": "form-select"}),
        error_messages={
            "required": "Selecione a comanda para o pedido.",
            "invalid_choice": "Comanda inválida ou já fechada.",
        },
    )
    table = forms.ModelChoiceField(
        queryset=Table.objects.filter(is_active=True).order_by("name"),
        label="Mesa",
        required=False,
        empty_label="Sem mesa (opcional)",
        widget=forms.Select(attrs={"class": "form-select"}),
        error_messages={
            "invalid_choice": "Mesa inválida.",
        },
    )


class OrderItemLineForm(forms.Form):
    """One line of the order: an item, a quantity and an optional note.

    The item field's queryset is restricted to active items with stock above
    zero so the picker only ever offers sellable goods. The view re-checks
    quantities against current stock inside the submission transaction so a
    race between render and submit cannot oversell.

    The note (#229) is the waiter's free-text request for this line and is
    always optional: an order line without one stays the normal case, and a
    blank note must never be what makes a submission fail.
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
    notes = forms.CharField(
        label="Observação",
        required=False,
        max_length=200,
        strip=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Observação (ex.: com gelo e limão)",
                "autocomplete": "off",
            }
        ),
        error_messages={
            "max_length": "A observação deve ter no máximo 200 caracteres.",
        },
    )

    def clean_notes(self) -> str:
        """Always a string, never ``None`` — a blank note is the normal case.

        ``required=False`` on a ``CharField`` already yields ``""`` for a
        missing field, but the picker can also post the input empty; both paths
        have to land on the model's empty default rather than on ``None``.
        """
        return self.cleaned_data.get("notes") or ""

    def clean_quantity(self) -> int:
        quantity = self.cleaned_data["quantity"]
        if quantity < 1:
            raise forms.ValidationError("A quantidade deve ser no mínimo 1.")
        return quantity


#: The touch picker (#225) writes its own line inputs and sets ``TOTAL_FORMS``
#: itself, so ``extra`` only sizes the plain fallback. Five blank rows is what
#: a waiter gets with scripting off — enough for a real round without a
#: "add another line" button that would need the very JavaScript that is
#: missing.
OrderItemLineFormSet = forms.formset_factory(
    OrderItemLineForm,
    extra=5,
    can_delete=False,
)