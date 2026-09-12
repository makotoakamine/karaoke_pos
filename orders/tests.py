"""Functional tests for the orders app covering the task's acceptance criteria."""
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from inventory.models import Category, Item, NoteSuggestion
from orders import urls as orders_urls
from orders.forms import OrderForm
from orders.models import Order, OrderItem
from orders.services.printer import PrinterError
from orders.services.receipts import ReceiptBuilder, normalize_text, strip_escpos
from orders.views import OrderCreateView
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
        cls.category = Category.objects.create(name="bebidas")
        cls.item = Item.objects.create(
            name="Cerveja",
            category=cls.category,
            price=Decimal("8.50"),
            stock=10,
            requires_kitchen_preparation=False,
        )
        cls.inactive = Item.objects.create(
            name="Desativado",
            category=cls.category,
            price=Decimal("2.00"),
            stock=5,
            is_active=False,
        )
        cls.zero = Item.objects.create(
            name="Sem estoque", category=cls.category, price=Decimal("3.00"), stock=0
        )
        cls.food = Item.objects.create(
            name="Porção",
            category=cls.category,
            price=Decimal("25.00"),
            stock=8,
            requires_kitchen_preparation=True,
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
        # A kitchen item so the order starts open — the serve-direct case is
        # covered by the #235 suite below.
        resp = self._post_lines([(self.food.pk, 2)])
        self.assertEqual(resp.status_code, 302)

        order = Order.objects.get()
        self.assertEqual(order.status, "open")
        self.assertEqual(order.tab_id, self.tab.pk)
        self.assertEqual(order.table_id, self.table.pk)
        self.assertEqual(order.items.count(), 1)
        line = order.items.get()
        self.assertEqual(line.item_id, self.food.pk)
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.unit_price, Decimal("25.00"))

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
        """The picker (#225) is a layer over the real fields, not a substitute.

        The selects are still rendered — the picker only hides the tab one and
        drives it — so a browser with scripting off gets working controls and
        the POST contract never changes.
        """
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

    # --- acceptance: serve-direct orders start done, kitchen orders open (#235)

    def test_drinks_only_order_starts_done(self):
        """An order whose lines are all serve-direct is created ``done``.

        The kitchen has nothing to prepare, so the order never appears on the
        kitchen screen and never needs the "Pronto" button.
        """
        resp = self._post_lines([(self.item.pk, 2)])
        self.assertEqual(resp.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.status, "done")

    def test_drinks_only_order_still_decrements_stock_and_snapshots_price(self):
        """A serve-direct order is recorded exactly like an open one, only the
        starting status differs: stock moves and the unit price is snapshotted
        from the locked item just the same."""
        self._post_lines([(self.item.pk, 3)])
        order = Order.objects.get()
        self.assertEqual(order.status, "done")
        line = order.items.get()
        self.assertEqual(line.unit_price, Decimal("8.50"))
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 7)

    def test_mixed_order_starts_open(self):
        """A line that needs the kitchen is enough to keep the order ``open``."""
        resp = self._post_lines([(self.item.pk, 1), (self.food.pk, 1)])
        self.assertEqual(resp.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.status, "open")

    def test_all_kitchen_order_starts_open(self):
        """An order where every line needs preparation is unchanged: ``open``."""
        resp = self._post_lines([(self.food.pk, 1)])
        self.assertEqual(resp.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.status, "open")

    def test_drinks_only_order_with_two_serve_direct_lines_starts_done(self):
        """Multiple serve-direct lines still resolve to ``done``."""
        other_drink = Item.objects.create(
            name="Refrigerante",
            category=self.category,
            price=Decimal("6.00"),
            stock=5,
            requires_kitchen_preparation=False,
        )
        resp = self._post_lines([(self.item.pk, 1), (other_drink.pk, 1)])
        self.assertEqual(resp.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.status, "done")
        self.assertEqual(order.items.count(), 2)

    def test_drinks_only_order_reaches_the_tab_detail(self):
        """The tab detail page still lists the drinks-only order with its lines."""
        self._post_lines([(self.item.pk, 2)])
        order = Order.objects.get()
        detail = self.client.get(
            reverse("tabs:tab-detail", args=[self.tab.pk])
        ).content.decode()
        self.assertIn(f"#{order.pk}", detail)
        self.assertIn("Cerveja", detail)

    # --- acceptance: rejected submissions still write nothing (#235 guard) --

    def test_drinks_only_oversell_is_rejected_and_writes_nothing(self):
        """A serve-direct line that overflows stock must reject like any other."""
        resp = self._post_lines([(self.item.pk, 11)])
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Estoque insuficiente", status_code=400)
        self.assertFalse(Order.objects.exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 10)

    def test_closed_tab_with_drinks_only_is_rejected_and_writes_nothing(self):
        resp = self._post_lines(
            [(self.item.pk, 1)], tab_pk=self.closed_tab.pk
        )
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Comanda inválida", status_code=400)
        self.assertFalse(Order.objects.exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 10)

    # --- navigation ---------------------------------------------------------

    def test_home_links_to_order_create(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, reverse("orders:order-create"))

    def test_navbar_links_to_order_create(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, reverse("orders:order-create"))


class OrderPickerDataTests(TestCase):
    """What /pedidos/novo/ hands the client for the touch picker (#225).

    The picker itself is JavaScript — tapping, searching and the running
    summary are exercised in the browser, not here. What *is* server-owned is
    the data the page renders for that JavaScript to filter: only open tabs,
    only sellable items, and every category present as filterable data. These
    tests pin that contract, plus the fact that the plain controls the picker
    layers over are still rendered for a browser with scripting off.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("garcom", password="secret123")

        cls.drinks = Category.objects.create(name="Bebidas")
        cls.food = Category.objects.create(name="Porções")
        cls.empty_category = Category.objects.create(name="Sobremesas")

        cls.table = Table.objects.create(name="Mesa 7", seats=4)
        cls.seated_tab = Tab.objects.create(name="Ana e amigos", table=cls.table)
        cls.bar_tab = Tab.objects.create(name="Bruno no balcão")
        cls.closed_tab = Tab.objects.create(
            name="Comanda encerrada", status=Tab.Status.CLOSED
        )

        cls.beer = Item.objects.create(
            name="Cerveja", category=cls.drinks, price=Decimal("8.50"), stock=10
        )
        cls.fries = Item.objects.create(
            name="Batata frita", category=cls.food, price=Decimal("25.00"), stock=6
        )
        cls.retired = Item.objects.create(
            name="Item aposentado",
            category=cls.drinks,
            price=Decimal("5.00"),
            stock=9,
            is_active=False,
        )
        cls.sold_out = Item.objects.create(
            name="Item esgotado", category=cls.food, price=Decimal("4.00"), stock=0
        )
        # The only item in this category is unsellable, so it must not earn a
        # chip that would filter the list down to nothing.
        cls.dessert = Item.objects.create(
            name="Pudim guardado",
            category=cls.empty_category,
            price=Decimal("12.00"),
            stock=0,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _body(self):
        return self.client.get(reverse("orders:order-create")).content.decode()

    # --- acceptance: one page, one view, no mobile-only route ---------------

    def test_the_picker_url_is_the_one_order_page(self):
        self.assertEqual(reverse("orders:order-create"), "/pedidos/novo/")
        match = resolve("/pedidos/novo/")
        self.assertIs(match.func.view_class, OrderCreateView)

    def test_orders_app_exposes_no_second_order_page_or_picker_endpoint(self):
        """No mobile-only URL and no JSON feed: the page ships its own data.

        ``order-print`` (#228) is an action on an existing order, not a second
        way to build one, so it is allowed here — the point of this guard is
        that the picker has no data endpoint of its own.
        """
        names = {pattern.name for pattern in orders_urls.urlpatterns}
        self.assertEqual(
            names,
            {
                "order-create",
                "kitchen",
                "kitchen-queue",
                "order-done",
                "order-print",
            },
        )

    # --- acceptance: only open tabs are offered, with their table -----------

    def test_open_tabs_are_rendered_as_tappable_targets(self):
        body = self._body()
        for tab in (self.seated_tab, self.bar_tab):
            self.assertIn(f'data-tab-id="{tab.pk}"', body)
            self.assertIn(f'data-tab-name="{tab.name}"', body)

    def test_closed_tabs_are_not_offered_to_the_picker(self):
        body = self._body()
        self.assertNotIn(f'data-tab-id="{self.closed_tab.pk}"', body)
        self.assertNotIn("Comanda encerrada", body)

    def test_a_tab_closed_after_the_page_was_built_is_gone_on_the_next_load(self):
        self.bar_tab.close()
        body = self._body()
        self.assertNotIn(f'data-tab-id="{self.bar_tab.pk}"', body)
        self.assertIn(f'data-tab-id="{self.seated_tab.pk}"', body)

    def test_tab_context_is_the_open_tabs_alphabetically(self):
        resp = self.client.get(reverse("orders:order-create"))
        self.assertEqual(
            list(resp.context["open_tabs"]), [self.seated_tab, self.bar_tab]
        )

    def test_tab_entry_shows_the_table_it_is_sitting_at(self):
        body = self._body()
        entry = body.split(f'data-tab-id="{self.seated_tab.pk}"', 1)[1].split(
            "</button>", 1
        )[0]
        self.assertIn("Mesa 7", entry)

    def test_tab_entry_without_a_table_says_it_has_none(self):
        body = self._body()
        entry = body.split(f'data-tab-id="{self.bar_tab.pk}"', 1)[1].split(
            "</button>", 1
        )[0]
        self.assertNotIn("Mesa 7", entry)
        self.assertIn("sem mesa", entry)

    def test_a_tab_search_box_is_rendered(self):
        self.assertIn('id="tab-search"', self._body())

    # --- acceptance: only sellable items reach the item picker ---------------

    def test_only_active_items_with_stock_are_rendered(self):
        body = self._body()
        for item in (self.beer, self.fries):
            self.assertIn(f'data-item-id="{item.pk}"', body)
        for item in (self.retired, self.sold_out, self.dessert):
            self.assertNotIn(f'data-item-id="{item.pk}"', body)
            self.assertNotIn(item.name, body)

    def test_an_item_that_sells_out_leaves_the_picker(self):
        Item.objects.filter(pk=self.beer.pk).update(stock=0)
        body = self._body()
        self.assertNotIn(f'data-item-id="{self.beer.pk}"', body)
        self.assertIn(f'data-item-id="{self.fries.pk}"', body)

    def test_item_entries_carry_the_data_the_picker_needs(self):
        """Name, stock and category — and, since #231, no price at all.

        The waiter's screen shows no money, so the price is not merely hidden
        with CSS: it is never rendered, not even as a data attribute the
        script could read back.
        """
        body = self._body()
        entry = body.split(f'data-item-id="{self.beer.pk}"', 1)[1].split(
            "</button>", 1
        )[0]
        self.assertIn('data-item-name="Cerveja"', entry)
        self.assertIn('data-item-stock="10"', entry)
        self.assertNotIn("data-item-price", entry)
        self.assertNotIn("8.50", entry)
        self.assertNotIn("R$", entry)

    def test_item_context_is_the_sellable_catalogue_alphabetically(self):
        resp = self.client.get(reverse("orders:order-create"))
        self.assertEqual(
            list(resp.context["sellable_items"]), [self.fries, self.beer]
        )

    def test_an_item_search_box_is_rendered(self):
        self.assertIn('id="item-search"', self._body())

    # --- acceptance: categories are present as filterable data ---------------

    def test_every_item_carries_its_category_for_client_side_filtering(self):
        body = self._body()
        for item in (self.beer, self.fries):
            entry = body.split(f'data-item-id="{item.pk}"', 1)[1].split(
                "</button>", 1
            )[0]
            self.assertIn(f'data-item-category="{item.category_id}"', entry)
            self.assertIn(item.category.name, entry)

    def test_a_chip_is_rendered_for_each_category_with_sellable_items(self):
        body = self._body()
        chips = body.split('id="category-chips"', 1)[1].split("</div>", 1)[0]
        for category in (self.drinks, self.food):
            self.assertIn(f'data-category="{category.pk}"', chips)
            self.assertIn(category.name, chips)

    def test_a_category_with_nothing_sellable_gets_no_chip(self):
        body = self._body()
        self.assertNotIn(f'data-category="{self.empty_category.pk}"', body)
        self.assertNotIn("Sobremesas", body)

    def test_the_chip_row_offers_a_way_back_to_all_items(self):
        chips = self._body().split('id="category-chips"', 1)[1].split("</div>", 1)[0]
        self.assertIn('data-category="all"', chips)
        self.assertIn("Todos", chips)

    def test_category_context_is_only_categories_with_sellable_items(self):
        resp = self.client.get(reverse("orders:order-create"))
        self.assertEqual(
            list(resp.context["item_categories"]), [self.drinks, self.food]
        )

    # --- acceptance: the line list and a reachable submit --------------------

    def test_the_page_renders_the_line_list_the_picker_fills_in(self):
        body = self._body()
        self.assertIn('id="order-summary"', body)
        self.assertIn('id="order-line-inputs"', body)

    def test_the_page_carries_no_running_total_since_prices_left(self):
        self.assertNotIn('id="order-total"', self._body())

    def test_the_submit_rides_a_sticky_bar_so_it_stays_reachable(self):
        body = self._body()
        self.assertIn("karaoke-submit-bar", body)
        bar = body.split("karaoke-submit-bar", 1)[1].split("</form>", 1)[0]
        self.assertIn('type="submit"', bar)

    # --- acceptance: the page still works with JavaScript off ----------------

    def test_plain_controls_are_rendered_for_a_browser_without_javascript(self):
        body = self._body()
        # The real fields, un-hidden in the markup — the script is what hides
        # them, so with scripting off these are what the waiter gets.
        self.assertIn('<select name="tab"', body)
        self.assertIn('<select name="table"', body)
        self.assertIn('<select name="lines-0-item"', body)
        self.assertIn('name="lines-0-quantity"', body)
        self.assertIn('name="lines-TOTAL_FORMS"', body)

    def test_the_plain_path_offers_several_lines_without_javascript(self):
        """No "add another line" button, because it would need scripting.

        The fallback is sized up front instead: a waiter with scripting off
        gets five blank rows, enough for a real round in one submission.
        """
        resp = self.client.get(reverse("orders:order-create"))
        body = resp.content.decode()
        self.assertEqual(len(resp.context["formset"].forms), 5)
        self.assertIn('<select name="lines-4-item"', body)
        self.assertNotIn("add-order-line", body)

    def test_the_picker_blocks_start_hidden_and_the_plain_ones_do_not(self):
        """Progressive enhancement, in that order: plain first, picker on top."""
        body = self._body()
        self.assertIn("<div data-order-picker hidden>", body)
        self.assertIn("<div data-order-plain>", body)
        self.assertNotIn("data-order-plain hidden", body)

    def test_a_plain_submission_still_creates_the_order(self):
        resp = self.client.post(
            reverse("orders:order-create"),
            {
                "tab": self.seated_tab.pk,
                "table": self.table.pk,
                "lines-TOTAL_FORMS": "1",
                "lines-INITIAL_FORMS": "0",
                "lines-MIN_NUM_FORMS": "0",
                "lines-MAX_NUM_FORMS": "1000",
                "lines-0-item": self.beer.pk,
                "lines-0-quantity": "2",
            },
        )
        self.assertEqual(resp.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.tab_id, self.seated_tab.pk)
        self.assertEqual(order.items.get().quantity, 2)
        self.beer.refresh_from_db()
        self.assertEqual(self.beer.stock, 8)

    # --- a rejected submission comes back with the picker intact -------------

    def test_a_rejected_submission_re_renders_the_picker_data(self):
        resp = self.client.post(
            reverse("orders:order-create"),
            {
                "tab": self.seated_tab.pk,
                "table": "",
                "lines-TOTAL_FORMS": "1",
                "lines-INITIAL_FORMS": "0",
                "lines-MIN_NUM_FORMS": "0",
                "lines-MAX_NUM_FORMS": "1000",
                "lines-0-item": self.beer.pk,
                "lines-0-quantity": "99",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Estoque insuficiente", status_code=400)
        body = resp.content.decode()
        self.assertIn(f'data-tab-id="{self.seated_tab.pk}"', body)
        self.assertIn(f'data-item-id="{self.beer.pk}"', body)
        self.assertIn('data-category="all"', body)
        # and the rejected line is still in the plain rows the picker reads
        self.assertIn('value="99"', body)
        self.assertFalse(Order.objects.exists())

    # --- the picker data is escaped, not injected ---------------------------

    def test_a_tab_name_with_markup_is_escaped_in_the_picker_data(self):
        Tab.objects.create(name='Grupo "B" <b>x</b>')
        body = self._body()
        self.assertNotIn("<b>x</b>", body)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", body)

    # --- acceptance: the styles come from static/scss/main.scss --------------

    def test_the_picker_classes_are_defined_in_the_projects_scss(self):
        """The compiled CSS is gitignored, so the source is what we can pin."""
        scss = (settings.BASE_DIR / "static" / "scss" / "main.scss").read_text(
            encoding="utf-8"
        )
        for selector in (
            ".karaoke-pick-grid",
            ".karaoke-pick",
            ".karaoke-filter-chip",
            ".karaoke-chip-row",
            ".karaoke-summary",
            ".karaoke-qty",
            ".karaoke-submit-bar",
            ".karaoke-empty",
        ):
            self.assertIn(selector, scss)


class OrderWizardTests(TestCase):
    """The three-step wizard on /pedidos/novo/ (#231).

    Stepping itself is JavaScript — blocking Avançar until a comanda is picked,
    the recap, the back button — and is exercised in a browser, not here. What
    is server-owned is the markup that JavaScript drives: three labelled step
    sections with a progress indicator, the submit parked in the step-3 slot,
    no price anywhere on the page, and a rejected POST coming back flagged so
    the wizard knows not to reset itself. Those are what these tests pin.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("garcom", password="secret123")
        cls.category = Category.objects.create(name="Bebidas")
        cls.table = Table.objects.create(name="Mesa 7", seats=4)
        cls.tab = Tab.objects.create(name="Ana e amigos", table=cls.table)
        cls.beer = Item.objects.create(
            name="Cerveja", category=cls.category, price=Decimal("8.50"), stock=10
        )
        cls.caipirinha = Item.objects.create(
            name="Caipirinha",
            category=cls.category,
            price=Decimal("19.90"),
            stock=4,
        )
        cls.fries = Item.objects.create(
            name="Batata frita",
            category=cls.category,
            price=Decimal("25.00"),
            stock=6,
            requires_kitchen_preparation=True,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _body(self):
        return self.client.get(reverse("orders:order-create")).content.decode()

    def _payload(self, lines, **overrides):
        data = {
            "tab": self.tab.pk,
            "table": self.table.pk,
            "lines-TOTAL_FORMS": str(len(lines)),
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
        }
        for index, (item_pk, quantity) in enumerate(lines):
            data[f"lines-{index}-item"] = item_pk
            data[f"lines-{index}-quantity"] = quantity
        data.update(overrides)
        return data

    # --- acceptance: three labelled steps with a progress indicator ---------

    def test_the_page_renders_three_step_sections(self):
        body = self._body()
        for step in (1, 2, 3):
            self.assertIn(f'data-step="{step}"', body)
        self.assertNotIn('data-step="4"', body)

    def test_the_progress_indicator_labels_every_step(self):
        indicator = self._body().split('id="order-steps"', 1)[1].split("</ol>", 1)[0]
        for step, label in ((1, "Comanda"), (2, "Itens"), (3, "Confirmação")):
            self.assertIn(f'data-step-chip="{step}"', indicator)
            self.assertIn(label, indicator)

    def test_step_one_holds_the_comanda_picker_and_the_optional_table(self):
        step = self._body().split('data-step="1"', 1)[1].split('data-step="2"', 1)[0]
        self.assertIn('id="tab-search"', step)
        self.assertIn('id="tab-picker"', step)
        self.assertIn(f'data-tab-id="{self.tab.pk}"', step)
        self.assertIn('<select name="table"', step)
        self.assertIn("Opcional", step)

    def test_step_two_holds_the_line_list_and_the_add_item_button(self):
        step = self._body().split('data-step="2"', 1)[1].split('data-step="3"', 1)[0]
        self.assertIn('id="order-summary"', step)
        self.assertIn('id="order-line-inputs"', step)
        # Since #232 the add-item surface is a full-screen modal reached from
        # an "Adicionar item" button — the order list no longer offers inline
        # item picking. The modal markup lives outside the step (it is a
        # Bootstrap modal), so the step itself only carries the button.
        self.assertIn("karaoke-add-item-btn", step)
        self.assertIn('data-bs-target="#add-item-modal"', step)
        # The inline category chips and item grid are gone from the step: they
        # now live inside the modal.
        self.assertNotIn('id="category-chips"', step)
        self.assertNotIn('id="item-search"', step)
        self.assertNotIn('id="item-picker"', step)

    def test_the_add_item_modal_is_rendered_with_chips_search_and_picker(self):
        """The full-screen modal (#232) carries the picker data the step used to."""
        body = self._body()
        modal = body.split('id="add-item-modal"', 1)[1].split("</form>", 1)[0]
        self.assertIn('modal-fullscreen', modal)
        self.assertIn('id="category-chips"', modal)
        self.assertIn('data-category="all"', modal)
        self.assertIn('id="item-search"', modal)
        self.assertIn('id="item-picker"', modal)
        # "Todos" is the active chip by default.
        chips = modal.split('id="category-chips"', 1)[1].split("</div>", 1)[0]
        self.assertIn("karaoke-filter-chip is-on", chips)

    def test_the_quantity_notes_dialog_is_rendered_after_the_add_item_modal(self):
        """A second modal asks for quantity and notes when an item is tapped."""
        body = self._body()
        modal = body.split('id="line-dialog"', 1)[1].split("</form>", 1)[0]
        self.assertIn('id="line-dialog-title"', modal)
        self.assertIn('id="line-dialog-qty"', modal)
        self.assertIn('id="line-dialog-notes"', modal)
        self.assertIn('id="line-dialog-suggestions"', modal)
        self.assertIn('id="line-dialog-confirm"', modal)
        # Quantity defaults to 1, minimum 1.
        qty_field = modal.split('id="line-dialog-qty"', 1)[1].split(">", 1)[0]
        self.assertIn('min="1"', qty_field)
        self.assertIn('value="1"', qty_field)

    def test_step_three_holds_the_read_only_recap(self):
        step = self._body().split('data-step="3"', 1)[1].split("</form>", 1)[0]
        self.assertIn('id="order-recap"', step)
        self.assertIn('id="order-recap-lines"', step)
        self.assertIn("Confirmação", step)

    # --- acceptance: the submit belongs to step 3 ---------------------------

    def test_the_wizard_submit_starts_hidden_next_to_the_step_controls(self):
        """Only step 3 may send the order, so its button comes up hidden.

        The script unhides it on the confirmation step and nowhere else; what
        the server can guarantee is that the enhanced path ships exactly one
        submit and that it starts out of reach.
        """
        bar = self._body().split("karaoke-submit-bar", 1)[1].split("</form>", 1)[0]
        self.assertIn("data-wizard-back", bar)
        self.assertIn("data-wizard-next", bar)
        self.assertIn("data-wizard-submit hidden", bar)

    def test_the_plain_submit_is_the_no_javascript_path(self):
        """With scripting off the steps all render and the plain submit works."""
        body = self._body()
        # The step sections are not hidden in the markup — the script hides
        # the two it is not showing.
        self.assertNotIn('data-step="1" hidden', body)
        self.assertNotIn('class="karaoke-step" hidden', body)
        actions = body.split('class="karaoke-actions" data-order-plain', 1)[1]
        self.assertIn('type="submit"', actions.split("</div>", 1)[0])

    # --- acceptance: no price anywhere in the waiter's flow ------------------

    def test_no_price_is_rendered_anywhere_on_the_order_page(self):
        body = self._body()
        self.assertNotIn("R$", body)
        self.assertNotIn("8.50", body)
        self.assertNotIn("19.90", body)
        self.assertNotIn("data-item-price", body)
        self.assertNotIn('id="order-total"', body)

    def test_no_price_survives_a_rejected_re_render_either(self):
        resp = self.client.post(
            reverse("orders:order-create"),
            self._payload([(self.caipirinha.pk, 99)]),
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.content.decode()
        self.assertNotIn("R$", body)
        self.assertNotIn("19.90", body)

    def test_the_script_no_longer_carries_price_bookkeeping(self):
        """Dropped, not hidden: no money helper is left in the page script."""
        body = self._body()
        self.assertNotIn("function money", body)
        self.assertNotIn("toFixed", body)

    # --- acceptance: a rejection seeds the wizard instead of resetting it ----

    def test_a_fresh_page_is_not_flagged_as_a_rejection(self):
        resp = self.client.get(reverse("orders:order-create"))
        self.assertFalse(resp.context["submission_rejected"])
        self.assertNotIn("data-order-rejected", resp.content.decode())

    def test_a_rejected_submission_is_flagged_with_the_lines_intact(self):
        resp = self.client.post(
            reverse("orders:order-create"),
            self._payload([(self.beer.pk, 2), (self.caipirinha.pk, 99)]),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.context["submission_rejected"])
        body = resp.content.decode()
        self.assertIn('data-order-rejected="1"', body)
        # The error the waiter has to read, above the steps so it is visible
        # whichever step the wizard lands on.
        self.assertIn("Estoque insuficiente", body)
        # and the chosen comanda plus both lines are still in the plain rows
        # the wizard seeds itself from.
        self.assertIn(f'<option value="{self.tab.pk}" selected>', body)
        self.assertIn(f'<option value="{self.beer.pk}" selected>', body)
        self.assertIn(f'<option value="{self.caipirinha.pk}" selected>', body)
        self.assertIn('value="99"', body)
        self.assertFalse(Order.objects.exists())

    def test_a_rejection_with_no_items_is_flagged_too(self):
        resp = self.client.post(reverse("orders:order-create"), self._payload([]))
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.context["submission_rejected"])
        self.assertContains(resp, "Adicione ao menos um item", status_code=400)

    # --- acceptance: submitting still creates the order exactly as before ----

    def test_a_wizard_submission_creates_the_order_and_moves_stock(self):
        """The wizard posts what the plain form posts: same names, same shape."""
        resp = self.client.post(
            reverse("orders:order-create"),
            self._payload([(self.beer.pk, 3), (self.caipirinha.pk, 1)]),
        )
        self.assertEqual(resp.status_code, 302)

        order = Order.objects.get()
        self.assertEqual(order.tab_id, self.tab.pk)
        self.assertEqual(order.table_id, self.table.pk)
        self.assertEqual(
            sorted(order.items.values_list("item__name", "quantity")),
            [("Caipirinha", 1), ("Cerveja", 3)],
        )
        self.beer.refresh_from_db()
        self.caipirinha.refresh_from_db()
        self.assertEqual(self.beer.stock, 7)
        self.assertEqual(self.caipirinha.stock, 3)

    def test_the_submitted_order_reaches_the_kitchen_and_the_tab_detail(self):
        # A kitchen item so the order starts open and lands on the kitchen
        # screen — serve-direct orders start done (#235) and would not.
        self.client.post(
            reverse("orders:order-create"), self._payload([(self.fries.pk, 2)])
        )
        order = Order.objects.get()

        kitchen = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertIn(f"#{order.pk}", kitchen)
        self.assertIn("Batata frita", kitchen)

        detail = self.client.get(
            reverse("tabs:tab-detail", args=[self.tab.pk])
        ).content.decode()
        self.assertIn(f"#{order.pk}", detail)
        self.assertIn("Batata frita", detail)

    # --- acceptance: the wizard styling lives in the project's SCSS ----------

    def test_the_wizard_classes_are_defined_in_the_projects_scss(self):
        scss = (settings.BASE_DIR / "static" / "scss" / "main.scss").read_text(
            encoding="utf-8"
        )
        for selector in (
            ".karaoke-steps",
            ".karaoke-step-chip",
            ".karaoke-step-num",
            ".karaoke-step-label",
            ".karaoke-wizard-status",
            ".karaoke-wizard-hint",
            ".karaoke-recap",
            ".karaoke-recap-row",
            ".karaoke-recap-qty",
        ):
            self.assertIn(selector, scss)


class AddItemModalTests(TestCase):
    """The add-item modal and quantity/notes dialog on /pedidos/novo/ (#232).

    The modal is a layer over the existing single-POST contract: the catalogue
    is rendered inside a full-screen Bootstrap modal, tapping an item opens a
    second dialog for quantity and notes, and confirming appends a line to the
    hidden formset inputs. What the server owns is the markup and the data the
    script drives — the category strip, the search field, the suggestion chips
    riding on each item, and the absence of prices anywhere in the flow. The
    POST contract and the no-JS fallback are covered by the suites above; this
    class pins what #232 adds.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("garcom", password="secret123")
        cls.drinks = Category.objects.create(name="Bebidas")
        cls.food = Category.objects.create(name="Porções")
        cls.empty_category = Category.objects.create(name="Sobremesas")
        cls.table = Table.objects.create(name="Mesa 7", seats=4)
        cls.tab = Tab.objects.create(name="Ana e amigos", table=cls.table)

        cls.beer = Item.objects.create(
            name="Cerveja", category=cls.drinks, price=Decimal("8.50"), stock=10
        )
        # Two curated suggestions — the chip row the dialog renders.
        NoteSuggestion.objects.create(item=cls.beer, text="gelo")
        NoteSuggestion.objects.create(item=cls.beer, text="rodela de limão")

        cls.fries = Item.objects.create(
            name="Batata frita", category=cls.food, price=Decimal("25.00"), stock=6
        )
        # No suggestions — the dialog shows no chip row for this item.

        cls.dessert = Item.objects.create(
            name="Pudim guardado",
            category=cls.empty_category,
            price=Decimal("12.00"),
            stock=0,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _body(self):
        return self.client.get(reverse("orders:order-create")).content.decode()

    def _modal(self):
        return self._body().split('id="add-item-modal"', 1)[1].split("</form>", 1)[0]

    def _dialog(self):
        return self._body().split('id="line-dialog"', 1)[1].split("</form>", 1)[0]

    # --- acceptance: the "Adicionar item" button replaces inline picking -----

    def test_step_two_offers_an_adicionar_item_button(self):
        step = self._body().split('data-step="2"', 1)[1].split('data-step="3"', 1)[0]
        self.assertIn("Adicionar item", step)
        self.assertIn('data-bs-toggle="modal"', step)
        self.assertIn('data-bs-target="#add-item-modal"', step)

    def test_the_order_list_no_longer_offers_inline_item_picking(self):
        """The inline category chips and item grid are gone from step 2."""
        step = self._body().split('data-step="2"', 1)[1].split('data-step="3"', 1)[0]
        # The picker grid and the inline filter chips moved into the modal.
        self.assertNotIn('id="item-picker"', step)
        self.assertNotIn('id="category-chips"', step)
        self.assertNotIn('id="item-search"', step)

    # --- acceptance: full-screen modal with a pinned category strip ----------

    def test_the_add_item_modal_is_full_screen(self):
        modal = self._modal()
        self.assertIn("modal-fullscreen", modal)
        self.assertIn('role="dialog"', modal)

    def test_the_category_strip_is_rendered_inside_the_modal(self):
        modal = self._modal()
        self.assertIn('id="category-chips"', modal)
        for category in (self.drinks, self.food):
            self.assertIn(f'data-category="{category.pk}"', modal)
            self.assertIn(category.name, modal)

    def test_the_category_strip_offers_todos_active_by_default(self):
        modal = self._modal()
        chips = modal.split('id="category-chips"', 1)[1].split("</div>", 1)[0]
        self.assertIn('data-category="all"', chips)
        self.assertIn("Todos", chips)
        # Only "Todos" starts active.
        self.assertIn("karaoke-filter-chip is-on", chips)

    def test_a_category_with_nothing_sellable_gets_no_chip_in_the_modal(self):
        modal = self._modal()
        self.assertNotIn(f'data-category="{self.empty_category.pk}"', modal)

    def test_the_search_field_is_rendered_below_the_category_strip(self):
        modal = self._modal()
        self.assertIn('id="item-search"', modal)

    def test_the_item_grid_inside_the_modal_lists_sellable_items(self):
        modal = self._modal()
        for item in (self.beer, self.fries):
            self.assertIn(f'data-item-id="{item.pk}"', modal)
        for item in (self.dessert,):
            self.assertNotIn(f'data-item-id="{item.pk}"', modal)

    def test_no_match_in_the_modal_shows_a_friendly_empty_message(self):
        modal = self._modal()
        self.assertIn("data-item-empty", modal)
        self.assertIn("Nenhum item encontrado", modal)

    # --- acceptance: no price anywhere in the modal or the dialog ------------

    def test_no_price_is_rendered_in_the_add_item_modal(self):
        modal = self._modal()
        self.assertNotIn("R$", modal)
        self.assertNotIn("8.50", modal)
        self.assertNotIn("25.00", modal)
        self.assertNotIn("data-item-price", modal)

    def test_no_price_is_rendered_in_the_quantity_notes_dialog(self):
        dialog = self._dialog()
        self.assertNotIn("R$", dialog)
        self.assertNotIn("8.50", dialog)
        self.assertNotIn("25.00", dialog)

    # --- acceptance: suggestion chips ride along with the item data ----------

    def test_each_item_carries_its_suggestions_as_data(self):
        """The dialog clones chips from a `||`-joined data attribute (#230)."""
        body = self._body()
        entry = body.split(f'data-item-id="{self.beer.pk}"', 1)[1].split(
            "</button>", 1
        )[0]
        self.assertIn("data-item-suggestions", entry)
        self.assertIn("gelo", entry)
        self.assertIn("rodela de limão", entry)

    def test_an_item_without_suggestions_carries_an_empty_attribute(self):
        body = self._body()
        entry = body.split(f'data-item-id="{self.fries.pk}"', 1)[1].split(
            "</button>", 1
        )[0]
        self.assertIn("data-item-suggestions", entry)
        # The attribute is present but empty — the script renders no chip row.
        suggestions_attr = entry.split('data-item-suggestions="', 1)[1].split(
            '"', 1
        )[0]
        self.assertEqual(suggestions_attr, "")

    def test_the_dialog_renders_a_suggestion_chips_row(self):
        dialog = self._dialog()
        self.assertIn('id="line-dialog-suggestions"', dialog)
        self.assertIn("karaoke-suggestion-chips", dialog)

    def test_the_dialog_renders_a_no_suggestions_empty_state(self):
        dialog = self._dialog()
        self.assertIn('id="line-dialog-no-suggestions"', dialog)

    def test_suggestion_text_is_escaped_in_the_data_attribute(self):
        """Markup in a suggestion must not reach the DOM as live HTML.

        ``escapejs`` is what the data attribute uses (the script reads it via
        ``dataset``), so the angle brackets come through as ``\\u003C`` rather
        than HTML entities — either way, the raw ``<b>`` never reaches the DOM.
        """
        item = Item.objects.create(
            name="Item com sugestão maliciosa",
            category=self.drinks,
            price=Decimal("1.00"),
            stock=1,
        )
        NoteSuggestion.objects.create(item=item, text="<b>gelo</b>")
        body = self._body()
        entry = body.split(f'data-item-id="{item.pk}"', 1)[1].split(
            "</button>", 1
        )[0]
        self.assertNotIn("<b>gelo</b>", entry)
        self.assertIn("gelo", entry)

    # --- acceptance: the quantity/notes dialog --------------------------------

    def test_the_dialog_has_a_quantity_input_defaulting_to_one(self):
        dialog = self._dialog()
        qty_field = dialog.split('id="line-dialog-qty"', 1)[1].split(">", 1)[0]
        self.assertIn('min="1"', qty_field)
        self.assertIn('value="1"', qty_field)

    def test_the_dialog_has_a_notes_input(self):
        dialog = self._dialog()
        self.assertIn('id="line-dialog-notes"', dialog)
        self.assertIn("maxlength=\"200\"", dialog)

    def test_the_dialog_has_a_confirm_button(self):
        dialog = self._dialog()
        self.assertIn('id="line-dialog-confirm"', dialog)
        self.assertIn("Confirmar", dialog)

    def test_the_dialog_carries_the_max_stock_hint_for_the_script(self):
        """The script caps the quantity stepper at the item's current stock."""
        body = self._body()
        entry = body.split(f'data-item-id="{self.beer.pk}"', 1)[1].split(
            "</button>", 1
        )[0]
        self.assertIn('data-item-stock="10"', entry)

    # --- acceptance: the single-POST contract and duplicate lines ------------

    def test_the_dialog_writes_the_same_formset_field_names(self):
        """The hidden inputs keep the ``lines-N-notes`` contract (#229)."""
        body = self._body()
        self.assertIn('"lines-" + index + "-notes"', body)
        self.assertIn('"lines-" + index + "-item"', body)
        self.assertIn('"lines-" + index + "-quantity"', body)

    def test_duplicate_item_lines_can_be_posted_as_separate_lines(self):
        """Two lines of the same item with different notes both land on the order."""
        data = {
            "tab": self.tab.pk,
            "table": self.table.pk,
            "lines-TOTAL_FORMS": "2",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-item": self.beer.pk,
            "lines-0-quantity": "1",
            "lines-0-notes": "com gelo",
            "lines-1-item": self.beer.pk,
            "lines-1-quantity": "2",
            "lines-1-notes": "sem gelo",
        }
        resp = self.client.post(reverse("orders:order-create"), data)
        self.assertEqual(resp.status_code, 302)

        order = Order.objects.get()
        lines = list(order.items.order_by("pk"))
        self.assertEqual(len(lines), 2)
        self.assertEqual([l.quantity for l in lines], [1, 2])
        self.assertEqual([l.notes for l in lines], ["com gelo", "sem gelo"])
        self.beer.refresh_from_db()
        self.assertEqual(self.beer.stock, 7)

    # --- acceptance: the wizard styling lives in the project's SCSS ----------

    def test_the_modal_classes_are_defined_in_the_projects_scss(self):
        scss = (settings.BASE_DIR / "static" / "scss" / "main.scss").read_text(
            encoding="utf-8"
        )
        for selector in (
            ".karaoke-add-item-btn",
            ".karaoke-modal-sticky",
            ".karaoke-modal-chips",
            ".karaoke-modal-scroll",
            ".karaoke-suggestion-chip",
            ".karaoke-summary-note",
        ):
            self.assertIn(selector, scss)


class OrderModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tab = Tab.objects.create(name="Comanda Bruno")
        cls.table = Table.objects.create(name="Mesa 2", seats=2)
        cls.category = Category.objects.create(name="bebidas")
        cls.item = Item.objects.create(
            name="Refrigerante",
            category=cls.category,
            price=Decimal("6.00"),
            stock=4,
        )

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
        cls.category = Category.objects.create(name="bebidas")
        cls.item = Item.objects.create(
            name="Cerveja", category=cls.category, price=Decimal("8.50"), stock=20
        )
        cls.item2 = Item.objects.create(
            name="Porção", category=cls.category, price=Decimal("25.00"), stock=10
        )
        # Since #233 an item may be flagged serve-direct (no kitchen prep); the
        # kitchen surfaces must only carry items that need preparation (#234).
        cls.kitchen_item = Item.objects.create(
            name="Batata frita",
            category=cls.category,
            price=Decimal("25.00"),
            stock=10,
            requires_kitchen_preparation=True,
        )
        cls.serve_direct_item = Item.objects.create(
            name="Refrigerante lata",
            category=cls.category,
            price=Decimal("6.00"),
            stock=30,
            requires_kitchen_preparation=False,
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

    # --- acceptance: only kitchen-preparation lines reach the screen (#234) --

    def test_kitchen_card_shows_only_kitchen_preparation_lines(self):
        """A mixed order shows the kitchen item and hides the serve-direct one."""
        order = self._make_order(
            self.tab_a,
            [(self.kitchen_item, 2), (self.serve_direct_item, 3)],
            table=self.table_a,
        )
        body = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertIn(f"#{order.pk}", body)
        self.assertIn("Batata frita", body)
        self.assertIn("2x", body)
        # The serve-direct line is absent from the card entirely.
        self.assertNotIn("Refrigerante lata", body)
        self.assertNotIn("3x", body)

    def test_polling_fragment_shows_only_kitchen_preparation_lines(self):
        order = self._make_order(
            self.tab_a,
            [(self.kitchen_item, 1), (self.serve_direct_item, 2)],
        )
        body = self.client.get(reverse("orders:kitchen-queue")).content.decode()
        self.assertIn(f"#{order.pk}", body)
        self.assertIn("Batata frita", body)
        self.assertNotIn("Refrigerante lata", body)

    def test_serve_direct_only_order_is_absent_from_the_kitchen_page(self):
        """A round with no kitchen items never renders a card, even while open."""
        order = self._make_order(
            self.tab_a, [(self.serve_direct_item, 2)], table=self.table_a
        )
        # The order is still open — it just has nothing for the kitchen.
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)
        body = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertNotIn(f"#{order.pk}", body)
        self.assertNotIn("Refrigerante lata", body)
        self.assertNotIn(self.tab_a.name, body)

    def test_serve_direct_only_order_is_absent_from_the_polling_fragment(self):
        order = self._make_order(self.tab_a, [(self.serve_direct_item, 1)])
        body = self.client.get(reverse("orders:kitchen-queue")).content.decode()
        self.assertNotIn(f"#{order.pk}", body)
        self.assertNotIn("Refrigerante lata", body)

    def test_serve_direct_only_order_falls_through_to_the_empty_state(self):
        """With only a serve-direct round open, the screen shows 'no orders'."""
        self._make_order(self.tab_a, [(self.serve_direct_item, 1)])
        page = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertIn("Sem pedidos abertos", page)
        fragment = self.client.get(
            reverse("orders:kitchen-queue")
        ).content.decode()
        self.assertIn("Sem pedidos abertos", fragment)


@override_settings(KARAOKE_PRINTER_DRY_RUN=True)
class OrderPrintViewTests(TestCase):
    """Acceptance tests for the kitchen ticket printing endpoint (#228).

    Every test runs in dry-run mode with the dump directory pointed at a
    throwaway temp dir, which is exactly how the feature is QA'd on a machine
    with no thermal printer attached.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")
        cls.tab = Tab.objects.create(name="Comanda Ana")
        cls.table = Table.objects.create(name="Mesa 7", seats=4)
        cls.category = Category.objects.create(name="bebidas")
        cls.beer = Item.objects.create(
            name="Cerveja long neck",
            category=cls.category,
            price=Decimal("12.50"),
            stock=20,
        )
        cls.fries = Item.objects.create(
            name="Porção de batata frita",
            category=cls.category,
            price=Decimal("34.90"),
            stock=10,
        )
        # Since #234 the ticket only lists kitchen-preparation items.
        cls.kitchen_item = Item.objects.create(
            name="Porção de batata frita",
            category=cls.category,
            price=Decimal("34.90"),
            stock=10,
            requires_kitchen_preparation=True,
        )
        cls.serve_direct_item = Item.objects.create(
            name="Refrigerante lata",
            category=cls.category,
            price=Decimal("6.00"),
            stock=30,
            requires_kitchen_preparation=False,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.dump_dir = Path(tempfile.mkdtemp(prefix="karaoke-receipts-"))
        self.addCleanup(shutil.rmtree, self.dump_dir, True)
        patched = override_settings(KARAOKE_PRINTER_DUMP_DIR=self.dump_dir)
        patched.enable()
        self.addCleanup(patched.disable)

    # --- helpers -----------------------------------------------------------

    def _make_order(self, lines, table=None):
        order = Order.objects.create(tab=self.tab, table=table)
        for item, qty in lines:
            OrderItem.objects.create(
                order=order, item=item, quantity=qty, unit_price=item.price
            )
        return order

    def _print(self, order):
        return self.client.post(reverse("orders:order-print", args=[order.pk]))

    def _ticket_text(self, order):
        return (self.dump_dir / f"pedido-{order.pk}-cozinha.txt").read_text(
            encoding="utf-8"
        )

    # --- acceptance: login required ----------------------------------------

    def test_anonymous_print_redirected_to_login(self):
        self.client.logout()
        order = self._make_order([(self.beer, 1)])
        resp = self._print(order)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("next=", resp["Location"])
        self.assertFalse(list(self.dump_dir.iterdir()))

    # --- acceptance: dry-run success --------------------------------------

    def test_print_returns_success_json(self):
        order = self._make_order([(self.beer, 2)])
        resp = self._print(order)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertIn(str(order.pk), body["message"])

    def test_print_writes_bin_and_txt_dumps(self):
        order = self._make_order([(self.beer, 2)])
        self._print(order)

        binary = self.dump_dir / f"pedido-{order.pk}-cozinha.bin"
        readable = self.dump_dir / f"pedido-{order.pk}-cozinha.txt"
        self.assertTrue(binary.exists())
        self.assertTrue(readable.exists())
        # The .bin is the raw ESC/POS stream: it opens with the reset command
        # and ends with the cut, which the readable copy has stripped out.
        raw = binary.read_bytes()
        self.assertTrue(raw.startswith(b"\x1b@"))
        self.assertTrue(raw.endswith(b"\x1dVB\x00"))
        self.assertNotIn("\x1b", readable.read_text(encoding="utf-8"))

    def test_printing_does_not_change_the_order_status(self):
        """Printing is read-only: only "Pronto" takes a card off the screen."""
        order = self._make_order([(self.beer, 1)])
        self._print(order)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.OPEN)

    # --- acceptance: ticket content ----------------------------------------

    def test_ticket_shows_tab_order_number_and_time(self):
        order = self._make_order([(self.beer, 1)], table=self.table)
        self._print(order)
        text = self._ticket_text(order)

        self.assertIn("Comanda Ana", text)
        self.assertIn(f"PEDIDO #{order.pk}", text)
        self.assertIn("Mesa: Mesa 7", text)
        self.assertIn(
            timezone.localtime(order.created_at).strftime("%d/%m/%Y %H:%M"), text
        )

    def test_ticket_omits_the_table_when_the_order_has_none(self):
        order = self._make_order([(self.beer, 1)])
        self._print(order)
        self.assertNotIn("Mesa:", self._ticket_text(order))

    def test_ticket_lists_every_item_with_its_quantity(self):
        order = self._make_order([(self.beer, 2), (self.fries, 3)])
        self._print(order)
        text = self._ticket_text(order)

        # Accents are normalized to ASCII for the printer's DOS code page.
        self.assertIn("2x Cerveja long neck", text)
        self.assertIn("3x Porcao de batata frita", text)
        self.assertNotIn("Porção", text)
        self.assertIn("Total de itens:", text)
        self.assertIn("Total de unidades:", text)

    def test_ticket_carries_no_prices(self):
        order = self._make_order([(self.beer, 2), (self.fries, 3)])
        self._print(order)
        text = self._ticket_text(order)

        self.assertNotIn("R$", text)
        self.assertNotIn("12.50", text)
        self.assertNotIn("34.90", text)
        # ...and no line total either (2 x 12.50 = 25.00).
        self.assertNotIn("25.00", text)

    # --- acceptance: unknown order ----------------------------------------

    def test_unknown_order_returns_404(self):
        resp = self.client.post(reverse("orders:order-print", args=[999999]))
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(list(self.dump_dir.iterdir()))

    # --- acceptance: printer failure surfaces --------------------------------

    @override_settings(KARAOKE_PRINTER_DRY_RUN=False)
    def test_printer_error_returns_503_with_the_message(self):
        """With dry-run off and no printer, the UI must get a readable error."""
        order = self._make_order([(self.beer, 1)])
        with mock.patch(
            "orders.views.print_raw",
            side_effect=PrinterError("Nenhuma impressora respondeu."),
        ):
            resp = self._print(order)

        self.assertEqual(resp.status_code, 503)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"], "Nenhuma impressora respondeu.")

    # --- acceptance: the button is on every card ---------------------------

    def test_kitchen_card_offers_a_print_button(self):
        order = self._make_order([(self.beer, 1)])
        resp = self.client.get(reverse("orders:kitchen"))
        self.assertContains(resp, reverse("orders:order-print", args=[order.pk]))
        self.assertContains(resp, "Imprimir")

    def test_polling_fragment_also_carries_the_print_button(self):
        """The delegated listener needs the button in the polled cards too."""
        order = self._make_order([(self.beer, 1)])
        resp = self.client.get(reverse("orders:kitchen-queue"))
        self.assertContains(resp, reverse("orders:order-print", args=[order.pk]))

    # --- acceptance: ticket lists only kitchen-preparation lines (#234) ----

    def test_ticket_lists_only_kitchen_preparation_items(self):
        order = self._make_order(
            [(self.kitchen_item, 2), (self.serve_direct_item, 3)]
        )
        self._print(order)
        text = self._ticket_text(order)

        self.assertIn("2x Porcao de batata frita", text)
        # The serve-direct line is absent from the printed ticket.
        self.assertNotIn("Refrigerante lata", text)
        self.assertNotIn("3x", text)

    def test_ticket_totals_count_only_kitchen_preparation_lines(self):
        """'Total de itens' and 'Total de unidades' count only preparation lines."""
        order = self._make_order(
            [(self.kitchen_item, 2), (self.serve_direct_item, 3)]
        )
        self._print(order)
        text = self._ticket_text(order)

        # Only one kitchen line of 2 units — the serve-direct 3 units do not
        # count toward the kitchen totals.
        self.assertIn("Total de itens:", text)
        self.assertIn("Total de unidades:", text)
        lines = text.splitlines()
        itens_line = next(line for line in lines if "Total de itens:" in line)
        unidades_line = next(
            line for line in lines if "Total de unidades:" in line
        )
        self.assertTrue(itens_line.rstrip().endswith("1"), itens_line)
        self.assertTrue(unidades_line.rstrip().endswith("2"), unidades_line)


class KitchenReceiptBuilderTests(TestCase):
    """Unit tests for the ported ESC/POS helpers."""

    def test_normalize_text_strips_accents_and_symbols(self):
        self.assertEqual(normalize_text("Porção — 20°"), "Porcao - 20o")
        self.assertEqual(normalize_text(None), "")

    def test_strip_escpos_removes_the_control_sequences(self):
        payload = b"\x1b@\x1ba\x01\x1bE\x01OI\n\x1bE\x00\x1d!\x00\x1dVB\x00"
        self.assertEqual(strip_escpos(payload), "OI\n")

    def test_builder_right_aligns_within_the_paper_width(self):
        builder = ReceiptBuilder(width=20, margin=2)
        builder.lr("Itens:", "3")
        self.assertIn("Itens:           3", builder.to_text())


@override_settings(KARAOKE_PRINTER_DRY_RUN=True)
class OrderLineNotesTests(TestCase):
    """Acceptance tests for the per-line note, waiter to kitchen (#229).

    The note is one free-text field that has to survive the whole trip: typed
    on the order page, posted through the ``lines-`` formset, stored on the
    :class:`OrderItem`, shown on the kitchen card and printed on the ticket.
    Each leg of that trip gets its own test, plus the case that must stay
    boring — a line with no note at all.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")
        cls.tab = Tab.objects.create(name="Comanda Ana")
        cls.table = Table.objects.create(name="Mesa 7", seats=4)
        cls.category = Category.objects.create(name="bebidas")
        cls.caipirinha = Item.objects.create(
            name="Caipirinha",
            category=cls.category,
            price=Decimal("22.00"),
            stock=20,
            requires_kitchen_preparation=True,
        )
        cls.fries = Item.objects.create(
            name="Porção de batata frita",
            category=cls.category,
            price=Decimal("34.90"),
            stock=10,
        )
        # Since #234 the kitchen surfaces only carry kitchen-preparation items.
        cls.serve_direct = Item.objects.create(
            name="Refrigerante lata",
            category=cls.category,
            price=Decimal("6.00"),
            stock=30,
            requires_kitchen_preparation=False,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.dump_dir = Path(tempfile.mkdtemp(prefix="karaoke-receipts-"))
        self.addCleanup(shutil.rmtree, self.dump_dir, True)
        patched = override_settings(KARAOKE_PRINTER_DUMP_DIR=self.dump_dir)
        patched.enable()
        self.addCleanup(patched.disable)

    # --- helpers -----------------------------------------------------------

    def _post(self, lines):
        """POST the order page with ``lines`` as ``(item, quantity, notes)``."""
        data = {
            "tab": self.tab.pk,
            "table": self.table.pk,
            "lines-TOTAL_FORMS": str(len(lines)),
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
        }
        for index, (item, quantity, notes) in enumerate(lines):
            data[f"lines-{index}-item"] = item.pk
            data[f"lines-{index}-quantity"] = str(quantity)
            if notes is not None:
                data[f"lines-{index}-notes"] = notes
        return self.client.post(reverse("orders:order-create"), data)

    def _make_order(self, lines, table=None):
        """Build an order directly from ``(item, quantity, notes)`` triples."""
        order = Order.objects.create(tab=self.tab, table=table)
        for item, quantity, notes in lines:
            OrderItem.objects.create(
                order=order,
                item=item,
                quantity=quantity,
                unit_price=item.price,
                notes=notes,
            )
        return order

    def _ticket_text(self, order):
        self.client.post(reverse("orders:order-print", args=[order.pk]))
        return (self.dump_dir / f"pedido-{order.pk}-cozinha.txt").read_text(
            encoding="utf-8"
        )

    # --- acceptance: the model's new field ---------------------------------

    def test_a_line_without_a_note_defaults_to_the_empty_string(self):
        """The normal case: no note, no ``None`` to guard against downstream."""
        order = Order.objects.create(tab=self.tab)
        line = OrderItem.objects.create(
            order=order, item=self.caipirinha, quantity=1, unit_price=Decimal("22.00")
        )
        line.refresh_from_db()
        self.assertEqual(line.notes, "")

    # --- acceptance: the note round-trips from POST to the OrderItem --------

    def test_a_note_posted_on_a_line_is_stored_on_the_order_item(self):
        resp = self._post([(self.caipirinha, 2, "com gelo e limão")])
        self.assertEqual(resp.status_code, 302)

        line = OrderItem.objects.get()
        self.assertEqual(line.item_id, self.caipirinha.pk)
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.notes, "com gelo e limão")

    def test_each_line_keeps_its_own_note(self):
        self._post(
            [
                (self.caipirinha, 1, "sem açúcar"),
                (self.fries, 1, "bem passada"),
            ]
        )
        notes = {
            line.item.name: line.notes for line in OrderItem.objects.select_related("item")
        }
        self.assertEqual(notes["Caipirinha"], "sem açúcar")
        self.assertEqual(notes["Porção de batata frita"], "bem passada")

    def test_a_note_is_stripped_of_surrounding_whitespace(self):
        self._post([(self.caipirinha, 1, "  com gelo  ")])
        self.assertEqual(OrderItem.objects.get().notes, "com gelo")

    # --- acceptance: a blank note stays valid and changes nothing -----------

    def test_a_line_with_a_blank_note_still_submits(self):
        resp = self._post([(self.caipirinha, 1, "")])
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(OrderItem.objects.get().notes, "")

    def test_a_line_that_posts_no_notes_field_at_all_still_submits(self):
        """Exactly the pre-#229 POST body: it has to keep working untouched."""
        resp = self._post([(self.caipirinha, 3, None)])
        self.assertEqual(resp.status_code, 302)

        line = OrderItem.objects.get()
        self.assertEqual(line.quantity, 3)
        self.assertEqual(line.notes, "")
        self.caipirinha.refresh_from_db()
        self.assertEqual(self.caipirinha.stock, 17)

    def test_a_note_on_one_line_leaves_the_other_line_blank(self):
        self._post([(self.caipirinha, 1, "com gelo"), (self.fries, 1, "")])
        notes = {
            line.item.name: line.notes for line in OrderItem.objects.select_related("item")
        }
        self.assertEqual(notes["Caipirinha"], "com gelo")
        self.assertEqual(notes["Porção de batata frita"], "")

    def test_a_note_over_the_field_length_is_rejected_without_writing(self):
        resp = self._post([(self.caipirinha, 1, "x" * 201)])
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(OrderItem.objects.exists())

    # --- acceptance: the waiter-side inputs ---------------------------------

    def test_the_plain_formset_rows_offer_a_notes_input(self):
        """The no-JS path: every rendered row has its own ``lines-N-notes``."""
        body = self.client.get(reverse("orders:order-create")).content.decode()
        self.assertIn('name="lines-0-notes"', body)
        self.assertIn('name="lines-4-notes"', body)

    def test_the_picker_posts_its_notes_through_the_same_formset_prefix(self):
        """The touch picker writes the very same field names, per line.

        Since #232 the note is entered in the quantity/notes dialog and the
        summary shows it read-only — the inline ``karaoke-note-input`` on the
        summary row is gone, replaced by ``karaoke-summary-note`` and the
        dialog's ``line-dialog-notes``. The formset contract is unchanged.
        """
        body = self.client.get(reverse("orders:order-create")).content.decode()
        self.assertIn('"lines-" + index + "-notes"', body)
        # The dialog owns the notes entry now; the summary only shows the value.
        self.assertIn('id="line-dialog-notes"', body)
        self.assertIn("karaoke-summary-note", body)
        self.assertNotIn("karaoke-note-input", body)
        # The add-item flow is now a Bootstrap modal (#232).
        self.assertIn('data-bs-toggle="modal"', body)
        self.assertIn('id="add-item-modal"', body)

    def test_the_note_input_style_is_defined_in_the_projects_scss(self):
        """The compiled CSS is gitignored, so the source is what we can pin.

        Since #232 the inline ``.karaoke-note-input`` on the summary row is
        gone; the dialog's notes field is a plain ``.form-control`` and the
        summary shows the note read-only as ``.karaoke-summary-note``. The
        kitchen card's ``.kitchen-line-note`` is unchanged.
        """
        scss = (settings.BASE_DIR / "static" / "scss" / "main.scss").read_text(
            encoding="utf-8"
        )
        self.assertIn(".karaoke-summary-note", scss)
        self.assertIn(".kitchen-line-note", scss)

    # --- acceptance: the kitchen screen -------------------------------------

    def test_kitchen_card_shows_the_note_under_its_item(self):
        self._make_order([(self.caipirinha, 2, "com gelo e limão")])
        body = self.client.get(reverse("orders:kitchen")).content.decode()

        self.assertIn("Caipirinha", body)
        self.assertIn(
            '<p class="kitchen-line-note">com gelo e limão</p>', body
        )

    def test_polling_fragment_also_shows_the_note(self):
        self._make_order([(self.caipirinha, 1, "sem açúcar")])
        body = self.client.get(reverse("orders:kitchen-queue")).content.decode()
        self.assertIn('<p class="kitchen-line-note">sem açúcar</p>', body)

    def test_a_line_without_a_note_renders_no_note_element(self):
        self._make_order([(self.caipirinha, 1, "")])
        for url in (reverse("orders:kitchen"), reverse("orders:kitchen-queue")):
            body = self.client.get(url).content.decode()
            self.assertNotIn("kitchen-line-note", body)

    def test_only_the_line_with_a_note_gets_one_on_the_card(self):
        self._make_order([(self.caipirinha, 1, "com gelo"), (self.fries, 2, "")])
        body = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertEqual(body.count("kitchen-line-note"), 1)

    def test_a_note_with_markup_is_escaped_on_the_card(self):
        self._make_order([(self.caipirinha, 1, "sem <b>gelo</b>")])
        body = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertNotIn("<b>gelo</b>", body)
        self.assertIn("&lt;b&gt;gelo&lt;/b&gt;", body)

    def test_the_kitchen_card_still_shows_no_prices(self):
        self._make_order([(self.caipirinha, 1, "com gelo")])
        body = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertNotIn("R$", body)
        self.assertNotIn("22.00", body)

    # --- acceptance: the printed ticket -------------------------------------

    def test_the_ticket_prints_the_note_indented_under_its_item(self):
        order = self._make_order([(self.caipirinha, 2, "com gelo e limão")])
        text = self._ticket_text(order)

        lines = text.splitlines()
        item_at = next(i for i, line in enumerate(lines) if "2x Caipirinha" in line)
        note_at = next(i for i, line in enumerate(lines) if "com gelo e limao" in line)

        # Directly under the item it belongs to...
        self.assertEqual(note_at, item_at + 1)
        # ...and indented further in than the item line itself.
        item_indent = len(lines[item_at]) - len(lines[item_at].lstrip())
        note_indent = len(lines[note_at]) - len(lines[note_at].lstrip())
        self.assertGreater(note_indent, item_indent)

    def test_the_ticket_normalizes_the_notes_accents(self):
        order = self._make_order([(self.fries, 1, "sem açúcar, bem passada")])
        text = self._ticket_text(order)
        self.assertIn("sem acucar, bem passada", text)
        self.assertNotIn("açúcar", text)

    def test_a_long_note_wraps_to_the_paper_width(self):
        note = (
            "sem cebola sem pimenta sem tomate e por favor mandar o molho "
            "separado em um potinho a parte"
        )
        order = self._make_order([(self.fries, 1, note)])
        text = self._ticket_text(order)

        wrapped = [line for line in text.splitlines() if "sem cebola" in line]
        self.assertEqual(len(wrapped), 1)
        # Wrapped, not truncated: the tail is on the paper too, and nothing
        # overflows the configured width.
        self.assertIn("potinho", text)
        for line in text.splitlines():
            self.assertLessEqual(len(line), settings.KARAOKE_RECEIPT_WIDTH)

    def test_the_ticket_omits_the_note_line_when_there_is_none(self):
        order = self._make_order([(self.caipirinha, 1, "")])
        text = self._ticket_text(order)
        self.assertIn("1x Caipirinha", text)
        # The only dashes left are the rules, never an empty "- " note.
        self.assertNotIn("- \n", text)

    def test_the_ticket_with_notes_still_carries_no_prices(self):
        order = self._make_order(
            [(self.caipirinha, 2, "com gelo"), (self.fries, 1, "bem passada")]
        )
        text = self._ticket_text(order)
        self.assertNotIn("R$", text)
        self.assertNotIn("22.00", text)
        self.assertNotIn("34.90", text)

    def test_a_note_typed_by_the_waiter_reaches_the_printed_ticket(self):
        """The whole trip in one test: POST, kitchen card, paper."""
        self._post([(self.caipirinha, 1, "com gelo e limão")])
        order = Order.objects.get()

        card = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertIn("com gelo e limão", card)
        self.assertIn("com gelo e limao", self._ticket_text(order))

    # --- acceptance: only kitchen-preparation lines on screen and paper (#234)

    def test_mixed_order_kitchen_card_omits_serve_direct_lines(self):
        """A serve-direct line never reaches the kitchen card."""
        order = self._make_order(
            [(self.fries, 2, "bem passada"), (self.serve_direct, 3, "")]
        )
        card = self.client.get(reverse("orders:kitchen")).content.decode()
        self.assertIn(f"#{order.pk}", card)
        self.assertIn("Porção de batata frita", card)
        self.assertIn("bem passada", card)
        self.assertNotIn("Refrigerante lata", card)

    def test_mixed_order_polling_fragment_omits_serve_direct_lines(self):
        self._make_order(
            [(self.fries, 1, ""), (self.serve_direct, 2, "")]
        )
        body = self.client.get(
            reverse("orders:kitchen-queue")
        ).content.decode()
        self.assertIn("Porção de batata frita", body)
        self.assertNotIn("Refrigerante lata", body)

    def test_mixed_order_ticket_omits_serve_direct_lines(self):
        """The printed ticket lists only the kitchen-preparation item."""
        order = self._make_order(
            [(self.fries, 2, "bem passada"), (self.serve_direct, 3, "")]
        )
        text = self._ticket_text(order)
        self.assertIn("2x Porcao de batata frita", text)
        self.assertIn("bem passada", text)
        self.assertNotIn("Refrigerante lata", text)
        self.assertNotIn("3x", text)

    def test_mixed_order_ticket_totals_count_only_kitchen_lines(self):
        """Totals on the ticket count only kitchen-preparation lines."""
        order = self._make_order(
            [(self.fries, 2, ""), (self.serve_direct, 3, "")]
        )
        text = self._ticket_text(order)
        lines = text.splitlines()
        itens_line = next(line for line in lines if "Total de itens:" in line)
        unidades_line = next(
            line for line in lines if "Total de unidades:" in line
        )
        # One kitchen line, two units — the serve-direct 3 units are excluded.
        self.assertTrue(itens_line.rstrip().endswith("1"), itens_line)
        self.assertTrue(unidades_line.rstrip().endswith("2"), unidades_line)
