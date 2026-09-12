"""Views for the orders app.

The order-taking page (``/pedidos/novo/``) is the app's central waiter flow.
It renders a tab selector — plus an optional table, purely as delivery
context — and a formset of item lines, each carrying an optional free-text
note for the kitchen (#229). On POST the whole submission runs inside a single
transaction: the chosen tab is re-read under a row lock and must still be
open, each requested quantity is validated against current stock
before anything is written, the items' stock counts are decremented, and the
order with its lines is created. If any single line exceeds stock the whole
submission is rejected with a clear form error and nothing is changed.

Since #225 the same view also hands the template the raw picker data — the
open tabs, the sellable catalogue and its categories — so the touch UI can
filter client-side without a second endpoint. Since #231 that page is a
three-step wizard (comanda, itens, confirmação), but entirely on the client:
the steps are sections of the same form, and the POST contract is unchanged —
one form, one formset, one submission. The only thing the wizard needs from
the server is ``submission_rejected``, so a refused POST comes back on the
step where the problem is rather than on a blank step 1.

Prices never reach the waiter's screen (#231): the catalogue is rendered
without them and the order page shows no totals. ``OrderItem.unit_price`` is
still snapshotted here — the till and the kitchen tickets need it, the waiter
does not.

Table occupancy is deliberately not touched here (#224): the table is now only
a hint for the waiter, and ``tables.Table.status`` is owned by the tables
screens alone.

The kitchen screen (#110) also prints (#228): :class:`OrderPrintView` renders an
order as an ESC/POS kitchen ticket and hands it to the thermal printer. It is a
read-only action on the order — printing never changes the status.
"""
from typing import Iterable, Tuple

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import View

from inventory.models import Category, Item
from tabs.models import Tab

from .forms import OrderForm, OrderItemLineFormSet
from .models import Order, OrderItem
from .services.printer import PrinterError, print_raw
from .services.receipts import kitchen_receipt_bytes


def _open_tabs():
    """The open tabs the picker may offer, alphabetically, with their table.

    Mirrors ``OrderForm.tab``'s queryset exactly: whatever the picker renders
    has to be something the form would also accept, or tapping a tab would
    produce an "invalid choice" the waiter cannot explain. The table comes
    along so each entry can show where the comanda is sitting.
    """
    return list(
        Tab.objects.filter(status=Tab.Status.OPEN)
        .select_related("table")
        .order_by("name")
    )


def _sellable_items():
    """The sellable catalogue, alphabetically, with each item's category and
    note suggestions.

    Mirrors ``OrderItemLineForm.item``'s queryset: active items with stock
    above zero, nothing else. The category rides along so the client-side
    chips can filter the rendered list without another request. Since #232
    the per-item note suggestions (#230) are prefetched in the same pass,
    so the add-item dialog can render one-tap chips next to the notes box
    without a second query per item.
    """
    return list(
        Item.objects.filter(is_active=True, stock__gt=0)
        .select_related("category")
        .prefetch_related("note_suggestions")
        .order_by("name")
    )


def _sellable_categories():
    """Categories that actually have something sellable in them.

    A chip for an empty category would filter the list down to nothing, so the
    row only carries categories with at least one active, in-stock item.
    """
    return list(
        Category.objects.filter(items__is_active=True, items__stock__gt=0)
        .distinct()
        .order_by("name")
    )


class OrderCreateView(LoginRequiredMixin, View):
    """Waiter-facing order-taking page."""

    template_name = "orders/order_form.html"
    extra_context = {"title": "Novo pedido"}

    def _render(self, request, order_form, formset, form_errors=None, status=200):
        context = {
            "title": self.extra_context["title"],
            "order_form": order_form,
            "formset": formset,
            "form_errors": form_errors or [],
            "open_tabs": _open_tabs(),
            "sellable_items": _sellable_items(),
            "item_categories": _sellable_categories(),
            # The wizard (#231) needs to know it is re-rendering a refusal, so
            # it can seed itself on the step where the problem is instead of
            # dropping the waiter on a blank step 1. Every rejection path here
            # renders with a 4xx; a fresh page is the only 200.
            "submission_rejected": status != 200,
        }
        return render(request, self.template_name, context, status=status)

    def get(self, request, *args, **kwargs):
        return self._render(
            request, OrderForm(), OrderItemLineFormSet(prefix="lines")
        )

    def post(self, request, *args, **kwargs):
        order_form = OrderForm(request.POST)
        formset = OrderItemLineFormSet(request.POST, prefix="lines")

        if not order_form.is_valid() or not formset.is_valid():
            return self._render(request, order_form, formset, status=400)

        tab = order_form.cleaned_data["tab"]
        table = order_form.cleaned_data.get("table")

        # Collect non-empty lines (the formset always renders at least one
        # extra blank row; an empty item field means the waiter did not fill
        # that line in). The note rides along per line and is optional: a
        # missing one is simply the empty string the model defaults to.
        lines: list[Tuple[Item, int, str]] = []
        for line in formset.cleaned_data:
            if not line:
                continue
            item = line.get("item")
            quantity = line.get("quantity")
            if not item or not quantity:
                continue
            lines.append((item, quantity, line.get("notes") or ""))

        if not lines:
            return self._render(
                request, order_form, formset,
                form_errors=[_("Adicione ao menos um item ao pedido.")],
                status=400,
            )

        # Aggregate quantities per item so a waiter entering the same item on
        # two lines still validates the combined demand against current stock.
        demanded: dict[int, int] = {}
        for item, quantity, _notes in lines:
            demanded[item.pk] = demanded.get(item.pk, 0) + quantity

        form_errors: list[str] = []
        try:
            with transaction.atomic():
                # Re-fetch the selected tab inside the transaction with a row
                # lock: a comanda closed between render and submit must not
                # collect another round.
                tab = Tab.objects.select_for_update().get(
                    pk=tab.pk, status=Tab.Status.OPEN
                )

                # Lock each item row before validating the demand so two
                # concurrent orders cannot both pass the stock check and then
                # oversell.
                items_by_pk: dict[int, Item] = {}
                for item_pk in demanded.keys():
                    item = Item.objects.select_for_update().get(pk=item_pk)
                    if not item.is_active or item.stock <= 0:
                        raise ValueError(
                            _('"{}" não está mais disponível para venda.').format(
                                item.name
                            )
                        )
                    items_by_pk[item_pk] = item

                # Validate every line against current stock before writing
                # anything; the first overflow raises and aborts the whole
                # transaction.
                for item_pk, total_qty in demanded.items():
                    item = items_by_pk[item_pk]
                    if total_qty > item.stock:
                        raise ValueError(
                            _(
                                'Estoque insuficiente para "{}": solicitado {}, '
                                "disponível {}."
                            ).format(item.name, total_qty, item.stock)
                        )

                # All lines validated — write the order against the tab,
                # snapshot the prices and decrement stock using the locked
                # instances. The table rides along untouched, if there is one.
                order = Order.objects.create(
                    tab=tab,
                    table=table,
                    status=Order.Status.OPEN,
                )
                for item, quantity, notes in lines:
                    OrderItem.objects.create(
                        order=order,
                        item=item,
                        quantity=quantity,
                        unit_price=items_by_pk[item.pk].price,
                        notes=notes,
                    )
                    locked = items_by_pk[item.pk]
                    locked.stock -= quantity
                    locked.save(update_fields=["stock", "updated_at"])
        except Tab.DoesNotExist:
            order_form.add_error("tab", _("Comanda inválida ou já fechada."))
            return self._render(request, order_form, formset, status=400)
        except ValueError as exc:
            form_errors.append(str(exc))
            return self._render(
                request, order_form, formset, form_errors=form_errors, status=400
            )

        messages.success(
            request,
            _('Pedido #{} registrado na comanda "{}" — estoque atualizado.').format(
                order.pk, tab.name
            ),
        )
        return redirect(reverse_lazy("orders:order-create"))


def _kitchen_items_prefetch():
    """Prefetch only the order lines whose item needs kitchen preparation.

    The kitchen screen and the printed ticket both walk ``order.items.all``;
    since #233 an item may be flagged ``requires_kitchen_preparation=False``
    (a serve-direct drink or shelf snack), and such a line must never reach
    the kitchen surfaces. Filtering at the prefetch level means every order
    handed to the kitchen already carries only its kitchen lines, with no
    template change — and orders whose prefetch comes back empty are dropped
    by :func:`_open_orders_queryset` so a drinks-only round never renders a
    card.
    """
    return Prefetch(
        "items",
        queryset=OrderItem.objects.filter(
            item__requires_kitchen_preparation=True
        ).select_related("item"),
    )


def _open_orders_queryset():
    """Open orders with at least one kitchen line, oldest first.

    The kitchen screen works top-down so the oldest ticket is always at the
    top of the pile. Prefetching only the kitchen lines (and the item's name)
    keeps the polling endpoint to a single query per refresh and means the
    template's ``order.items.all`` already carries only what the cook needs.

    Orders whose kitchen-line prefetch comes back empty are dropped here, so a
    serve-direct-only round never renders a blank card — the order stays open
    and visible on the comanda, just not on the kitchen screen.
    """
    qs = (
        Order.objects.filter(status=Order.Status.OPEN)
        .select_related("tab", "table")
        .prefetch_related(_kitchen_items_prefetch())
        .order_by("created_at")
    )
    return [order for order in qs if order.items.all()]


class KitchenView(LoginRequiredMixin, View):
    """Kitchen-facing screen listing every open order oldest-first.

    The page renders the full grid of open orders as large Bootstrap cards.
    A companion polling endpoint (:class:`KitchenQueueView`) returns just the
    cards fragment so a small piece of plain JavaScript can swap it in every
    few seconds without a full reload.
    """

    template_name = "orders/kitchen.html"
    extra_context = {"title": "Cozinha"}

    def get(self, request, *args, **kwargs):
        orders = list(_open_orders_queryset())
        context = {
            "title": self.extra_context["title"],
            "orders": orders,
        }
        return render(request, self.template_name, context)


class KitchenQueueView(LoginRequiredMixin, View):
    """Polling endpoint that returns the rendered cards fragment.

    Returns an HTML fragment (the ``orders/_kitchen_queue.html`` partial)
    so the kitchen page's JavaScript can simply swap ``innerHTML`` of the
    grid container with the response body. No JSON, no JS framework.
    """

    template_name = "orders/_kitchen_queue.html"

    def get(self, request, *args, **kwargs):
        orders = list(_open_orders_queryset())
        return render(
            request,
            self.template_name,
            {"orders": orders},
        )


class OrderDoneView(LoginRequiredMixin, View):
    """Flip a single order's status from ``open`` to ``done``.

    Reached from the ``Done`` button on each kitchen card. Only the
    ``status`` field is updated; neither the tab nor the table is touched
    (closing a comanda is its own action on /comandas/). Unknown or already
    done orders are treated as gone and silently redirect back to the screen
    so a stale poll cannot raise a 404 in the kitchen's face.
    """

    def post(self, request, pk, *args, **kwargs):
        order = get_object_or_404(Order, pk=pk)
        if order.status == Order.Status.OPEN:
            order.status = Order.Status.DONE
            order.save(update_fields=["status", "updated_at"])
        return redirect(reverse("orders:kitchen"))


class OrderPrintView(LoginRequiredMixin, View):
    """POST-only endpoint that sends an order's kitchen ticket to the printer.

    Reached from the "Imprimir" button on each kitchen card. It composes the
    ESC/POS bytes and hands them to :func:`orders.services.printer.print_raw`,
    which either reaches the hardware or — with ``KARAOKE_PRINTER_DRY_RUN=1`` —
    dumps the ticket to disk so the flow can be exercised without a printer.

    Printing is deliberately read-only with respect to the order: the status is
    never touched, so re-printing a lost ticket does not take the card off the
    kitchen screen. Only "Pronto" does that.

    Replies in JSON so the kitchen JavaScript can show the outcome inline:
    ``200`` with the printer's message on success, ``503`` with the error text
    when no printer answered — never a silent failure.
    """

    def post(self, request, pk, *args, **kwargs):
        # Prefetch the lines the way the queue does — only kitchen lines — so
        # the ticket and the screen always agree on what to prepare. An unknown
        # order is a plain 404 (a stale card, most likely).
        order = get_object_or_404(
            Order.objects.select_related("tab", "table").prefetch_related(
                _kitchen_items_prefetch()
            ),
            pk=pk,
        )
        payload = kitchen_receipt_bytes(order)

        try:
            result = print_raw(payload, label=f"pedido-{order.pk}-cozinha")
        except PrinterError as exc:
            # 503: the app is fine, the printer is not. The UI shows this text
            # verbatim so whoever is at the pass knows what to check.
            return JsonResponse({"success": False, "error": str(exc)}, status=503)

        return JsonResponse(
            {
                "success": True,
                "message": _("Pedido #{} enviado para a impressora. {}").format(
                    order.pk, result.message
                ),
            }
        )
