"""Forms for the tabs app."""
from django import forms
from django.db.models import Q

from tables.models import Table

from .models import Tab


class TabForm(forms.ModelForm):
    """Create/edit form for :class:`Tab`.

    Only the two fields staff actually type are exposed: the free-text name and
    the optional table. Status is driven by the "Fechar" action on the overview
    (like the free/occupied toggle on /mesas/), never by this form. The
    "no two open tabs share a name" rule lives on the model's ``clean()`` and
    surfaces here as an error on the name field.

    Bootstrap classes are declared on the widgets rather than in the template,
    matching ``orders/forms.py`` and ``inventory/forms.py``.
    """

    class Meta:
        model = Tab
        fields = ["name", "table"]

    name = forms.CharField(
        label="Nome",
        max_length=100,
        widget=forms.TextInput(attrs={"class": "form-control", "autofocus": "autofocus"}),
        help_text="Nome da comanda (cliente, grupo ou como o salão a chama).",
        error_messages={"required": "Informe o nome da comanda."},
    )
    table = forms.ModelChoiceField(
        queryset=Table.objects.none(),
        label="Mesa",
        required=False,
        empty_label="Sem mesa",
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Opcional — só indica onde entregar o pedido.",
        error_messages={"invalid_choice": "Mesa inválida."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Offer the active tables plus, when editing, whichever table this tab
        # already points at: a table retired after the tab was opened must
        # still round-trip through the form instead of being silently cleared.
        criteria = Q(is_active=True)
        if self.instance.table_id:
            criteria |= Q(pk=self.instance.table_id)
        self.fields["table"].queryset = Table.objects.filter(criteria).order_by("name")
