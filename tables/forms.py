"""Forms for the tables app."""
from django import forms

from .models import Table


class TableForm(forms.ModelForm):
    """Create/edit form for :class:`Table`.

    Re-declares ``seats`` so the model-level ``MinValueValidator(1)``
    constraint surfaces as a bound-field error with a clear Portuguese message
    even when an out-of-range value is typed, and enforces it at the form
    layer too (belt-and-braces with the model validator). Status is left out of
    the form because it is driven by the manual toggle on the overview page.
    """

    class Meta:
        model = Table
        fields = ["name", "seats", "is_active"]

    seats = forms.IntegerField(
        label="Lugares",
        min_value=1,
        error_messages={
            "min_value": "A mesa precisa ter pelo menos 1 lugar.",
            "invalid": "Informe uma quantidade válida.",
        },
        help_text="Quantidade de lugares da mesa (no mínimo 1).",
    )