"""Views for the orders app.

The order-taking page (``/pedidos/novo/``) is the app's central waiter flow.
It renders a table selector plus a formset of item lines. On POST the whole
submission runs inside a single transaction: each requested quantity is
validated against current stock before anything is written, the items'
stock counts are decremented, the order with its lines is created, and the
chosen table's status is flipped to occupied. If any single line exceeds
stock the whole submission is rejected with a clear form error and nothing
is changed.
"""
from typing import Iterable, Tuple

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import View

from inventory.models import Item
from tables.models import Table

from .forms import OrderForm, OrderItemLineFormSet
from .models import Order, OrderItem


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

        table = order_form.cleaned_data["table"]

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
                # Re-fetch the selected table inside the transaction with a
                # row lock so the occupancy flip is the row we mutate.
                table = Table.objects.select_for_update().get(
                    pk=table.pk, is_active=True
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

                # All lines validated — write the order, snapshot the prices,
                # decrement stock using the locked instances, and occupy the
                # table.
                order = Order.objects.create(
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

                table.status = Table.Status.OCCUPIED
                table.save(update_fields=["status", "updated_at"])
        except Table.DoesNotExist:
            order_form.add_error("table", _("Mesa inválida ou inativa."))
            return self._render(request, order_form, formset, status=400)
        except ValueError as exc:
            form_errors.append(str(exc))
            return self._render(
                request, order_form, formset, form_errors=form_errors, status=400
            )

        messages.success(
            request,
            _('Pedido #{} registrado para a mesa "{}" — estoque atualizado.').format(
                order.pk, table.name
            ),
        )
        return redirect(reverse_lazy("orders:order-create"))