"""Functional tests for the inventory app covering the task's acceptance criteria."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from inventory.models import Category, Item


class InventoryViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")
        cls.category = Category.objects.create(name="destilados")
        cls.item = Item.objects.create(
            name="Cerveja", category=cls.category, price=Decimal("8.50"), stock=12
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
            {
                "name": "Refrigerante",
                "category": self.category.pk,
                "price": "6.00",
                "stock": "5",
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Item.objects.filter(name="Refrigerante").exists())
        created = Item.objects.get(name="Refrigerante")
        self.assertEqual(created.stock, 5)
        self.assertEqual(created.price, Decimal("6.00"))
        self.assertTrue(created.is_active)
        self.assertEqual(created.category, self.category)

    def test_edit_persists_stock_change(self):
        resp = self.client.post(
            reverse("inventory:item-update", args=[self.item.pk]),
            {
                "name": "Cerveja",
                "category": self.category.pk,
                "price": "9.00",
                "stock": "3",
                "is_active": "on",
            },
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
            {
                "name": "Bad",
                "category": self.category.pk,
                "price": "1.00",
                "stock": "-5",
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não pode ser negativo")
        self.assertFalse(Item.objects.filter(name="Bad").exists())

    def test_form_rejects_negative_price(self):
        resp = self.client.post(
            reverse("inventory:item-create"),
            {
                "name": "Bad",
                "category": self.category.pk,
                "price": "-1.00",
                "stock": "0",
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não pode ser negativo")
        self.assertFalse(Item.objects.filter(name="Bad").exists())

    def test_form_accepts_zero_stock(self):
        resp = self.client.post(
            reverse("inventory:item-create"),
            {
                "name": "Zero",
                "category": self.category.pk,
                "price": "2.00",
                "stock": "0",
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Item.objects.filter(name="Zero", stock=0).exists())

    def test_home_links_to_inventory(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, reverse("inventory:item-list"))


class CategoryModelTests(TestCase):
    """The Category model itself: string form, ordering and uniqueness."""

    def test_str_is_the_name(self):
        category = Category.objects.create(name="sobremesas")
        self.assertEqual(str(category), "sobremesas")

    def test_default_ordering_is_alphabetical(self):
        Category.objects.create(name="zzz")
        Category.objects.create(name="aaa")
        names = list(
            Category.objects.filter(name__in=["aaa", "zzz"]).values_list(
                "name", flat=True
            )
        )
        self.assertEqual(names, ["aaa", "zzz"])

    def test_starter_categories_seeded_by_migration(self):
        """A fresh clone that runs the migrations comes up usable (#223)."""
        for name in ["bebidas não alcoólicas", "bebidas alcoólicas", "comidas"]:
            with self.subTest(name=name):
                self.assertTrue(Category.objects.filter(name=name).exists())


class CategoryViewTests(TestCase):
    """CRUD on the category screens, mirroring the item screen tests."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")
        cls.category = Category.objects.create(name="petiscos")

    def setUp(self):
        self.client.force_login(self.user)

    def test_list_shows_categories(self):
        resp = self.client.get(reverse("inventory:category-list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "petiscos")

    def test_list_is_alphabetical(self):
        """annotate() adds a GROUP BY, which drops Meta.ordering — pin it here."""
        Category.objects.create(name="aaa primeiro")
        Category.objects.create(name="zzz último")
        resp = self.client.get(reverse("inventory:category-list"))
        names = [c.name for c in resp.context["categories"]]
        self.assertEqual(names, sorted(names))
        self.assertEqual(names[0], "aaa primeiro")
        self.assertEqual(names[-1], "zzz último")

    def test_list_shows_item_count(self):
        Item.objects.create(
            name="Amendoim", category=self.category, price=Decimal("5.00"), stock=3
        )
        resp = self.client.get(reverse("inventory:category-list"))
        listed = {c.name: c.item_count for c in resp.context["categories"]}
        self.assertEqual(listed["petiscos"], 1)

    def test_create_category_via_post(self):
        resp = self.client.post(
            reverse("inventory:category-create"), {"name": "drinks"}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Category.objects.filter(name="drinks").exists())

    def test_edit_category_persists_rename(self):
        resp = self.client.post(
            reverse("inventory:category-update", args=[self.category.pk]),
            {"name": "petiscos quentes"},
        )
        self.assertEqual(resp.status_code, 302)
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, "petiscos quentes")

    def test_delete_unused_category_succeeds(self):
        resp = self.client.post(
            reverse("inventory:category-delete", args=[self.category.pk])
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Category.objects.filter(pk=self.category.pk).exists())

    def test_duplicate_name_shows_field_error(self):
        resp = self.client.post(
            reverse("inventory:category-create"), {"name": "petiscos"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Já existe uma categoria com esse nome.")
        self.assertEqual(Category.objects.filter(name="petiscos").count(), 1)

    def test_duplicate_name_on_edit_shows_field_error(self):
        other = Category.objects.create(name="massas")
        resp = self.client.post(
            reverse("inventory:category-update", args=[other.pk]),
            {"name": "petiscos"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Já existe uma categoria com esse nome.")
        other.refresh_from_db()
        self.assertEqual(other.name, "massas")

    def test_blank_name_rejected(self):
        resp = self.client.post(reverse("inventory:category-create"), {"name": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Informe o nome da categoria.")

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        for url_name, args in [
            ("inventory:category-list", None),
            ("inventory:category-create", None),
            ("inventory:category-update", [self.category.pk]),
            ("inventory:category-delete", [self.category.pk]),
        ]:
            with self.subTest(url_name=url_name):
                resp = self.client.get(reverse(url_name, args=args))
                self.assertEqual(resp.status_code, 302)
                self.assertIn("next=", resp["Location"])

    def test_stock_page_links_to_categories(self):
        """No navbar slot for this screen, so the stock page has to lead there."""
        resp = self.client.get(reverse("inventory:item-list"))
        self.assertContains(resp, reverse("inventory:category-list"))

    def test_no_navbar_entry_for_categories(self):
        """#222 needs the last navbar slot; categories must not take it."""
        resp = self.client.get(reverse("core:home"))
        self.assertNotContains(resp, reverse("inventory:category-list"))


class CategoryInUseTests(TestCase):
    """Item.category is PROTECT: a category in use cannot be deleted."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")
        cls.category = Category.objects.create(name="destilados")
        cls.item = Item.objects.create(
            name="Cerveja", category=cls.category, price=Decimal("8.50"), stock=12
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_delete_in_use_category_is_refused(self):
        resp = self.client.post(
            reverse("inventory:category-delete", args=[self.category.pk]),
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não pode ser excluída")
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())
        self.assertTrue(Item.objects.filter(pk=self.item.pk).exists())

    def test_confirm_page_warns_before_the_click(self):
        resp = self.client.get(
            reverse("inventory:category-delete", args=[self.category.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não pode ser excluída")

    def test_item_list_shows_the_category(self):
        resp = self.client.get(reverse("inventory:item-list"))
        self.assertContains(resp, "destilados")

    def test_item_form_requires_a_category(self):
        resp = self.client.post(
            reverse("inventory:item-create"),
            {"name": "Sem categoria", "price": "3.00", "stock": "1", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Selecione a categoria do item.")
        self.assertFalse(Item.objects.filter(name="Sem categoria").exists())

    def test_item_form_rejects_unknown_category(self):
        resp = self.client.post(
            reverse("inventory:item-create"),
            {
                "name": "Categoria fantasma",
                "category": 999999,
                "price": "3.00",
                "stock": "1",
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Categoria inválida.")
        self.assertFalse(Item.objects.filter(name="Categoria fantasma").exists())

    def test_editing_an_item_can_move_it_to_another_category(self):
        other = Category.objects.create(name="porções")
        resp = self.client.post(
            reverse("inventory:item-update", args=[self.item.pk]),
            {
                "name": "Cerveja",
                "category": other.pk,
                "price": "8.50",
                "stock": "12",
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.category, other)
