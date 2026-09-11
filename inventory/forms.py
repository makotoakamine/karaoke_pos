"""Forms for the inventory app."""
from django import forms

from .models import Category, Item


class ItemForm(forms.ModelForm):
    """Create/edit form for :class:`Item`.

    Re-declares ``price`` and ``stock`` so model-level ``MinValueValidator``
    constraints surface as bound-field errors with a clear Portuguese message
    even when a negative value is typed, and enforces non-negative values at
    the form layer too (belt-and-braces with the model validators).

    ``category`` is re-declared as well so the picker keeps a deterministic
    alphabetical order, offers a "select one" placeholder instead of a blank
    line, and refuses an empty submission with a Portuguese message (#223).
    """

    class Meta:
        model = Item
        fields = ["name", "category", "price", "stock", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        label="Categoria",
        empty_label="Selecione a categoria",
        widget=forms.Select(attrs={"class": "form-select"}),
        error_messages={
            "required": "Selecione a categoria do item.",
            "invalid_choice": "Categoria inválida.",
        },
        help_text="Categoria do item no catálogo (obrigatória).",
    )
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


class CategoryForm(forms.ModelForm):
    """Create/edit form for :class:`Category`.

    Only the name is editable. Uniqueness is enforced by the model field, whose
    ``unique`` error message is already in Portuguese, so a duplicate name comes
    back as a field error on the form instead of an IntegrityError.
    """

    class Meta:
        model = Category
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
        }
        labels = {"name": "Nome"}
        help_texts = {
            "name": "Nome único da categoria (ex.: \"bebidas alcoólicas\")."
        }
        error_messages = {
            "name": {
                "required": "Informe o nome da categoria.",
                "unique": "Já existe uma categoria com esse nome.",
            }
        }
