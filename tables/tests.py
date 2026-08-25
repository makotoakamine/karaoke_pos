"""Functional tests for the tables app covering the task's acceptance criteria."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from tables.models import Table


class TableViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")
        cls.table = Table.objects.create(name="Mesa 1", seats=4)

    def setUp(self):
        self.client.force_login(self.user)

    def test_new_table_defaults_free(self):
        self.assertEqual(self.table.status, "free")
        self.assertTrue(self.table.is_active)

    def test_list_shows_active_tables_with_status_badges(self):
        resp = self.client.get(reverse("tables:table-list"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Mesa 1", body)
        self.assertIn("4", body)
        self.assertIn("Livre", body)
        # toggle-to-occupy button is shown for free tables
        self.assertIn("Marcar ocupada", body)

    def test_free_and_occupied_badges_distinguishable(self):
        self.table.status = "occupied"
        self.table.save()
        resp = self.client.get(reverse("tables:table-list"))
        body = resp.content.decode()
        self.assertIn('bg-danger', body)
        self.table.status = "free"
        self.table.save()
        resp = self.client.get(reverse("tables:table-list"))
        body = resp.content.decode()
        self.assertIn('bg-success', body)

    def test_create_table_via_post(self):
        resp = self.client.post(
            reverse("tables:table-create"),
            {"name": "Mesa 2", "seats": "6", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        created = Table.objects.get(name="Mesa 2")
        self.assertEqual(created.seats, 6)
        self.assertEqual(created.status, "free")
        self.assertTrue(created.is_active)

    def test_create_rejects_duplicate_name(self):
        resp = self.client.post(
            reverse("tables:table-create"),
            {"name": "Mesa 1", "seats": "2", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Table.objects.filter(name="Mesa 1", seats=2).exists())

    def test_edit_persists_change(self):
        resp = self.client.post(
            reverse("tables:table-update", args=[self.table.pk]),
            {"name": "Mesa 1", "seats": "8", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        self.table.refresh_from_db()
        self.assertEqual(self.table.seats, 8)

    def test_toggle_free_to_occupied(self):
        resp = self.client.post(
            reverse("tables:table-list"),
            {"table_id": self.table.pk},
        )
        self.assertEqual(resp.status_code, 302)
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, "occupied")

    def test_toggle_occupied_to_free(self):
        self.table.status = "occupied"
        self.table.save()
        self.client.post(reverse("tables:table-list"), {"table_id": self.table.pk})
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, "free")

    def test_toggle_persists_after_reload(self):
        self.client.post(reverse("tables:table-list"), {"table_id": self.table.pk})
        # simulate "reload" by re-fetching from DB in a fresh request
        fresh = Table.objects.get(pk=self.table.pk)
        self.assertEqual(fresh.status, "occupied")

    def test_deactivate_hides_from_overview_not_deleted(self):
        self.table.is_active = False
        self.table.save()
        resp = self.client.get(reverse("tables:table-list"))
        body = resp.content.decode()
        self.assertNotIn("Mesa 1", body)
        self.assertTrue(Table.objects.filter(pk=self.table.pk).exists())

    def test_edit_can_deactivate(self):
        resp = self.client.post(
            reverse("tables:table-update", args=[self.table.pk]),
            {"name": "Mesa 1", "seats": "4"},
        )
        self.assertEqual(resp.status_code, 302)
        self.table.refresh_from_db()
        self.assertFalse(self.table.is_active)

    def test_form_rejects_zero_seats(self):
        resp = self.client.post(
            reverse("tables:table-create"),
            {"name": "Bad", "seats": "0", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "pelo menos 1 lugar")
        self.assertFalse(Table.objects.filter(name="Bad").exists())

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        for url_name, args in [
            ("tables:table-list", None),
            ("tables:table-create", None),
            ("tables:table-update", [self.table.pk]),
        ]:
            with self.subTest(url_name=url_name):
                resp = self.client.get(reverse(url_name, args=args))
                self.assertEqual(resp.status_code, 302)
                self.assertIn("next=", resp["Location"])

    def test_anonymous_toggle_redirected_to_login(self):
        self.client.logout()
        resp = self.client.post(reverse("tables:table-list"), {"table_id": self.table.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("next=", resp["Location"])
        # state must not change for anonymous users
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, "free")

    def test_home_links_to_tables(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, reverse("tables:table-list"))

    def test_navbar_links_to_tables(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, reverse("tables:table-list"))