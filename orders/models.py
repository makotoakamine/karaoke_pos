"""Models for the orders app.

The order records are the app's central ledger: an :class:`Order` belongs to a
single :class:`tables.Table` and holds one or more :class:`OrderItem` lines.
Each line snapshots the item's unit price at the moment the order is placed so
later price edits in the inventory app never rewrite historical orders.

The :class:`Order` status starts at ``open``; task #110 will filter on this to
build the bill/close-flow. ``done`` is reserved for that future step and is
already present in the choices to keep the column stable from day one.
"""
from django.core.validators import MinValueValidator
from django.db import models


class Order(models.Model):
    """A waiter-placed order attached to a table.

    The order's status starts at ``open`` and only the future close-flow
    (#110) will flip it to ``done``. The ``created_at`` timestamp is the
    authoritative moment the order was placed.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        DONE = "done", "Encerrada"

    table = models.ForeignKey(
        "tables.Table",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="mesa",
        help_text="Mesa à qual o pedido está vinculado.",
    )
    status = models.CharField(
        "status",
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
        help_text="Pedidos novos começam em \"aberta\"; o fluxo de encerramento (#110) a move para \"encerrada\".",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"

    def __str__(self) -> str:
        return f"Pedido #{self.pk} – {self.table.name}"


class OrderItem(models.Model):
    """A single line on an :class:`Order`.

    ``unit_price`` is snapshotted from :class:`inventory.Item` at order time so
    price edits in the inventory app never rewrite historical orders. The
    ``quantity`` is a positive integer validated at submission time against
    current stock before anything is written.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="pedido",
    )
    item = models.ForeignKey(
        "inventory.Item",
        on_delete=models.PROTECT,
        related_name="order_lines",
        verbose_name="item",
    )
    quantity = models.PositiveIntegerField(
        "quantidade",
        validators=[MinValueValidator(1)],
        help_text="Quantidade vendida deste item no pedido (no mínimo 1).",
    )
    unit_price = models.DecimalField(
        "preço unitário",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Preço unitário do item no momento do pedido (snapshot, não muda).",
    )

    class Meta:
        ordering = ["item__name"]
        verbose_name = "item do pedido"
        verbose_name_plural = "itens do pedido"

    def __str__(self) -> str:
        return f"{self.quantity}x {self.item.name} @ {self.unit_price}"