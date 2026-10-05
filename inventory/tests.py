"""Functional tests for the inventory app covering the task's acceptance criteria."""
from decimal import Decimal
from io import BytesIO, StringIO

import openpyxl

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from inventory.importers import SpreadsheetImportError, import_items
from inventory.models import Category, Item, NoteSuggestion
from inventory.management.commands.seed_demo import (
    NAO_ALCOOLICAS,
    ALCOOLICAS,
    COMIDAS,
)


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

    def test_new_item_defaults_to_requiring_kitchen_preparation(self):
        """The model default is True — food never silently hides from the cook."""
        item = Item.objects.create(
            name="Porção", category=self.category, price=Decimal("20.00"), stock=10
        )
        self.assertTrue(item.requires_kitchen_preparation)

    def test_edit_persists_kitchen_preparation_off(self):
        """Saving with the switch unchecked stores False and survives a reload."""
        resp = self.client.post(
            reverse("inventory:item-update", args=[self.item.pk]),
            {
                "name": "Cerveja",
                "category": self.category.pk,
                "price": "8.50",
                "stock": "12",
                "is_active": "on",
                # requires_kitchen_preparation left off -> False
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertFalse(self.item.requires_kitchen_preparation)

        # A second edit turning it back on restores True.
        resp = self.client.post(
            reverse("inventory:item-update", args=[self.item.pk]),
            {
                "name": "Cerveja",
                "category": self.category.pk,
                "price": "8.50",
                "stock": "12",
                "is_active": "on",
                "requires_kitchen_preparation": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.item.refresh_from_db()
        self.assertTrue(self.item.requires_kitchen_preparation)

    def test_item_form_shows_the_kitchen_switch(self):
        resp = self.client.get(reverse("inventory:item-create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Requer preparo na cozinha")
        self.assertContains(resp, 'name="requires_kitchen_preparation"')

    def test_item_list_shows_kitchen_column(self):
        resp = self.client.get(reverse("inventory:item-list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cozinha")


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


class SeedDemoCommandTests(TestCase):
    """``manage.py seed_demo`` populates a demo catalogue and is re-runnable (#227)."""

    def run_command(self):
        out = StringIO()
        call_command("seed_demo", stdout=out)
        return out.getvalue()

    def test_seeds_items_across_the_three_starter_categories(self):
        self.run_command()
        names = set(Category.objects.values_list("name", flat=True))
        self.assertEqual(
            names,
            {"bebidas não alcoólicas", "bebidas alcoólicas", "comidas"},
        )
        for name in names:
            with self.subTest(category=name):
                self.assertGreater(Category.objects.get(name=name).items.count(), 0)
        self.assertGreaterEqual(Item.objects.count(), 12)
        self.assertLessEqual(Item.objects.count(), 20)

    def test_reuses_the_categories_from_migration_0003(self):
        """Rows already exist from the data migration; none may be duplicated."""
        before = {c.pk: c.name for c in Category.objects.all()}
        self.assertEqual(len(before), 3, "migration 0003 should have seeded 3 rows")
        self.run_command()
        after = {c.pk: c.name for c in Category.objects.all()}
        self.assertEqual(before, after)

    def test_seeded_items_have_sensible_prices_and_stock(self):
        self.run_command()
        for item in Item.objects.all():
            with self.subTest(item=item.name):
                self.assertGreater(item.price, Decimal("0"))
                self.assertEqual(item.price, item.price.quantize(Decimal("0.01")))
                self.assertGreaterEqual(item.stock, 10)
                self.assertLessEqual(item.stock, 100)

    def test_at_least_one_seeded_item_is_inactive(self):
        self.run_command()
        self.assertTrue(Item.objects.filter(is_active=False).exists())
        self.assertTrue(Item.objects.filter(is_active=True).exists())

    def test_second_invocation_creates_nothing_new(self):
        self.run_command()
        items = {(i.pk, i.name, i.category_id) for i in Item.objects.all()}
        categories = set(Category.objects.values_list("pk", flat=True))

        output = self.run_command()

        self.assertEqual({(i.pk, i.name, i.category_id) for i in Item.objects.all()}, items)
        self.assertEqual(set(Category.objects.values_list("pk", flat=True)), categories)
        self.assertIn("já existiam", output)

    def test_rerun_leaves_a_hand_edited_item_untouched(self):
        self.run_command()
        edited = Item.objects.filter(is_active=True).first()
        edited.price = Decimal("123.45")
        edited.stock = 99
        edited.save()

        self.run_command()

        edited.refresh_from_db()
        self.assertEqual(edited.price, Decimal("123.45"))
        self.assertEqual(edited.stock, 99)

    def test_reports_what_it_created(self):
        output = self.run_command()
        self.assertIn("Itens criados:", output)

    def test_drinks_seeded_without_kitchen_preparation(self):
        """Bebidas (alcoólicas e não alcoólicas) are served directly; comidas go to the kitchen."""
        self.run_command()
        drinks = Item.objects.filter(
            category__name__in=[NAO_ALCOOLICAS, ALCOOLICAS]
        )
        self.assertTrue(drinks.exists())
        for item in drinks:
            with self.subTest(item=item.name):
                self.assertFalse(item.requires_kitchen_preparation)
        comidas = Item.objects.filter(category__name=COMIDAS)
        self.assertTrue(comidas.exists())
        for item in comidas:
            with self.subTest(item=item.name):
                self.assertTrue(item.requires_kitchen_preparation)

    def test_rerun_leaves_existing_kitchen_flag_untouched(self):
        """Seed is additive: a hand-edited flag survives a second run."""
        self.run_command()
        edited = Item.objects.filter(category__name=COMIDAS).first()
        edited.requires_kitchen_preparation = False
        edited.save()

        self.run_command()

        edited.refresh_from_db()
        self.assertFalse(edited.requires_kitchen_preparation)

    def test_stock_page_lists_the_seeded_catalogue(self):
        self.run_command()
        user = User.objects.create_user("seeder", password="secret123")
        self.client.force_login(user)
        resp = self.client.get(reverse("inventory:item-list"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for item in Item.objects.all():
            with self.subTest(item=item.name):
                self.assertIn(item.name, body)
                self.assertIn(item.category.name, body)

    def test_order_page_offers_the_seeded_items_and_category_filters(self):
        self.run_command()
        user = User.objects.create_user("seeder", password="secret123")
        self.client.force_login(user)
        resp = self.client.get(reverse("orders:order-create"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for item in Item.objects.filter(is_active=True, stock__gt=0):
            with self.subTest(item=item.name):
                self.assertIn(item.name, body)
        for name in ["bebidas não alcoólicas", "bebidas alcoólicas", "comidas"]:
            with self.subTest(category=name):
                self.assertIn(name, body)


class NoteSuggestionModelTests(TestCase):
    """The NoteSuggestion model itself: ordering, uniqueness and cascade (#230)."""

    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="refrigerantes")
        cls.coca = Item.objects.create(
            name="Coca-Cola", category=cls.category, price=Decimal("8.00"), stock=20
        )
        cls.guarana = Item.objects.create(
            name="Guaraná", category=cls.category, price=Decimal("8.00"), stock=20
        )

    def test_str_is_the_text(self):
        suggestion = NoteSuggestion.objects.create(item=self.coca, text="gelo")
        self.assertEqual(str(suggestion), "gelo")

    def test_default_ordering_is_by_text(self):
        NoteSuggestion.objects.create(item=self.coca, text="rodela de limão")
        NoteSuggestion.objects.create(item=self.coca, text="gelo")
        self.assertEqual(
            list(self.coca.note_suggestions.values_list("text", flat=True)),
            ["gelo", "rodela de limão"],
        )

    def test_same_text_allowed_on_two_different_items(self):
        NoteSuggestion.objects.create(item=self.coca, text="gelo")
        NoteSuggestion.objects.create(item=self.guarana, text="gelo")
        self.assertEqual(NoteSuggestion.objects.filter(text="gelo").count(), 2)

    def test_same_text_twice_on_one_item_is_refused(self):
        NoteSuggestion.objects.create(item=self.coca, text="gelo")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                NoteSuggestion.objects.create(item=self.coca, text="gelo")

    def test_deleting_the_item_deletes_its_suggestions(self):
        NoteSuggestion.objects.create(item=self.coca, text="gelo")
        NoteSuggestion.objects.create(item=self.guarana, text="gelo")

        self.coca.delete()

        self.assertFalse(NoteSuggestion.objects.filter(item_id=self.coca.pk).exists())
        # The other item's identically-named chip is untouched.
        self.assertEqual(self.guarana.note_suggestions.count(), 1)


class NoteSuggestionFormTests(TestCase):
    """The textarea round-trip on the item create/edit screens (#230)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")
        cls.category = Category.objects.create(name="refrigerantes")

    def setUp(self):
        self.client.force_login(self.user)

    def post_item(self, url, name="Coca-Cola", suggestions=""):
        return self.client.post(
            url,
            {
                "name": name,
                "category": self.category.pk,
                "price": "8.00",
                "stock": "20",
                "is_active": "on",
                "note_suggestions": suggestions,
            },
        )

    def create_item(self, name="Coca-Cola", suggestions=""):
        resp = self.post_item(
            reverse("inventory:item-create"), name=name, suggestions=suggestions
        )
        self.assertEqual(resp.status_code, 302)
        return Item.objects.get(name=name)

    def texts(self, item):
        return list(item.note_suggestions.values_list("text", flat=True))

    def test_create_form_offers_the_textarea(self):
        resp = self.client.get(reverse("inventory:item-create"))
        self.assertContains(resp, "Sugestões de observação")
        self.assertContains(resp, 'name="note_suggestions"')
        self.assertContains(resp, "<textarea")

    def test_create_with_suggestions_persists_them(self):
        item = self.create_item(suggestions="gelo\nrodela de limão")
        self.assertEqual(self.texts(item), ["gelo", "rodela de limão"])

    def test_create_without_suggestions_is_fine(self):
        item = self.create_item(name="Água", suggestions="")
        self.assertEqual(self.texts(item), [])

    def test_edit_prefills_the_saved_suggestions_one_per_line(self):
        item = self.create_item(suggestions="gelo\nrodela de limão")
        resp = self.client.get(reverse("inventory:item-update", args=[item.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.context["form"]["note_suggestions"].value(),
            "gelo\nrodela de limão",
        )
        self.assertContains(resp, "gelo\nrodela de limão", html=False)

    def test_edit_adds_a_line(self):
        item = self.create_item(suggestions="gelo")
        resp = self.post_item(
            reverse("inventory:item-update", args=[item.pk]),
            suggestions="gelo\nrodela de limão",
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.texts(item), ["gelo", "rodela de limão"])

    def test_edit_removes_a_line(self):
        item = self.create_item(suggestions="gelo\nrodela de limão")
        resp = self.post_item(
            reverse("inventory:item-update", args=[item.pk]), suggestions="gelo"
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.texts(item), ["gelo"])

    def test_edit_to_an_empty_textarea_clears_every_suggestion(self):
        item = self.create_item(suggestions="gelo\nrodela de limão")
        resp = self.post_item(
            reverse("inventory:item-update", args=[item.pk]), suggestions=""
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.texts(item), [])

    def test_untouched_suggestion_keeps_its_row(self):
        """Editing one line must not churn the PKs of the lines left alone."""
        item = self.create_item(suggestions="gelo\nrodela de limão")
        kept_pk = item.note_suggestions.get(text="gelo").pk
        self.post_item(
            reverse("inventory:item-update", args=[item.pk]),
            suggestions="gelo\nsem canudo",
        )
        self.assertEqual(item.note_suggestions.get(text="gelo").pk, kept_pk)

    def test_blank_lines_and_whitespace_are_ignored(self):
        item = self.create_item(suggestions="\n  gelo  \n\n\t\nrodela de limão\n\n")
        self.assertEqual(self.texts(item), ["gelo", "rodela de limão"])

    def test_duplicate_lines_are_dropped_silently(self):
        item = self.create_item(suggestions="gelo\nrodela de limão\ngelo\n  gelo  ")
        self.assertEqual(self.texts(item), ["gelo", "rodela de limão"])

    def test_duplicate_lines_on_edit_do_not_error(self):
        item = self.create_item(suggestions="gelo")
        resp = self.post_item(
            reverse("inventory:item-update", args=[item.pk]),
            suggestions="gelo\ngelo\nrodela de limão",
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.texts(item), ["gelo", "rodela de limão"])

    def test_carriage_returns_from_the_browser_are_handled(self):
        """Real browsers post CRLF line breaks in a textarea."""
        item = self.create_item(suggestions="gelo\r\nrodela de limão\r\n")
        self.assertEqual(self.texts(item), ["gelo", "rodela de limão"])

    def test_two_items_can_share_a_suggestion_text(self):
        coca = self.create_item(name="Coca-Cola", suggestions="gelo\nrodela de limão")
        guarana = self.create_item(name="Guaraná", suggestions="gelo\nrodela de laranja")
        self.assertEqual(self.texts(coca), ["gelo", "rodela de limão"])
        self.assertEqual(self.texts(guarana), ["gelo", "rodela de laranja"])

    def test_overlong_suggestion_is_rejected_with_a_readable_message(self):
        resp = self.post_item(
            reverse("inventory:item-create"),
            name="Comprida",
            suggestions="x" * 101,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "no máximo 100 caracteres")
        self.assertFalse(Item.objects.filter(name="Comprida").exists())

    def test_a_failed_save_leaves_the_suggestions_alone(self):
        """A rejected edit (negative price) must not half-apply the textarea."""
        item = self.create_item(suggestions="gelo")
        resp = self.client.post(
            reverse("inventory:item-update", args=[item.pk]),
            {
                "name": "Coca-Cola",
                "category": self.category.pk,
                "price": "-1.00",
                "stock": "20",
                "is_active": "on",
                "note_suggestions": "rodela de limão",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.texts(item), ["gelo"])
        # What the user typed is still in the box so the fix is one edit away.
        self.assertContains(resp, "rodela de limão")

    def test_deleting_the_item_from_the_screen_deletes_its_suggestions(self):
        item = self.create_item(suggestions="gelo\nrodela de limão")
        suggestion_pks = list(item.note_suggestions.values_list("pk", flat=True))
        self.assertEqual(len(suggestion_pks), 2)

        resp = self.client.post(reverse("inventory:item-delete", args=[item.pk]))

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Item.objects.filter(pk=item.pk).exists())
        self.assertFalse(NoteSuggestion.objects.filter(pk__in=suggestion_pks).exists())


class NoteSuggestionSeedDemoTests(TestCase):
    """``seed_demo`` ships the #230 chip examples and stays idempotent."""

    def run_command(self):
        out = StringIO()
        call_command("seed_demo", stdout=out)
        return out.getvalue()

    def texts_for(self, item_name):
        return list(
            Item.objects.get(name__startswith=item_name)
            .note_suggestions.values_list("text", flat=True)
        )

    def test_seeds_the_coca_cola_and_guarana_examples(self):
        self.run_command()
        self.assertEqual(self.texts_for("Coca-Cola"), ["gelo", "rodela de limão"])
        self.assertEqual(self.texts_for("Guaraná"), ["gelo", "rodela de laranja"])

    def test_the_shared_gelo_chip_exists_on_both_items(self):
        self.run_command()
        self.assertEqual(NoteSuggestion.objects.filter(text="gelo").count(), 2)

    def test_second_invocation_creates_no_extra_suggestions(self):
        self.run_command()
        before = {(s.pk, s.item_id, s.text) for s in NoteSuggestion.objects.all()}
        self.assertTrue(before)

        self.run_command()

        self.assertEqual(
            {(s.pk, s.item_id, s.text) for s in NoteSuggestion.objects.all()}, before
        )

    def test_reports_the_suggestions_it_created(self):
        self.assertIn("Sugestões de observação criadas:", self.run_command())


HEADERS = ["Categoria", "Item", "Descrição", "Estoque", "Preço", "Cozinha?", "Observações"]


def make_workbook(rows, headers=HEADERS, name="menu.xlsx"):
    """Build an .xlsx in memory: ``headers`` in row 1, then ``rows``."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(
        name,
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


SAMPLE_ROWS = [
    ["Teishoku", "Karague", "Frango empanado", 99999, 50, "S", None],
    ["Pratos Donburi", "Nikuyasai Tamanho M", "Contra-filé com legumes", 99999, 64, "S", None],
    ["Teppan na Chapa", "Nikuyasai Tamanho M", "Carne com legumes", 99999, 65, "s ", None],
    ["Bebidas Não Alcoólicas", "Água", None, 99999, 6, None, None],
    ["Cervejas", "Heineken 600ML", None, 99999, 25.5, "N", None],
    [None, None, None, None, None, None, None],
    ["Drinks", "Gin Tônica", "Drink", 99999, None, None, "Preço ilegível"],
]


class ItemImporterTests(TestCase):
    """The import function itself, without HTTP (#398)."""

    def setUp(self):
        # Start from a truly empty catalogue (0003 seeds starter categories).
        Category.objects.all().delete()

    def test_creates_categories_and_items(self):
        result = import_items(make_workbook(SAMPLE_ROWS))

        self.assertEqual(result.categories_created, 5)
        self.assertEqual(result.items_created, 5)
        self.assertEqual(result.items_updated, 0)
        self.assertEqual(Category.objects.count(), 5)
        karague = Item.objects.get(name="Karague")
        self.assertEqual(karague.category.name, "Teishoku")
        self.assertEqual(karague.price, Decimal("50.00"))
        self.assertEqual(karague.stock, 99999)
        self.assertEqual(karague.description, "Frango empanado")
        self.assertTrue(karague.is_active)
        self.assertEqual(Item.objects.get(name="Heineken 600ML").price, Decimal("25.50"))

    def test_kitchen_flag_mapping(self):
        import_items(make_workbook(SAMPLE_ROWS))

        self.assertTrue(Item.objects.get(name="Karague").requires_kitchen_preparation)
        self.assertFalse(Item.objects.get(name="Água").requires_kitchen_preparation)
        self.assertFalse(
            Item.objects.get(name="Heineken 600ML").requires_kitchen_preparation
        )
        # "s " is trimmed and case-folded.
        self.assertTrue(
            Item.objects.get(
                name="Nikuyasai Tamanho M", category__name="Teppan na Chapa"
            ).requires_kitchen_preparation
        )

    def test_same_name_in_two_categories_creates_two_items(self):
        import_items(make_workbook(SAMPLE_ROWS))

        nikuyasai = Item.objects.filter(name="Nikuyasai Tamanho M")
        self.assertEqual(nikuyasai.count(), 2)
        self.assertEqual(
            nikuyasai.get(category__name="Pratos Donburi").price, Decimal("64.00")
        )
        self.assertEqual(
            nikuyasai.get(category__name="Teppan na Chapa").price, Decimal("65.00")
        )

    def test_reupload_updates_instead_of_duplicating(self):
        import_items(make_workbook(SAMPLE_ROWS))
        karague = Item.objects.get(name="Karague")
        karague.is_active = False
        karague.save()
        untouched = Item.objects.create(
            name="Fora da planilha",
            category=karague.category,
            price=Decimal("1.00"),
            stock=3,
        )

        rows = [list(r) for r in SAMPLE_ROWS]
        rows[0] = ["teishoku", " KARAGUE ", "Novo texto", 10, 55, None, None]
        result = import_items(make_workbook(rows))

        self.assertEqual(result.categories_created, 0)
        self.assertEqual(result.items_created, 0)
        self.assertEqual(result.items_updated, 5)
        self.assertEqual(Category.objects.count(), 5)
        self.assertEqual(Item.objects.count(), 6)
        karague.refresh_from_db()
        self.assertEqual(karague.name, "Karague")
        self.assertEqual(karague.price, Decimal("55.00"))
        self.assertEqual(karague.stock, 10)
        self.assertEqual(karague.description, "Novo texto")
        self.assertFalse(karague.requires_kitchen_preparation)
        self.assertFalse(karague.is_active)  # never touched on existing items
        untouched.refresh_from_db()
        self.assertEqual(untouched.price, Decimal("1.00"))
        self.assertEqual(untouched.stock, 3)

    def test_matches_existing_category_case_insensitively_with_accents(self):
        Category.objects.create(name="BEBIDAS NÃO ALCOÓLICAS")
        result = import_items(make_workbook(SAMPLE_ROWS))

        self.assertEqual(result.categories_created, 4)
        self.assertEqual(
            Item.objects.get(name="Água").category.name, "BEBIDAS NÃO ALCOÓLICAS"
        )

    def test_row_without_price_is_skipped_and_reported(self):
        result = import_items(make_workbook(SAMPLE_ROWS))

        self.assertFalse(Item.objects.filter(name="Gin Tônica").exists())
        self.assertEqual(len(result.skipped), 1)
        skipped = result.skipped[0]
        self.assertEqual(skipped.row, 8)  # header + 6 rows above it
        self.assertEqual(skipped.name, "Gin Tônica")
        self.assertIn("preço", skipped.reason)

    def test_invalid_rows_are_skipped_with_reason(self):
        rows = [
            [None, "Sem categoria", None, 1, 10, None, None],
            ["Drinks", None, None, 1, 10, None, None],
            ["Drinks", "Preço negativo", None, 1, -1, None, None],
            ["Drinks", "Preço texto", None, 1, "caro", None, None],
            ["Drinks", "Estoque fracionado", None, 1.5, 10, None, None],
            ["Drinks", "Estoque negativo", None, -2, 10, None, None],
            ["Drinks", "Estoque vazio", None, None, "12,50", None, None],
        ]
        result = import_items(make_workbook(rows))

        self.assertEqual([s.row for s in result.skipped], [2, 3, 4, 5, 6, 7])
        self.assertEqual(result.items_created, 1)
        ok = Item.objects.get(name="Estoque vazio")
        self.assertEqual(ok.stock, 0)
        self.assertEqual(ok.price, Decimal("12.50"))

    def test_columns_are_found_by_header_name(self):
        headers = [" cozinha? ", "PREÇO", "item", "Estoque", "CATEGORIA"]
        import_items(make_workbook([["S", 9, "Guioza", 4, "Entradas"]], headers=headers))

        item = Item.objects.get(name="Guioza")
        self.assertEqual(item.category.name, "Entradas")
        self.assertEqual(item.price, Decimal("9.00"))
        self.assertEqual(item.stock, 4)
        self.assertEqual(item.description, "")
        self.assertTrue(item.requires_kitchen_preparation)

    def test_missing_header_is_rejected_and_nothing_imported(self):
        headers = ["Categoria", "Item", "Descrição", "Estoque", "Cozinha?"]
        upload = make_workbook([["Teishoku", "Karague", "", 1, "S"]], headers=headers)

        with self.assertRaisesMessage(SpreadsheetImportError, "Preço"):
            import_items(upload)
        self.assertFalse(Category.objects.exists())
        self.assertFalse(Item.objects.exists())

    def test_non_xlsx_file_is_rejected(self):
        upload = SimpleUploadedFile("menu.xlsx", b"Categoria;Item\nTeishoku;Karague\n")

        with self.assertRaisesMessage(SpreadsheetImportError, ".xlsx"):
            import_items(upload)
        self.assertFalse(Item.objects.exists())

    def test_observacoes_column_is_ignored(self):
        import_items(make_workbook(SAMPLE_ROWS))

        self.assertFalse(NoteSuggestion.objects.exists())


class ItemImportViewTests(TestCase):
    """The upload page at /estoque/importar/ (#398)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")

    def setUp(self):
        Category.objects.all().delete()
        self.client.force_login(self.user)
        self.url = reverse("inventory:item-import")

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("core:login"), resp["Location"])

        resp = self.client.post(self.url, {"file": make_workbook(SAMPLE_ROWS)})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Item.objects.exists())

    def test_item_list_links_to_import_page(self):
        resp = self.client.get(reverse("inventory:item-list"))
        self.assertContains(resp, "Importar planilha")
        self.assertContains(resp, f'href="{self.url}"')

    def test_get_shows_upload_form(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'type="file"')
        self.assertContains(resp, 'enctype="multipart/form-data"')
        self.assertContains(resp, ".xlsx")

    def test_post_imports_and_shows_summary(self):
        resp = self.client.post(self.url, {"file": make_workbook(SAMPLE_ROWS)})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Item.objects.count(), 5)
        body = resp.content.decode()
        self.assertIn("Importação concluída", body)
        self.assertIn('data-testid="categories-created">5<', body)
        self.assertIn('data-testid="items-created">5<', body)
        self.assertIn('data-testid="items-updated">0<', body)
        self.assertIn("Gin Tônica", body)
        self.assertIn("preço ausente", body)

        resp = self.client.post(self.url, {"file": make_workbook(SAMPLE_ROWS)})
        self.assertContains(resp, 'data-testid="items-updated">5<')
        self.assertEqual(Item.objects.count(), 5)

    def test_missing_header_shows_error(self):
        upload = make_workbook([["Teishoku", "Karague"]], headers=["Categoria", "Item"])
        resp = self.client.post(self.url, {"file": upload})

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "coluna(s) obrigatória(s)")
        self.assertNotContains(resp, "Importação concluída")
        self.assertFalse(Category.objects.exists())

    def test_non_xlsx_upload_shows_error(self):
        upload = SimpleUploadedFile("menu.csv", b"Categoria,Item\nTeishoku,Karague\n")
        resp = self.client.post(self.url, {"file": upload})

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Envie um arquivo no formato .xlsx")
        self.assertFalse(Item.objects.exists())

    def test_item_edit_form_shows_description(self):
        category = Category.objects.create(name="Teishoku")
        item = Item.objects.create(
            name="Karague",
            category=category,
            price=Decimal("50"),
            description="Frango empanado",
        )
        resp = self.client.get(reverse("inventory:item-update", args=[item.pk]))
        self.assertContains(resp, "Descrição")
        self.assertContains(resp, "Frango empanado")

        resp = self.client.post(
            reverse("inventory:item-update", args=[item.pk]),
            {
                "name": "Karague",
                "category": category.pk,
                "description": "Frango frito",
                "price": "50",
                "stock": "1",
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.description, "Frango frito")
