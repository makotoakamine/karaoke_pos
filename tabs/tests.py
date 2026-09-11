"""Functional tests for the tabs app covering the task's acceptance criteria."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

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
