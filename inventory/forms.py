"""Forms for the inventory app."""
from django import forms

from .models import Category, Item, NoteSuggestion


class ItemForm(forms.ModelForm):
    """Create/edit form for :class:`Item`.

    Re-declares ``price`` and ``stock`` so model-level ``MinValueValidator``
    constraints surface as bound-field errors with a clear Portuguese message
    even when a negative value is typed, and enforces non-negative values at
    the form layer too (belt-and-braces with the model validators).

    ``category`` is re-declared as well so the picker keeps a deterministic
    alphabetical order, offers a "select one" placeholder instead of a blank
    line, and refuses an empty submission with a Portuguese message (#223).

    ``note_suggestions`` is the one field that is not on the model (#230): a
    textarea of one suggestion per line, edited here rather than on a separate
    screen because a chip list is a property of the item, not an entity staff
    would go looking for. Save syncs the :class:`NoteSuggestion` rows to
    whatever the textarea now says — lines added become rows, lines removed are
    deleted — so the textarea is the single source of truth and create and edit
    behave identically.
    """

    class Meta:
        model = Item
        fields = ["name", "category", "price", "stock", "is_active", "requires_kitchen_preparation"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "requires_kitchen_preparation": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
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

    note_suggestions = forms.CharField(
        label="Sugestões de observação",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "gelo\nrodela de limão",
            }
        ),
        help_text=(
            "Uma sugestão por linha. Aparecem como atalhos ao lançar o item no "
            "pedido. Linhas em branco e repetidas são ignoradas."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # On edit, pre-fill the textarea from the rows already saved. Only when
        # the caller did not pass an explicit initial, so a re-displayed bound
        # form still shows what was typed.
        if self.instance.pk and "note_suggestions" not in self.initial:
            self.initial["note_suggestions"] = "\n".join(
                self.instance.note_suggestions.values_list("text", flat=True)
            )

    def clean_note_suggestions(self) -> list:
        """Turn the raw textarea into the exact list of suggestions to keep.

        Whitespace is trimmed, blank lines and repeats are dropped silently —
        typing the same chip twice is a slip, not an error worth blocking a
        save on — and the surviving order is the one the user typed.
        """
        raw = self.cleaned_data.get("note_suggestions") or ""
        texts = []
        for line in raw.splitlines():
            text = line.strip()
            if not text or text in texts:
                continue
            if len(text) > NoteSuggestion._meta.get_field("text").max_length:
                raise forms.ValidationError(
                    "Cada sugestão deve ter no máximo 100 caracteres: "
                    f'"{text[:40]}…" é longa demais.'
                )
            texts.append(text)
        return texts

    def save(self, commit=True):
        item = super().save(commit=commit)
        if commit:
            self._sync_note_suggestions(item)
        else:
            # Defer to save_m2m() like Django does for m2m data: the rows need
            # the item's PK, which does not exist yet with commit=False.
            save_m2m = self.save_m2m

            def save_related():
                save_m2m()
                self._sync_note_suggestions(self.instance)

            self.save_m2m = save_related
        return item

    def _sync_note_suggestions(self, item) -> None:
        """Make the item's rows match ``cleaned_data`` exactly.

        Rows are matched by text, so untouched suggestions keep their PK and
        their ``created_at`` instead of being churned on every save.
        """
        texts = self.cleaned_data.get("note_suggestions") or []
        existing = {s.text: s for s in item.note_suggestions.all()}

        stale = [s.pk for text, s in existing.items() if text not in texts]
        if stale:
            item.note_suggestions.filter(pk__in=stale).delete()

        NoteSuggestion.objects.bulk_create(
            [
                NoteSuggestion(item=item, text=text)
                for text in texts
                if text not in existing
            ]
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
