"""Models for the tables app."""
from django.core.validators import MinValueValidator
from django.db import models


class Table(models.Model):
    """A physical restaurant table.

    The status field tracks whether a table is free or occupied so #109 can
    attach orders to a seat. ``is_active`` lets staff retire a table (e.g. it
    was removed from the dining room) without deleting the historical rows.
    """

    class Status(models.TextChoices):
        FREE = "free", "Livre"
        OCCUPIED = "occupied", "Ocupada"

    name = models.CharField(
        "nome/número",
        max_length=100,
        unique=True,
        help_text="Nome ou número único da mesa (ex.: \"Mesa 1\").",
    )
    seats = models.PositiveIntegerField(
        "lugares",
        validators=[MinValueValidator(1)],
        help_text="Quantidade de lugares da mesa (no mínimo 1).",
    )
    status = models.CharField(
        "status",
        max_length=10,
        choices=Status.choices,
        default=Status.FREE,
        help_text="Indica se a mesa está livre ou ocupada.",
    )
    is_active = models.BooleanField(
        "ativa",
        default=True,
        help_text="Mesas inativas permanecem no banco mas saem da visão de mesas.",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "mesa"
        verbose_name_plural = "mesas"

    def __str__(self) -> str:
        return self.name