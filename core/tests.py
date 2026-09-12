"""Functional tests for the core app's config page (#237).

The config page is the project's first runtime-configurable settings surface:
a singleton :class:`Configuracao` row (``pk=1``) edited through a login-required
:class:`ModelForm`, rendered in the dark theme every other staff page uses.
These tests pin the login gate, the singleton enforcement (one row ever, even
across concurrent first-access), the GET/POST flow with the auto-print toggle,
and the navbar link.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Configuracao, get_config


class ConfigViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")

    def setUp(self):
        self.client.force_login(self.user)

    # --- acceptance: login required ----------------------------------------

    def test_anonymous_config_get_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse("core:config"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("next=", resp["Location"])

    def test_anonymous_config_post_redirected_to_login(self):
        self.client.logout()
        resp = self.client.post(
            reverse("core:config"),
            {"auto_print_on_kitchen_arrival": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("next=", resp["Location"])

    # --- acceptance: GET as staff → 200 in the dark theme with the toggle ---

    def test_staff_get_returns_200(self):
        resp = self.client.get(reverse("core:config"))
        self.assertEqual(resp.status_code, 200)

    def test_page_extends_base_html(self):
        resp = self.client.get(reverse("core:config"))
        self.assertTemplateUsed(resp, "base.html")
        self.assertTemplateUsed(resp, "core/config.html")

    def test_page_uses_the_dark_theme(self):
        resp = self.client.get(reverse("core:config"))
        self.assertContains(resp, 'data-bs-theme="dark"')

    def test_page_renders_the_auto_print_checkbox(self):
        resp = self.client.get(reverse("core:config"))
        body = resp.content.decode()
        self.assertIn('name="auto_print_on_kitchen_arrival"', body)
        self.assertIn('id="id_auto_print_on_kitchen_arrival"', body)
        self.assertIn(
            "Imprimir pedido automaticamente ao chegar na cozinha", body
        )

    def test_page_renders_bootstrap_classes(self):
        resp = self.client.get(reverse("core:config"))
        body = resp.content.decode()
        self.assertIn("card", body)
        self.assertIn("btn-primary", body)
        self.assertIn("container", body)
        self.assertIn("form-check", body)

    # --- acceptance: singleton enforcement ----------------------------------

    def test_fresh_project_auto_creates_the_singleton_row_on_first_get(self):
        self.assertFalse(Configuracao.objects.exists())
        resp = self.client.get(reverse("core:config"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Configuracao.objects.count(), 1)
        config = Configuracao.objects.get()
        self.assertEqual(config.pk, 1)
        self.assertFalse(config.auto_print_on_kitchen_arrival)

    def test_only_one_config_row_ever_exists(self):
        # First access creates the row.
        self.client.get(reverse("core:config"))
        # Second access reuses it, never creates a second.
        self.client.get(reverse("core:config"))
        self.assertEqual(Configuracao.objects.count(), 1)

    def test_get_config_returns_the_singleton(self):
        config = get_config()
        self.assertEqual(config.pk, 1)
        # A second call returns the same row.
        self.assertEqual(get_config().pk, 1)
        self.assertEqual(Configuracao.objects.count(), 1)

    def test_defaults_to_auto_print_off(self):
        config = get_config()
        self.assertFalse(config.auto_print_on_kitchen_arrival)

    # --- acceptance: saving persists across reloads -------------------------

    def test_saving_with_toggle_on_persists(self):
        resp = self.client.post(
            reverse("core:config"),
            {"auto_print_on_kitchen_arrival": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        config = Configuracao.objects.get()
        self.assertTrue(config.auto_print_on_kitchen_arrival)

    def test_saving_with_toggle_off_persists(self):
        # First turn it on.
        Configuracao.objects.create(pk=1, auto_print_on_kitchen_arrival=True)
        # Then POST without the checkbox (off).
        resp = self.client.post(reverse("core:config"), {})
        self.assertEqual(resp.status_code, 302)
        config = Configuracao.objects.get()
        self.assertFalse(config.auto_print_on_kitchen_arrival)

    def test_a_second_visit_pre_fills_the_saved_value(self):
        Configuracao.objects.create(pk=1, auto_print_on_kitchen_arrival=True)
        resp = self.client.get(reverse("core:config"))
        body = resp.content.decode()
        # The checkbox is checked when the saved value is True.
        self.assertIn("checked", body)

    def test_a_second_visit_pre_fills_off_when_off(self):
        Configuracao.objects.create(pk=1, auto_print_on_kitchen_arrival=False)
        resp = self.client.get(reverse("core:config"))
        # The form field is not checked when the value is False. Extract the
        # checkbox markup to avoid matching the word "checked" elsewhere.
        body = resp.content.decode()
        checkbox = body.split(
            'id="id_auto_print_on_kitchen_arrival"', 1
        )[1].split(">", 1)[0]
        self.assertNotIn("checked", checkbox)

    # --- acceptance: navbar link between Estoque and Sair -------------------

    def test_navbar_shows_configuracoes_link_on_every_authenticated_page(self):
        for url in (
            reverse("core:home"),
            reverse("orders:order-create"),
            reverse("orders:kitchen"),
            reverse("inventory:item-list"),
        ):
            body = self.client.get(url).content.decode()
            self.assertIn(reverse("core:config"), body)
            self.assertIn("Configurações", body)

    def test_navbar_config_link_sits_between_estoque_and_sair(self):
        body = self.client.get(reverse("core:home")).content.decode()
        estoque_pos = body.index("Estoque")
        config_pos = body.index("Configurações")
        sair_pos = body.index("Sair")
        self.assertLess(estoque_pos, config_pos)
        self.assertLess(config_pos, sair_pos)

    # --- acceptance: success message ---------------------------------------

    def test_successful_save_shows_a_success_message(self):
        resp = self.client.post(
            reverse("core:config"),
            {"auto_print_on_kitchen_arrival": "on"},
            follow=True,
        )
        self.assertContains(resp, "Configurações salvas")

    # --- acceptance: the config page styling lives in the project's SCSS ----

    def test_the_config_classes_are_defined_in_the_projects_scss(self):
        from django.conf import settings

        scss = (settings.BASE_DIR / "static" / "scss" / "main.scss").read_text(
            encoding="utf-8"
        )
        self.assertIn(".karaoke-config", scss)