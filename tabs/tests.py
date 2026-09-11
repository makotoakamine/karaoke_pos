"""Functional tests for the tabs app covering the task's acceptance criteria."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from inventory.models import Category, Item
from orders.models import Order, OrderItem
from tables.models import Table
from tabs.models import Tab


class TabViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")
        cls.table = Table.objects.create(name="Mesa 1", seats=4)

    def setUp(self):
        self.client.force_login(self.user)

    # -- creating -----------------------------------------------------------
    def test_create_with_only_a_name_starts_open(self):
        resp = self.client.post(reverse("tabs:tab-create"), {"name": "Maria", "table": ""})
        self.assertEqual(resp.status_code, 302)
        tab = Tab.objects.get(name="Maria")
        self.assertEqual(tab.status, "open")
        self.assertIsNone(tab.table)
        self.assertIsNone(tab.closed_at)

    def test_create_with_a_table(self):
        resp = self.client.post(
            reverse("tabs:tab-create"),
            {"name": "Turma do fundo", "table": str(self.table.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        tab = Tab.objects.get(name="Turma do fundo")
        self.assertEqual(tab.table, self.table)

    def test_duplicate_open_name_rejected_with_message_and_nothing_saved(self):
        Tab.objects.create(name="Maria")
        resp = self.client.post(reverse("tabs:tab-create"), {"name": "Maria", "table": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Já existe uma comanda aberta com o nome")
        self.assertEqual(Tab.objects.filter(name="Maria").count(), 1)

    def test_duplicate_open_name_is_case_insensitive(self):
        Tab.objects.create(name="Maria")
        resp = self.client.post(reverse("tabs:tab-create"), {"name": "maria", "table": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Tab.objects.count(), 1)

    def test_name_reusable_after_previous_tab_closed(self):
        first = Tab.objects.create(name="Maria")
        first.close()
        resp = self.client.post(reverse("tabs:tab-create"), {"name": "Maria", "table": ""})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Tab.objects.filter(name="Maria").count(), 2)
        self.assertEqual(Tab.objects.filter(name="Maria", status="open").count(), 1)

    # -- overview -----------------------------------------------------------
    def test_open_list_shows_name_table_and_status(self):
        Tab.objects.create(name="Maria", table=self.table)
        resp = self.client.get(reverse("tabs:tab-list"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Maria", body)
        self.assertIn("Mesa 1", body)
        self.assertIn("Aberta", body)
        self.assertIn("karaoke-chip-on", body)

    def test_tab_without_table_shows_empty_marker(self):
        Tab.objects.create(name="Avulsa")
        resp = self.client.get(reverse("tabs:tab-list"))
        self.assertContains(resp, "sem mesa")

    def test_closed_tabs_not_in_open_list_but_reachable_from_same_screen(self):
        closed = Tab.objects.create(name="Fechada")
        closed.close()
        Tab.objects.create(name="Aberta agora")

        open_list = self.client.get(reverse("tabs:tab-list"))
        body = open_list.content.decode()
        self.assertIn("Aberta agora", body)
        self.assertNotIn("&gt;Fechada&lt;", body)
        self.assertNotIn(">Fechada<", body)
        # the closed listing is one link away, on the very same view
        self.assertIn("?status=closed", body)

        closed_list = self.client.get(reverse("tabs:tab-list"), {"status": "closed"})
        closed_body = closed_list.content.decode()
        self.assertIn("Fechada", closed_body)
        self.assertNotIn("Aberta agora", closed_body)

    # -- closing ------------------------------------------------------------
    def test_close_from_overview(self):
        tab = Tab.objects.create(name="Maria")
        resp = self.client.post(reverse("tabs:tab-list"), {"tab_id": tab.pk}, follow=True)
        self.assertEqual(resp.status_code, 200)
        tab.refresh_from_db()
        self.assertEqual(tab.status, "closed")
        self.assertIsNotNone(tab.closed_at)
        self.assertContains(resp, "fechada")
        # and it left the open list
        self.assertNotIn(">Maria<", resp.content.decode())

    def test_close_unknown_tab_reports_error(self):
        resp = self.client.post(reverse("tabs:tab-list"), {"tab_id": 9999}, follow=True)
        self.assertContains(resp, "não encontrada")

    # -- editing ------------------------------------------------------------
    def test_edit_name_and_table_visible_on_overview(self):
        tab = Tab.objects.create(name="Maria")
        resp = self.client.post(
            reverse("tabs:tab-update", args=[tab.pk]),
            {"name": "Maria e João", "table": str(self.table.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        tab.refresh_from_db()
        self.assertEqual(tab.name, "Maria e João")
        self.assertEqual(tab.table, self.table)

        overview = self.client.get(reverse("tabs:tab-list"))
        body = overview.content.decode()
        self.assertIn("Maria e João", body)
        self.assertIn("Mesa 1", body)

    def test_edit_can_clear_the_table(self):
        tab = Tab.objects.create(name="Maria", table=self.table)
        self.client.post(
            reverse("tabs:tab-update", args=[tab.pk]), {"name": "Maria", "table": ""}
        )
        tab.refresh_from_db()
        self.assertIsNone(tab.table)

    def test_edit_does_not_trip_over_its_own_name(self):
        tab = Tab.objects.create(name="Maria")
        resp = self.client.post(
            reverse("tabs:tab-update", args=[tab.pk]),
            {"name": "Maria", "table": str(self.table.pk)},
        )
        self.assertEqual(resp.status_code, 302)

    # -- table lifecycle ----------------------------------------------------
    def test_tab_survives_its_table_being_retired(self):
        tab = Tab.objects.create(name="Maria", table=self.table)
        self.table.is_active = False
        self.table.save()

        overview = self.client.get(reverse("tabs:tab-list"))
        self.assertEqual(overview.status_code, 200)
        self.assertContains(overview, "Maria")

        edit = self.client.get(reverse("tabs:tab-update", args=[tab.pk]))
        self.assertEqual(edit.status_code, 200)
        # the retired table is still selectable so saving does not clear it
        resp = self.client.post(
            reverse("tabs:tab-update", args=[tab.pk]),
            {"name": "Maria", "table": str(self.table.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        tab.refresh_from_db()
        self.assertEqual(tab.table, self.table)

    def test_tab_survives_its_table_being_deleted(self):
        tab = Tab.objects.create(name="Maria", table=self.table)
        self.table.delete()
        tab.refresh_from_db()
        self.assertIsNone(tab.table)

        overview = self.client.get(reverse("tabs:tab-list"))
        self.assertEqual(overview.status_code, 200)
        self.assertContains(overview, "Maria")
        self.assertContains(overview, "sem mesa")
        self.assertEqual(
            self.client.get(reverse("tabs:tab-update", args=[tab.pk])).status_code, 200
        )

    # -- access control -----------------------------------------------------
    def test_anonymous_redirected_to_login(self):
        tab = Tab.objects.create(name="Maria")
        self.client.logout()
        for url_name, args in [
            ("tabs:tab-list", None),
            ("tabs:tab-create", None),
            ("tabs:tab-detail", [tab.pk]),
            ("tabs:tab-update", [tab.pk]),
        ]:
            with self.subTest(url_name=url_name):
                resp = self.client.get(reverse(url_name, args=args))
                self.assertEqual(resp.status_code, 302)
                self.assertIn("next=", resp["Location"])

    def test_anonymous_close_redirected_to_login(self):
        tab = Tab.objects.create(name="Maria")
        self.client.logout()
        resp = self.client.post(reverse("tabs:tab-list"), {"tab_id": tab.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("next=", resp["Location"])
        tab.refresh_from_db()
        self.assertEqual(tab.status, "open")

    # -- navigation ---------------------------------------------------------
    def test_home_links_to_tabs(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, reverse("tabs:tab-list"))

    def test_navbar_links_to_tabs(self):
        # the navbar lives in base.html, so any authenticated page carries it
        resp = self.client.get(reverse("tables:table-list"))
        self.assertContains(resp, reverse("tabs:tab-list"))

    # -- theme --------------------------------------------------------------
    def test_pages_reuse_the_dark_theme_classes(self):
        Tab.objects.create(name="Maria")
        for url in [reverse("tabs:tab-list"), reverse("tabs:tab-create")]:
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                self.assertIn("karaoke-page-header", body)
                # no rounded / light-theme leftovers
                self.assertNotIn("rounded", body)
                self.assertNotIn("shadow-sm", body)
                self.assertNotIn("bg-light", body)
                self.assertNotIn("table-light", body)


class TabDetailViewTests(TestCase):
    """The read-only slip: orders, subtotals and the tab's running total."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")
        cls.table = Table.objects.create(name="Mesa 1", seats=4)
        cls.category = Category.objects.create(name="Bebidas")
        cls.beer = Item.objects.create(
            name="Cerveja", category=cls.category, price=Decimal("10.00"), stock=100
        )
        cls.soda = Item.objects.create(
            name="Refrigerante", category=cls.category, price=Decimal("7.50"), stock=100
        )

    def setUp(self):
        self.client.force_login(self.user)

    # -- helpers ------------------------------------------------------------
    def _order(self, tab, *lines, placed_at=None, status=Order.Status.OPEN):
        """Create an order on ``tab`` from ``(item, quantity, unit_price)`` lines.

        ``unit_price`` is passed in rather than read off the item so the tests
        can model an order placed *before* a price edit.
        """
        order = Order.objects.create(tab=tab, status=status)
        for item, quantity, unit_price in lines:
            OrderItem.objects.create(
                order=order, item=item, quantity=quantity, unit_price=unit_price
            )
        if placed_at is not None:
            # created_at is auto_now_add, so it can only be backdated with an
            # UPDATE that bypasses the model's save().
            Order.objects.filter(pk=order.pk).update(created_at=placed_at)
            order.refresh_from_db()
        return order

    def _get(self, tab):
        return self.client.get(reverse("tabs:tab-detail", args=[tab.pk]))

    def _main(self, resp):
        """Just the page's own markup, without base.html's navbar and footer.

        The navbar carries the logout form, so "does this page mutate
        anything?" can only be asked of the <main> slice.
        """
        body = resp.content.decode()
        start = body.index("<main")
        return body[start:body.index("</main>", start)]

    # -- reachability and access -------------------------------------------
    def test_detail_reachable_and_linked_from_every_row_of_the_list(self):
        first = Tab.objects.create(name="Maria")
        second = Tab.objects.create(name="João")

        listing = self.client.get(reverse("tabs:tab-list"))
        for tab in (first, second):
            self.assertContains(listing, reverse("tabs:tab-detail", args=[tab.pk]))

        self.assertEqual(self._get(first).status_code, 200)

    def test_anonymous_redirected_to_login(self):
        tab = Tab.objects.create(name="Maria")
        self.client.logout()
        resp = self._get(tab)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("core:login"), resp["Location"])
        self.assertIn("next=", resp["Location"])

    # -- identity -----------------------------------------------------------
    def test_shows_name_open_state_and_linked_table(self):
        tab = Tab.objects.create(name="Maria", table=self.table)
        resp = self._get(tab)
        self.assertContains(resp, "Maria")
        self.assertContains(resp, "Mesa 1")
        self.assertContains(resp, "Aberta")
        self.assertContains(resp, "karaoke-chip-on")

    def test_tab_without_table_renders_an_explicit_marker(self):
        tab = Tab.objects.create(name="Avulsa")
        resp = self._get(tab)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "sem mesa")

    def test_closed_tab_shows_closed_state(self):
        tab = Tab.objects.create(name="Maria")
        tab.close()
        resp = self._get(tab)
        self.assertContains(resp, "Fechada")
        self.assertContains(resp, "karaoke-chip-off")

    # -- orders -------------------------------------------------------------
    def test_lists_every_order_oldest_first_with_time_status_and_lines(self):
        tab = Tab.objects.create(name="Maria")
        now = timezone.now()
        self._order(
            tab,
            (self.soda, 1, Decimal("7.50")),
            placed_at=now,
            status=Order.Status.DONE,
        )
        self._order(
            tab, (self.beer, 2, Decimal("10.00")), placed_at=now - timedelta(hours=1)
        )

        body = self._get(tab).content.decode()
        # the older order (beer) is rendered above the newer one (soda)
        self.assertLess(body.index("Cerveja"), body.index("Refrigerante"))
        # each line carries item name, quantity and unit price
        self.assertIn("R$ 10.00", body)
        self.assertIn("R$ 7.50", body)
        # and each order its own status
        self.assertIn("Encerrada", body)
        self.assertIn("Aberta", body)

    def test_orders_of_other_tabs_are_not_listed(self):
        tab = Tab.objects.create(name="Maria")
        other = Tab.objects.create(name="João")
        self._order(tab, (self.beer, 1, Decimal("10.00")))
        self._order(other, (self.soda, 3, Decimal("7.50")))

        body = self._get(tab).content.decode()
        self.assertIn("Cerveja", body)
        self.assertNotIn("Refrigerante", body)
        self.assertIn("R$ 10.00", body)

    # -- money --------------------------------------------------------------
    def test_order_subtotals_and_running_total(self):
        tab = Tab.objects.create(name="Maria")
        # 2 x 10.00 + 1 x 7.50 = 27.50
        self._order(
            tab, (self.beer, 2, Decimal("10.00")), (self.soda, 1, Decimal("7.50"))
        )
        # 3 x 10.00 = 30.00 -> tab total 57.50
        self._order(tab, (self.beer, 3, Decimal("10.00")))

        resp = self._get(tab)
        self.assertEqual(resp.context["total"], Decimal("57.50"))
        body = resp.content.decode()
        self.assertIn("R$ 27.50", body)
        self.assertIn("R$ 30.00", body)
        self.assertIn("R$ 57.50", body)
        self.assertIn("Total da comanda", body)

    def test_total_uses_the_price_snapshot_not_the_current_catalogue_price(self):
        tab = Tab.objects.create(name="Maria")
        self._order(tab, (self.beer, 2, Decimal("10.00")))

        before = self._get(tab).context["total"]
        self.assertEqual(before, Decimal("20.00"))

        # the bar raises the price after the round was served
        self.beer.price = Decimal("99.00")
        self.beer.save(update_fields=["price"])

        resp = self._get(tab)
        self.assertEqual(resp.context["total"], Decimal("20.00"))
        body = resp.content.decode()
        self.assertIn("R$ 20.00", body)
        self.assertNotIn("99.00", body)

    def test_totals_survive_a_price_edit_made_through_the_inventory_page(self):
        tab = Tab.objects.create(name="Maria")
        self._order(tab, (self.beer, 2, Decimal("10.00")))

        resp = self.client.post(
            reverse("inventory:item-update", args=[self.beer.pk]),
            {
                "name": "Cerveja",
                "category": str(self.category.pk),
                "price": "99.00",
                "stock": "100",
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.beer.refresh_from_db()
        self.assertEqual(self.beer.price, Decimal("99.00"))

        self.assertEqual(self._get(tab).context["total"], Decimal("20.00"))

    def test_empty_tab_shows_empty_state_and_a_zero_total(self):
        tab = Tab.objects.create(name="Recém-aberta")
        resp = self._get(tab)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total"], Decimal("0.00"))
        self.assertContains(resp, "Nenhum pedido nesta comanda ainda.")
        self.assertContains(resp, "R$ 0.00")

    def test_closed_tab_keeps_its_orders_and_total(self):
        tab = Tab.objects.create(name="Maria", table=self.table)
        self._order(tab, (self.beer, 2, Decimal("10.00")))
        tab.close()

        resp = self._get(tab)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total"], Decimal("20.00"))
        body = resp.content.decode()
        self.assertIn("Cerveja", body)
        self.assertIn("R$ 20.00", body)
        self.assertIn("Mesa 1", body)

    # -- read-only guarantee ------------------------------------------------
    def test_page_carries_no_controls_that_change_data(self):
        tab = Tab.objects.create(name="Maria", table=self.table)
        self._order(tab, (self.beer, 2, Decimal("10.00")))
        tab.close()

        cases = [("aberta", Tab.objects.create(name="Aberta agora")), ("fechada", tab)]
        for label, current in cases:
            with self.subTest(tab=label):
                main = self._main(self._get(current))
                self.assertNotIn("<form", main)
                self.assertNotIn("csrfmiddlewaretoken", main)
                self.assertNotIn("<button", main)
                self.assertNotIn("method=\"post\"", main)
                # nor a link into any screen that mutates this tab or its orders
                self.assertNotIn(reverse("tabs:tab-update", args=[current.pk]), main)
                self.assertNotIn("Fechar", main)
                self.assertNotIn("Pagar", main)
                self.assertNotIn("Excluir", main)

    def test_get_does_not_touch_the_tab_or_its_orders(self):
        tab = Tab.objects.create(name="Maria", table=self.table)
        order = self._order(tab, (self.beer, 2, Decimal("10.00")))
        before = (tab.status, tab.updated_at, order.status, self.beer.stock)

        self.assertEqual(self._get(tab).status_code, 200)

        tab.refresh_from_db()
        order.refresh_from_db()
        self.beer.refresh_from_db()
        self.assertEqual(
            (tab.status, tab.updated_at, order.status, self.beer.stock), before
        )

    def test_post_is_not_allowed(self):
        tab = Tab.objects.create(name="Maria")
        resp = self.client.post(reverse("tabs:tab-detail", args=[tab.pk]), {})
        self.assertEqual(resp.status_code, 405)

    # -- query budget -------------------------------------------------------
    def test_query_count_stays_flat_as_orders_are_added(self):
        tab = Tab.objects.create(name="Maria", table=self.table)
        self._order(tab, (self.beer, 1, Decimal("10.00")))

        url = reverse("tabs:tab-detail", args=[tab.pk])
        with CaptureQueriesContext(connection) as one_order:
            self.assertEqual(self.client.get(url).status_code, 200)

        for _ in range(5):
            self._order(
                tab,
                (self.beer, 2, Decimal("10.00")),
                (self.soda, 3, Decimal("7.50")),
            )

        with CaptureQueriesContext(connection) as many_orders:
            self.assertEqual(self.client.get(url).status_code, 200)

        self.assertEqual(len(many_orders), len(one_order))

    # -- theme --------------------------------------------------------------
    def test_page_reuses_the_dark_theme_classes(self):
        tab = Tab.objects.create(name="Maria", table=self.table)
        self._order(tab, (self.beer, 1, Decimal("10.00")))
        body = self._get(tab).content.decode()
        self.assertIn("karaoke-page-header", body)
        self.assertIn("karaoke-table", body)
        self.assertIn("karaoke-chip", body)
        # no rounded / light-theme leftovers
        self.assertNotIn("rounded", body)
        self.assertNotIn("shadow-sm", body)
        self.assertNotIn("bg-light", body)
        self.assertNotIn("table-light", body)
