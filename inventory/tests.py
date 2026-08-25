"""Functional tests for the inventory app covering the task's acceptance criteria."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from inventory.models import Item


class InventoryViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")
        cls.item = Item.objects.create(
            name="Cerveja", price=Decimal("8.50"), stock=12
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_item_list_shows_name_price_stock_active(self):
        resp = self.client.get(reverse("inventory:item-list"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Cerveja", body)
        self.assertIn("8.50", body)
        self.assertIn("12", body)
        self.assertIn("sim", body)

    def test_create_item_via_post(self):
        resp = self.client.post(
            reverse("inventory:item-create"),
            {"name": "Refrigerante", "price": "6.00", "stock": "5", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Item.objects.filter(name="Refrigerante").exists())
        created = Item.objects.get(name="Refrigerante")
        self.assertEqual(created.stock, 5)
        self.assertEqual(created.price, Decimal("6.00"))
        self.assertTrue(created.is_active)

    def test_edit_persists_stock_change(self):
        resp = self.client.post(
            reverse("inventory:item-update", args=[self.item.pk]),
            {"name": "Cerveja", "price": "9.00", "stock": "3", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 3)
        self.assertEqual(self.item.price, Decimal("9.00"))

    def test_deactivate_item_shown_distinct_on_list(self):
        self.item.is_active = False
        self.item.save()
        resp = self.client.get(reverse("inventory:item-list"))
        body = resp.content.decode()
        self.assertIn("inativo", body)

    def test_delete_removes_item(self):
        resp = self.client.post(
            reverse("inventory:item-delete", args=[self.item.pk])
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Item.objects.filter(pk=self.item.pk).exists())

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        for url_name, args in [
            ("inventory:item-list", None),
            ("inventory:item-create", None),
            ("inventory:item-update", [self.item.pk]),
            ("inventory:item-delete", [self.item.pk]),
        ]:
            with self.subTest(url_name=url_name):
                resp = self.client.get(reverse(url_name, args=args))
                self.assertEqual(resp.status_code, 302)
                self.assertIn("next=", resp["Location"])

    def test_form_rejects_negative_stock(self):
        resp = self.client.post(
            reverse("inventory:item-create"),
            {"name": "Bad", "price": "1.00", "stock": "-5", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não pode ser negativo")
        self.assertFalse(Item.objects.filter(name="Bad").exists())

    def test_form_rejects_negative_price(self):
        resp = self.client.post(
            reverse("inventory:item-create"),
            {"name": "Bad", "price": "-1.00", "stock": "0", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não pode ser negativo")
        self.assertFalse(Item.objects.filter(name="Bad").exists())

    def test_form_accepts_zero_stock(self):
        resp = self.client.post(
            reverse("inventory:item-create"),
            {"name": "Zero", "price": "2.00", "stock": "0", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Item.objects.filter(name="Zero", stock=0).exists())

    def test_home_links_to_inventory(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, reverse("inventory:item-list"))