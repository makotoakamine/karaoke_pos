"""Models for the inventory app."""
from django.core.validators import MinValueValidator
from django.db import models


class Category(models.Model):
    """A staff-managed grouping for the sellable catalogue.

    Categories exist so the touch-friendly order page (#225) has real data to
    filter on. The list is managed from the stock area (there is no seeded
    taxonomy beyond the starter rows created by the data migration) and names
    are unique so the same bucket cannot be typed twice.

    Deletion is refused while items still point at a category — see the
    ``PROTECT`` on :attr:`Item.category` — so a category is never silently
    emptied out from under the catalogue.
    """

    name = models.CharField(
        "nome",
        max_length=100,
        unique=True,
        help_text="Nome único da categoria (ex.: \"bebidas alcoólicas\").",
        error_messages={"unique": "Já existe uma categoria com esse nome."},
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "categoria"
        verbose_name_plural = "categorias"

    def __str__(self) -> str:
        return self.name


class Item(models.Model):
    """A sellable good kept in stock.

    Items can be retired from the catalogue without deletion by flipping
    ``is_active`` to ``False``; the order page in #109 will only sell active
    items. Stock is edited by hand — there is no stock-movement history or
    recipe/ingredient modelling in this round.

    Every item belongs to exactly one :class:`Category` (#223): there is no
    uncategorised bucket, so downstream screens can group or filter without
    special-casing a null.
    """

    name = models.CharField(
        "nome",
        max_length=200,
        help_text="Nome do item exibido no catálogo.",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="items",
        verbose_name="categoria",
        help_text="Categoria do item no catálogo (obrigatória).",
    )
    price = models.DecimalField(
        "preço",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Preço unitário em reais (não pode ser negativo).",
    )
    stock = models.IntegerField(
        "estoque",
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Quantidade atual em estoque (não pode ser negativa).",
    )
    is_active = models.BooleanField(
        "ativo",
        default=True,
        help_text="Itens inativos permanecem no banco mas saem do catálogo de vendas.",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "item"
        verbose_name_plural = "itens"

    def __str__(self) -> str:
        return self.name
