"""Functional tests for the orders app covering the task's acceptance criteria."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from inventory.models import Item
from orders.forms import OrderForm
from orders.models import Order, OrderItem
from tables.models import Table
from tabs.models import Tab


class OrderCreateViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")
        cls.tab = Tab.objects.create(name="Comanda Ana")
        cls.closed_tab = Tab.objects.create(
            name="Comanda encerrada", status=Tab.Status.CLOSED
        )
        cls.table = Table.objects.create(name="Mesa 1", seats=4)
        cls.inactive_table = Table.objects.create(
            name="Mesa aposentada", seats=2, is_active=False
        )
        cls.item = Item.objects.create(
            name="Cerveja", price=Decimal("8.50"), stock=10
        )
        cls.inactive = Item.objects.create(
            name="Desativado",
            price=Decimal("2.00"),
            stock=5,
            is_active=False,
        )
        cls.zero = Item.objects.create(
            name="Sem estoque", price=Decimal("3.00"), stock=0
        )

    def setUp(self):
        self.client.force_login(self.user)

    # --- acceptance: login required ----------------------------------------

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("orders:order-create"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("next=", resp["Location"])

    def test_anonymous_post_redirected_to_login(self):
        self.client.logout()
        resp = self.client.post(
            reverse("orders:order-create"),
            {
                "tab": self.tab.pk,
                "table": self.table.pk,
                "lines-TOTAL_FORMS": "1",
                "lines-INITIAL_FORMS": "0",
                "lines-MIN_NUM_FORMS": "0",
                "lines-MAX_NUM_FORMS": "1000",
                "lines-0-item": self.item.pk,
                "lines-0-quantity": "1",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("next=", resp["Location"])
        # nothing should have changed for an anonymous visitor
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 10)
        self.assertFalse(Order.objects.exists())

    # --- acceptance: only active items with stock > 0 are offered -----------

    def test_picker_offers_only_active_with_stock(self):
        resp = self.client.get(reverse("orders:order-create"))
        body = resp.content.decode()
        self.assertIn("Cerveja", body)
        self.assertNotIn("Desativado", body)
        self.assertNotIn("Sem estoque", body)

    def test_picker_offers_no_zero_stock_option(self):
        Item.objects.filter(pk=self.zero.pk).update(stock=0)
        resp = self.client.get(reverse("orders:order-create"))
        body = resp.content.decode()
        self.assertNotIn("Sem estoque", body)

    # --- helper to build a formset POST ------------------------------------

    #: Sentinel telling :meth:`_post_lines` to leave a selector out entirely,
    #: as the browser does when nothing is picked.
    BLANK = object()

    def _post_lines(self, lines, tab_pk=None, table_pk=None):
        data = {
            "tab": self.tab.pk if tab_pk is None else tab_pk,
            "table": self.table.pk if table_pk is None else table_pk,
            "lines-TOTAL_FORMS": str(len(lines)),
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
        }
        if data["tab"] is self.BLANK:
            data["tab"] = ""
        if data["table"] is self.BLANK:
            data["table"] = ""
        for i, (item_pk, qty) in enumerate(lines):
            data[f"lines-{i}-item"] = item_pk
            data[f"lines-{i}-quantity"] = qty
        return self.client.post(reverse("orders:order-create"), data)

    # --- acceptance: valid order creates Order + OrderItems, snaps price ---

    def test_valid_order_creates_order_with_items_and_snapshotted_price(self):
        resp = self._post_lines([(self.item.pk, 2)])
        self.assertEqual(resp.status_code, 302)

        order = Order.objects.get()
        self.assertEqual(order.status, "open")
        self.assertEqual(order.tab_id, self.tab.pk)
        self.assertEqual(order.table_id, self.table.pk)
        self.assertEqual(order.items.count(), 1)
        line = order.items.get()
        self.assertEqual(line.item_id, self.item.pk)
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.unit_price, Decimal("8.50"))

    def test_price_snapshot_is_not_rewritten_when_item_price_changes(self):
        self._post_lines([(self.item.pk, 1)])
        self.item.price = Decimal("99.99")
        self.item.save()
        line = OrderItem.objects.get()
        # the historical line keeps the snapshot taken at order time
        self.assertEqual(line.unit_price, Decimal("8.50"))

    def test_success_message_names_the_tab(self):
        resp = self._post_lines([(self.item.pk, 1)], table_pk=self.BLANK)
        resp = self.client.get(resp["Location"])
        self.assertContains(resp, "Comanda Ana")

    # --- acceptance: stock is decremented by the ordered quantity -----------

    def test_stock_is_decremented_by_ordered_quantity(self):
        self._post_lines([(self.item.pk, 3)])
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 7)

    # --- acceptance: the tab is mandatory ----------------------------------

    def test_order_without_tab_is_rejected_and_writes_nothing(self):
        resp = self._post_lines([(self.item.pk, 2)], tab_pk=self.BLANK)
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Selecione a comanda", status_code=400)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(OrderItem.objects.exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 10)

    def test_unknown_tab_is_rejected(self):
        resp = self._post_lines([(self.item.pk, 1)], tab_pk=999999)
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Comanda inválida", status_code=400)
        self.assertFalse(Order.objects.exists())

    def test_closed_tab_is_absent_from_the_selector(self):
        body = self.client.get(reverse("orders:order-create")).content.decode()
        self.assertIn("Comanda Ana", body)
        self.assertNotIn("Comanda encerrada", body)

    def test_closed_tab_posted_directly_is_rejected(self):
        resp = self._post_lines([(self.item.pk, 1)], tab_pk=self.closed_tab.pk)
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Comanda inválida", status_code=400)
        self.assertFalse(Order.objects.exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 10)

    def test_view_rejects_a_tab_closed_after_the_form_accepted_it(self):
        """The view re-validates the tab under a lock, not just the form.

        Widening the form's queryset simulates a comanda closed between render
        and submit: the submission must still be refused, with nothing written.
        """
        field = OrderForm.base_fields["tab"]
        original = field.queryset
        field.queryset = Tab.objects.all()
        try:
            resp = self._post_lines([(self.item.pk, 1)], tab_pk=self.closed_tab.pk)
        finally:
            field.queryset = original
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Comanda inválida", status_code=400)
        self.assertFalse(Order.objects.exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 10)

    # --- acceptance: the table is optional context, never written to -------

    def test_order_without_a_table_is_saved(self):
        resp = self._post_lines([(self.item.pk, 2)], table_pk=self.BLANK)
        self.assertEqual(resp.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.tab_id, self.tab.pk)
        self.assertIsNone(order.table_id)
        self.assertEqual(order.items.count(), 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 8)

    def test_order_with_a_table_stores_it_without_touching_its_status(self):
        self.assertEqual(self.table.status, "free")
        resp = self._post_lines([(self.item.pk, 1)])
        self.assertEqual(resp.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.table_id, self.table.pk)
        # ordering is no longer what makes a table occupied (#224)
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, "free")

    def test_order_leaves_an_already_occupied_table_occupied(self):
        Table.objects.filter(pk=self.table.pk).update(
            status=Table.Status.OCCUPIED
        )
        resp = self._post_lines([(self.item.pk, 1)])
        self.assertEqual(resp.status_code, 302)
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, "occupied")

    def test_table_selector_offers_an_empty_option_and_only_active_tables(self):
        body = self.client.get(reverse("orders:order-create")).content.decode()
        self.assertIn("Sem mesa", body)
        self.assertIn("Mesa 1", body)
        self.assertNotIn("Mesa aposentada", body)

    def test_inactive_table_posted_directly_is_rejected(self):
        resp = self._post_lines(
            [(self.item.pk, 1)], table_pk=self.inactive_table.pk
        )
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Mesa inválida", status_code=400)
        self.assertFalse(Order.objects.exists())

    # --- acceptance: oversell is rejected with a visible error, nothing changes

    def test_oversell_rejected_with_visible_error(self):
        resp = self._post_lines([(self.item.pk, 11)])
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Estoque insuficiente", status_code=400)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(OrderItem.objects.exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 10)

    def test_oversell_on_one_line_rejects_whole_order(self):
        # line 1 would fit, line 2 overflows — whole submission must fail.
        resp = self._post_lines([(self.item.pk, 5), (self.item.pk, 6)])
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Estoque insuficiente", status_code=400)
        self.assertFalse(Order.objects.exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 10)

    def test_duplicate_item_lines_aggregate_demand_against_stock(self):
        # Two lines of the same item that together exceed stock must reject.
        resp = self._post_lines([(self.item.pk, 6), (self.item.pk, 6)])
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Estoque insuficiente", status_code=400)
        self.assertFalse(Order.objects.exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 10)

    def test_duplicate_item_lines_aggregate_within_stock_succeeds(self):
        # Two lines of the same item that together fit must succeed.
        resp = self._post_lines([(self.item.pk, 4), (self.item.pk, 3)])
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 3)
        self.assertEqual(OrderItem.objects.count(), 2)
        order = Order.objects.get()
        self.assertEqual(order.items.count(), 2)

    # --- acceptance: more rounds on the same open tab ----------------------

    def test_second_order_against_the_same_open_tab_succeeds(self):
        self._post_lines([(self.item.pk, 2)])
        # extra round on the comanda that is already collecting orders
        resp = self._post_lines([(self.item.pk, 1)])
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Order.objects.count(), 2)
        self.assertEqual(Order.objects.filter(tab=self.tab).count(), 2)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 7)
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, "free")

    # --- acceptance: page extends base.html and uses Bootstrap styling -----

    def test_page_extends_base_html(self):
        resp = self.client.get(reverse("orders:order-create"))
        self.assertTemplateUsed(resp, "base.html")
        self.assertTemplateUsed(resp, "orders/order_form.html")

    def test_page_renders_bootstrap_classes(self):
        resp = self.client.get(reverse("orders:order-create"))
        body = resp.content.decode()
        self.assertIn("card", body)
        self.assertIn("btn-primary", body)
        self.assertIn("container", body)

    def test_page_keeps_plain_select_controls_for_tab_and_table(self):
        """#225 owns the touch-friendly picker; this round stays a select."""
        body = self.client.get(reverse("orders:order-create")).content.decode()
        self.assertIn('<select name="tab"', body)
        self.assertIn('<select name="table"', body)
        self.assertIn("form-select", body)

    # --- sanity: invalid form fields keep nothing in the DB ----------------

    def test_no_items_submitted_rejected(self):
        data = {
            "tab": self.tab.pk,
            "table": self.table.pk,
            "lines-TOTAL_FORMS": "1",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-item": "",
            "lines-0-quantity": "",
        }
        resp = self.client.post(reverse("orders:order-create"), data)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Order.objects.exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 10)

    def test_inactive_item_rejected(self):
        resp = self._post_lines([(self.inactive.pk, 1)])
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_zero_stock_item_rejected(self):
        resp = self._post_lines([(self.zero.pk, 1)])
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Order.objects.exists())

    # --- navigation ---------------------------------------------------------

    def test_home_links_to_order_create(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, reverse("orders:order-create"))

    def test_navbar_links_to_order_create(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, reverse("orders:order-create"))


class OrderModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tab = Tab.objects.create(name="Comanda Bruno")
        cls.table = Table.objects.create(name="Mesa 2", seats=2)
        cls.item = Item.objects.create(name="Refrigerante", price=Decimal("6.00"), stock=4)

    def test_new_order_defaults_open(self):
        order = Order.objects.create(tab=self.tab)
        self.assertEqual(order.status, "open")
        self.assertEqual(order.status, Order.Status.OPEN)

    def test_order_str_leads_with_the_tab_name(self):
        order = Order.objects.create(tab=self.tab, table=self.table)
        self.assertIn("Comanda Bruno", str(order))

    def test_order_table_is_optional(self):
        order = Order.objects.create(tab=self.tab)
        self.assertIsNone(order.table_id)

    def test_tab_with_orders_cannot_be_deleted(self):
        Order.objects.create(tab=self.tab)
        with self.assertRaises(ProtectedError):
            self.tab.delete()

    def test_table_with_orders_cannot_be_deleted(self):
        Order.objects.create(tab=self.tab, table=self.table)
        with self.assertRaises(ProtectedError):
            self.table.delete()

    def test_order_item_snapshots_unit_price(self):
        order = Order.objects.create(tab=self.tab)
        OrderItem.objects.create(
            order=order, item=self.item, quantity=2, unit_price=self.item.price
        )
        self.item.price = Decimal("7.50")
        self.item.save()
        line = OrderItem.objects.get()
        self.assertEqual(line.unit_price, Decimal("6.00"))


class KitchenViewTests(TestCase):
    """Acceptance tests for the kitchen screen and its polling endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")
        cls.tab_a = Tab.objects.create(name="Comanda Ana")
        cls.tab_b = Tab.objects.create(name="Comanda Bruno")
        cls.table_a = Table.objects.create(name="Mesa 1", seats=4)
        cls.table_b = Table.objects.create(name="Mesa 2", seats=2)
        cls.item = Item.objects.create(
            name="Cerveja", price=Decimal("8.50"), stock=20
        )
        cls.item2 = Item.objects.create(
            name="Porção", price=Decimal("25.00"), stock=10
        )

    def setUp(self):
        self.client.force_login(self.user)

    # --- helpers -----------------------------------------------------------

    def _make_order(
        self, tab, lines, table=None, status=Order.Status.OPEN, created_at=None
    ):
        order = Order.objects.create(tab=tab, table=table, status=status)
        if created_at is not None:
            Order.objects.filter(pk=order.pk).update(created_at=created_at)
        for item, qty in lines:
            OrderItem.objects.create(
                order=order, item=item, quantity=qty, unit_price=item.price
            )
        return order

    # --- acceptance: login required ----------------------------------------

    def test_anonymous_kitchen_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("orders:kitchen"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("next=", resp["Location"])

    def test_anonymous_polling_endpoint_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("orders:kitchen-queue"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("next=", resp["Location"])

    def test_anonymous_done_post_redirected_to_login(self):
        self.client.logout()
        order = self._make_order(self.tab_a, [(self.item, 1)])
        resp = self.client.post(reverse("orders:order-done", args=[order.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("next=", resp["Location"])
        # state must not change for anonymous users
        order.refresh_from_db()
        self.assertEqual(order.status, "open")

    # --- acceptance: open orders oldest-first -----------------------------

    def test_kitchen_lists_open_orders_oldest_first(self):
        older = self._make_order(
            self.tab_a, [(self.item, 2)], table=self.table_a,
            created_at=timezone.now() - timezone.timedelta(minutes=10),
        )
        newer = self._make_order(
            self.tab_b, [(self.item2, 1)],
            created_at=timezone.now() - timezone.timedelta(minutes=1),
        )
        resp = self.client.get(reverse("orders:kitchen"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # older order appears before newer order in the response body
        self.assertLess(body.index(f"#{older.pk}"), body.index(f"#{newer.pk}"))

    def test_kitchen_headlines_the_tab_and_lists_time_and_quantities(self):
        order = self._make_order(
            self.tab_a, [(self.item, 3), (self.item2, 1)], table=self.table_a
        )
        resp = self.client.get(reverse("orders:kitchen"))
        body = resp.content.decode()
        # the tab name is the card headline
        self.assertIn(
            f'<h2 class="karaoke-title">{self.tab_a.name}</h2>', body
        )
        self.assertContains(resp, "Cerveja")
        self.assertContains(resp, "3x")
        self.assertContains(resp, "Porção")
        self.assertContains(resp, "1x")
        # the placed time is rendered (HH:MM) in the project's local tz
        self.assertContains(
            resp, timezone.localtime(order.created_at).strftime("%H:%M")
        )

    def test_kitchen_shows_the_table_under_the_tab_when_the_order_has_one(self):
        self._make_order(self.tab_a, [(self.item, 1)], table=self.table_a)
        body = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertIn(
            f'<p class="kitchen-card-table">{self.table_a.name}</p>', body
        )
        # the tab still leads the card
        self.assertLess(
            body.index(self.tab_a.name), body.index("kitchen-card-table")
        )

    def test_kitchen_order_without_a_table_renders_only_the_tab_headline(self):
        self._make_order(self.tab_b, [(self.item, 1)])
        body = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertIn(
            f'<h2 class="karaoke-title">{self.tab_b.name}</h2>', body
        )
        # no empty table line is emitted for a table-less order
        self.assertNotIn("kitchen-card-table", body)

    def test_done_orders_are_not_listed(self):
        done = self._make_order(
            self.tab_a, [(self.item, 1)], status=Order.Status.DONE
        )
        open_order = self._make_order(self.tab_b, [(self.item, 1)])
        resp = self.client.get(reverse("orders:kitchen"))
        body = resp.content.decode()
        self.assertNotIn(f"#{done.pk}", body)
        self.assertIn(f"#{open_order.pk}", body)

    # --- acceptance: polling endpoint returns open orders only ------------

    def test_polling_endpoint_returns_open_orders_fragment(self):
        older = self._make_order(
            self.tab_a, [(self.item, 2)],
            created_at=timezone.now() - timezone.timedelta(minutes=5),
        )
        newer = self._make_order(
            self.tab_b, [(self.item2, 1)], created_at=timezone.now()
        )
        resp = self.client.get(reverse("orders:kitchen-queue"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # both open orders present, oldest first
        self.assertLess(body.index(f"#{older.pk}"), body.index(f"#{newer.pk}"))
        # contains the Done button form pointing at the right endpoint
        self.assertIn(
            reverse("orders:order-done", args=[older.pk]), body
        )

    def test_polling_fragment_headlines_the_tab_and_shows_the_table_below(self):
        self._make_order(self.tab_a, [(self.item, 1)], table=self.table_a)
        body = self.client.get(reverse("orders:kitchen-queue")).content.decode()
        self.assertIn(
            f'<h2 class="karaoke-title">{self.tab_a.name}</h2>', body
        )
        self.assertIn(
            f'<p class="kitchen-card-table">{self.table_a.name}</p>', body
        )

    def test_polling_fragment_omits_the_table_line_when_there_is_none(self):
        self._make_order(self.tab_b, [(self.item, 1)])
        body = self.client.get(reverse("orders:kitchen-queue")).content.decode()
        self.assertIn(
            f'<h2 class="karaoke-title">{self.tab_b.name}</h2>', body
        )
        self.assertNotIn("kitchen-card-table", body)

    def test_polling_endpoint_excludes_done_orders(self):
        done = self._make_order(
            self.tab_a, [(self.item, 1)], status=Order.Status.DONE
        )
        open_order = self._make_order(self.tab_b, [(self.item, 1)])
        resp = self.client.get(reverse("orders:kitchen-queue"))
        body = resp.content.decode()
        self.assertNotIn(f"#{done.pk}", body)
        self.assertIn(f"#{open_order.pk}", body)

    def test_polling_endpoint_empty_state(self):
        # no open orders -> empty-state markup
        resp = self.client.get(reverse("orders:kitchen-queue"))
        self.assertContains(resp, "Sem pedidos abertos")

    # --- acceptance: Done flips status and order disappears ---------------

    def test_done_post_flips_status_to_done(self):
        order = self._make_order(self.tab_a, [(self.item, 1)])
        resp = self.client.post(reverse("orders:order-done", args=[order.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("orders:kitchen"))
        order.refresh_from_db()
        self.assertEqual(order.status, "done")

    def test_done_order_disappears_from_kitchen_after_post(self):
        order = self._make_order(self.tab_a, [(self.item, 1)])
        self.client.post(reverse("orders:order-done", args=[order.pk]))
        resp = self.client.get(reverse("orders:kitchen"))
        body = resp.content.decode()
        self.assertNotIn(f"#{order.pk}", body)

    def test_done_order_does_not_reappear_on_later_polls(self):
        order = self._make_order(self.tab_a, [(self.item, 1)])
        self.client.post(reverse("orders:order-done", args=[order.pk]))
        resp = self.client.get(reverse("orders:kitchen-queue"))
        body = resp.content.decode()
        self.assertNotIn(f"#{order.pk}", body)

    def test_done_post_on_already_done_order_is_idempotent(self):
        order = self._make_order(
            self.tab_a, [(self.item, 1)], status=Order.Status.DONE
        )
        resp = self.client.post(reverse("orders:order-done", args=[order.pk]))
        self.assertEqual(resp.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "done")

    def test_done_post_on_unknown_order_returns_404(self):
        resp = self.client.post(reverse("orders:order-done", args=[999999]))
        self.assertEqual(resp.status_code, 404)

    def test_done_touches_neither_the_tab_nor_the_table(self):
        # kitchen Done is about the ticket only: the comanda stays open and the
        # table keeps whatever status the tables screen gave it.
        Table.objects.filter(pk=self.table_a.pk).update(
            status=Table.Status.OCCUPIED
        )
        order = self._make_order(self.tab_a, [(self.item, 1)], table=self.table_a)
        self.client.post(reverse("orders:order-done", args=[order.pk]))
        self.table_a.refresh_from_db()
        self.assertEqual(self.table_a.status, "occupied")
        self.tab_a.refresh_from_db()
        self.assertEqual(self.tab_a.status, "open")

    # --- acceptance: page extends base.html and uses Bootstrap ------------

    def test_kitchen_page_extends_base_html(self):
        resp = self.client.get(reverse("orders:kitchen"))
        self.assertTemplateUsed(resp, "base.html")
        self.assertTemplateUsed(resp, "orders/kitchen.html")

    def test_kitchen_page_renders_bootstrap_cards(self):
        self._make_order(self.tab_a, [(self.item, 1)])
        resp = self.client.get(reverse("orders:kitchen"))
        body = resp.content.decode()
        self.assertIn("card", body)
        self.assertIn("btn-success", body)
        self.assertIn("container", body)

    def test_kitchen_page_contains_polling_script(self):
        resp = self.client.get(reverse("orders:kitchen"))
        body = resp.content.decode()
        self.assertIn(reverse("orders:kitchen-queue"), body)
        self.assertIn("setInterval", body)

    # --- acceptance: elapsed-time escalation (#204) ------------------------

    def test_fresh_order_card_is_not_escalated(self):
        self._make_order(
            self.tab_a,
            [(self.item, 1)],
            created_at=timezone.now() - timezone.timedelta(minutes=2),
        )
        body = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertNotIn("kitchen-card-late", body)
        self.assertNotIn("kitchen-card-overdue", body)

    def test_order_older_than_fifteen_minutes_is_escalated(self):
        self._make_order(
            self.tab_a,
            [(self.item, 1)],
            created_at=timezone.now() - timezone.timedelta(minutes=16),
        )
        body = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertIn("kitchen-card-late", body)
        self.assertNotIn("kitchen-card-overdue", body)

    def test_order_older_than_thirty_minutes_escalates_further(self):
        self._make_order(
            self.tab_a,
            [(self.item, 1)],
            created_at=timezone.now() - timezone.timedelta(minutes=45),
        )
        body = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertIn("kitchen-card-overdue", body)
        self.assertNotIn("kitchen-card-late", body)

    def test_polling_fragment_also_escalates_old_orders(self):
        """The escalation lives in the partial, so the poll must carry it too."""
        self._make_order(
            self.tab_a,
            [(self.item, 1)],
            created_at=timezone.now() - timezone.timedelta(minutes=20),
        )
        body = self.client.get(reverse("orders:kitchen-queue")).content.decode()
        self.assertIn("kitchen-card-late", body)

    # --- navigation --------------------------------------------------------

    def test_navbar_links_to_kitchen(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, reverse("orders:kitchen"))

    def test_home_links_to_kitchen(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, reverse("orders:kitchen"))
