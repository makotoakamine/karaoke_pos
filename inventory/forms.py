"""Forms for the inventory app."""
from django import forms

from .models import Item


class ItemForm(forms.ModelForm):
    """Create/edit form for :class:`Item`.

    Re-declares ``price`` and ``stock`` so model-level ``MinValueValidator``
    constraints surface as bound-field errors with a clear Portuguese message
    even when a negative value is typed, and enforces non-negative values at
    the form layer too (belt-and-braces with the model validators).
    """

    class Meta:
        model = Item
        fields = ["name", "price", "stock", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    price = forms.DecimalField(
        label="Preço",
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        error_messages={
            "min_value": "O preço não pode ser negativo.",
            "invalid": "Informe um preço válido.",
        },
        help_text="Preço unitário em reais (não pode ser negativo).",
    )
    stock = forms.IntegerField(
        label="Estoque",
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        error_messages={
            "min_value": "O estoque não pode ser negativo.",
            "invalid": "Informe uma quantidade válida.",
        },
        help_text="Quantidade atual em estoque (zero é permitido, negativo não).",
    )