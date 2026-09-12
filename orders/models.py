"""Models for the orders app.

The order records are the app's central ledger: an :class:`Order` belongs to a
single :class:`tabs.Tab` — the running slip the guests are drinking against —
and holds one or more :class:`OrderItem` lines. Each line snapshots the item's
unit price at the moment the order is placed so later price edits in the
inventory app never rewrite historical orders.

The table is *not* what the order hangs off any more (#224): it is optional
delivery context for the waiter, so an order can perfectly well exist with no
table at all (a walk-up at the bar, a party still choosing where to sit).

The :class:`Order` status starts at ``open``; task #110 will filter on this to
build the bill/close-flow. ``done`` is reserved for that future step and is
already present in the choices to keep the column stable from day one.
"""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Order(models.Model):
    """A waiter-placed order attached to a tab, optionally to a table too.

    The order's status starts at ``open`` and only the future close-flow
    (#110) will flip it to ``done``. The ``created_at`` timestamp is the
    authoritative moment the order was placed.

    Both foreign keys are ``PROTECT``: an order is a historical financial
    record, so neither closing-and-deleting a tab nor removing a table from the
    dining room may take the orders that referenced them along.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        DONE = "done", "Encerrada"

    tab = models.ForeignKey(
        "tabs.Tab",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="comanda",
        help_text="Comanda à qual o pedido está vinculado.",
    )
    table = models.ForeignKey(
        "tables.Table",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="orders",
        verbose_name="mesa",
        help_text="Mesa onde entregar o pedido (opcional, apenas contexto de entrega).",
    )
    status = models.CharField(
        "status",
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
        help_text="Pedidos novos começam em \"aberta\"; o fluxo de encerramento (#110) a move para \"encerrada\".",
    )
    auto_print_failed = models.BooleanField(
        "falha na impressão automática",
        default=False,
        help_text=(
            "Marcado quando a impressão automática na criação do pedido (#237) "
            "não consegue alcançar a impressora. A cozinha vê um aviso "
            "vermelho persistente no card até que uma reimpressão (manual ou "
            "automática) tenha sucesso, momento em que o flag é limpo."
        ),
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"

    def __str__(self) -> str:
        return f"Pedido #{self.pk} – {self.tab.name}"

    @property
    def subtotal(self) -> Decimal:
        """What this order costs, from the lines' snapshotted prices.

        Deliberately walks ``self.items.all()`` instead of aggregating in SQL:
        the tab detail page prefetches the lines, so summing in Python costs no
        extra query there, and a caller that did not prefetch still gets the
        right number (at the price of one query).
        """
        return sum((line.line_total for line in self.items.all()), Decimal("0.00"))


class OrderItem(models.Model):
    """A single line on an :class:`Order`.

    ``unit_price`` is snapshotted from :class:`inventory.Item` at order time so
    price edits in the inventory app never rewrite historical orders. The
    ``quantity`` is a positive integer validated at submission time against
    current stock before anything is written.

    ``notes`` (#229) is the waiter's free-text request for *this* line — "com
    gelo e limão", "sem cebola" — and travels with the item all the way to the
    kitchen screen and the printed ticket. A line without a note is the normal
    case, so the field is blank with an empty default and never ``NULL``: every
    reader can treat it as a plain string.

    ``is_prepared`` (#236) is the kitchen's per-line "done" flag, off by
    default for every new order line. The kitchen screen offers a toggle per
    line that flips it; a done line stays on the card, visibly struck through,
    and never disappears. Only the kitchen surfaces expose the toggle — the
    flag exists on every line, but the kitchen prefetch (#234) already
    restricts kitchen-facing rows to preparation lines, so serve-direct lines
    never reach a surface that renders one. Toggling a line never changes
    ``Order.status``; only the "Pronto" footer button does that.
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
    notes = models.CharField(
        "observações",
        max_length=200,
        blank=True,
        default="",
        help_text='Pedido especial do cliente para esta linha ("com gelo e limão").',
    )
    is_prepared = models.BooleanField(
        "preparado",
        default=False,
        help_text=(
            "Marcado pela cozinha quando esta linha está pronta. O card de "
            "pedidos da cozinha (#236) oferece um botão por linha para "
            "alternar este estado; a linha nunca some do card, apenas é "
            "riscada. A impressão em papel do flag virá em #237."
        ),
    )

    class Meta:
        ordering = ["item__name"]
        verbose_name = "item do pedido"
        verbose_name_plural = "itens do pedido"

    def __str__(self) -> str:
        return f"{self.quantity}x {self.item.name} @ {self.unit_price}"

    @property
    def line_total(self) -> Decimal:
        """Quantity times the *snapshotted* price, never ``item.price``.

        Reading the live inventory price here would silently rewrite every past
        order the next time someone edits the catalogue.
        """
        return self.unit_price * self.quantity