"""Models for the inventory app."""
from django.core.validators import MinValueValidator
from django.db import models


class Item(models.Model):
    """A sellable good kept in stock.

    Items can be retired from the catalogue without deletion by flipping
    ``is_active`` to ``False``; the order page in #109 will only sell active
    items. Stock is edited by hand — there is no stock-movement history or
    recipe/ingredient modelling in this round.
    """

    name = models.CharField(
        "nome",
        max_length=200,
        help_text="Nome do item exibido no catálogo.",
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