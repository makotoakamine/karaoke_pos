"""Models for the tabs app.

A :class:`Tab` ("comanda") is the running slip staff open for a customer or a
group when they arrive; from #224 onwards orders are placed against it. This
task only models the slip itself and its open/closed lifecycle — no order
lines, no totals, no payment.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Tab(models.Model):
    """A customer tab ("comanda") staff open when guests arrive.

    The name is free text — staff type whatever they call the party (a person,
    a group, a room). Status mirrors :class:`tables.Table.Status` in shape:
    a tab starts ``open`` and is retired by closing it, which is why there is
    no ``is_active`` flag here — ``closed`` *is* the retirement state.

    ``table`` is purely organisational context so the waiter knows where to
    deliver; it is optional and deliberately ``SET_NULL`` so retiring *or*
    deleting the table never takes the tab with it.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        CLOSED = "closed", "Fechada"

    name = models.CharField(
        "nome",
        max_length=100,
        help_text="Nome da comanda (cliente, grupo ou como o salão a chama).",
    )
    status = models.CharField(
        "status",
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
        help_text="Comandas novas começam em \"aberta\"; fechá-la a aposenta.",
    )
    table = models.ForeignKey(
        "tables.Table",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="tabs",
        verbose_name="mesa",
        help_text="Mesa onde a comanda está sentada (opcional, apenas referência de entrega).",
    )
    created_at = models.DateTimeField("criada em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizada em", auto_now=True)
    closed_at = models.DateTimeField(
        "fechada em",
        blank=True,
        null=True,
        help_text="Momento em que a comanda foi fechada; vazio enquanto estiver aberta.",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "comanda"
        verbose_name_plural = "comandas"

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        """Reject a second *open* tab carrying an already-open name.

        This is validation rather than a ``unique`` column on purpose: the name
        has to be reusable once the earlier tab with it was closed, which a
        plain unique constraint would forbid forever. Matching is
        case-insensitive so "Maria" and "maria" are treated as the same party.
        """
        super().clean()
        name = (self.name or "").strip()
        if not name or self.status != self.Status.OPEN:
            return
        clash = Tab.objects.filter(name__iexact=name, status=self.Status.OPEN)
        if self.pk:
            clash = clash.exclude(pk=self.pk)
        if clash.exists():
            raise ValidationError(
                {
                    "name": ValidationError(
                        'Já existe uma comanda aberta com o nome "%(name)s". '
                        "Feche a anterior ou escolha outro nome.",
                        code="duplicate_open_name",
                        params={"name": name},
                    )
                }
            )

    def close(self) -> None:
        """Mark the tab closed and stamp when it happened."""
        self.status = self.Status.CLOSED
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "closed_at", "updated_at"])
