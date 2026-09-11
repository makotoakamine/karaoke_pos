"""Views for the orders app.

The order-taking page (``/pedidos/novo/``) is the app's central waiter flow.
It renders a tab selector — plus an optional table, purely as delivery
context — and a formset of item lines. On POST the whole submission runs
inside a single transaction: the chosen tab is re-read under a row lock and
must still be open, each requested quantity is validated against current stock
before anything is written, the items' stock counts are decremented, and the
order with its lines is created. If any single line exceeds stock the whole
submission is rejected with a clear form error and nothing is changed.

Since #225 the same view also hands the template the raw picker data — the
open tabs, the sellable catalogue and its categories — so the touch UI can
filter client-side without a second endpoint. The POST contract is unchanged:
the picker is a layer over the very same form fields and formset.

Table occupancy is deliberately not touched here (#224): the table is now only
a hint for the waiter, and ``tables.Table.status`` is owned by the tables
screens alone.
"""
from typing import Iterable, Tuple

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import View

from inventory.models import Category, Item
from tabs.models import Tab

from .forms import OrderForm, OrderItemLineFormSet
from .models import Order, OrderItem


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
    """The sellable catalogue, alphabetically, with each item's category.

    Mirrors ``OrderItemLineForm.item``'s queryset: active items with stock
    above zero, nothing else. The category rides along so the client-side
    chips can filter the rendered list without another request.
    """
    return list(
        Item.objects.filter(is_active=True, stock__gt=0)
        .select_related("category")
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
        # that line in).
        lines: list[Tuple[Item, int]] = []
        for line in formset.cleaned_data:
            if not line:
                continue
            item = line.get("item")
            quantity = line.get("quantity")
            if not item or not quantity:
                continue
            lines.append((item, quantity))

        if not lines:
            return self._render(
                request, order_form, formset,
                form_errors=[_("Adicione ao menos um item ao pedido.")],
                status=400,
            )

        # Aggregate quantities per item so a waiter entering the same item on
        # two lines still validates the combined demand against current stock.
        demanded: dict[int, int] = {}
        for item, quantity in lines:
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
                for item, quantity in lines:
                    OrderItem.objects.create(
                        order=order,
                        item=item,
                        quantity=quantity,
                        unit_price=items_by_pk[item.pk].price,
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


def _open_orders_queryset():
    """Open orders, oldest first, with their tab, table and items prefetched.

    The kitchen screen works top-down so the oldest ticket is always at the
    top of the pile. Prefetching the items and the item's name keeps the
    polling endpoint to a single query per refresh.
    """
    return (
        Order.objects.filter(status=Order.Status.OPEN)
        .select_related("tab", "table")
        .prefetch_related("items__item")
        .order_by("created_at")
    )


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