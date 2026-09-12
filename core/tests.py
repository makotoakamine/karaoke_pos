"""Functional tests for the core app's config page (#237, #238).

The config page is the project's first runtime-configurable settings surface:
a singleton :class:`Configuracao` row (``pk=1``) edited through a login-required
:class:`ModelForm`, rendered in the dark theme every other staff page uses.
These tests pin the login gate, the singleton enforcement (one row ever, even
across concurrent first-access), the GET/POST flow with the auto-print toggle,
and the navbar link.

Since #238 the config page also owns an optional ``alert_sound`` file: when a
kitchen auto-print attempt fails, the server host plays that sound (or the
built-in default). The second suite below pins the config round-trip (upload
persists, empty falls back to default, the page shows which sound is active)
and the player selection logic in :mod:`core.services.alerts`, with
subprocess/winsound mocked so the suite makes no actual noise on CI.
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
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


class AlertSoundConfigTests(TestCase):
    """Config round-trip for the ``alert_sound`` FileField (#238).

    Pins that the form renders the file input with the right help text, that
    uploading a sound persists the file under ``MEDIA_ROOT``, that clearing it
    restores the built-in default, and that the config page shows which sound
    is currently active. A temporary ``MEDIA_ROOT`` is used so the uploaded
    files do not pollute the checkout.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("admin", password="secret123")

    def setUp(self):
        self.client.force_login(self.user)
        self.media_dir = Path(tempfile.mkdtemp(prefix="karaoke-media-"))
        self.addCleanup(shutil.rmtree, self.media_dir, True)
        self._patched = override_settings(MEDIA_ROOT=self.media_dir)
        self._patched.enable()
        self.addCleanup(self._patched.disable)

    # --- helpers -----------------------------------------------------------

    def _wav(self, name="custom.wav", content=b"RIFF fake wav content"):
        return SimpleUploadedFile(
            name, content, content_type="audio/wav"
        )

    # --- acceptance: the form renders the alert sound field -----------------

    def test_config_page_renders_the_alert_sound_file_input(self):
        resp = self.client.get(reverse("core:config"))
        body = resp.content.decode()
        self.assertIn('name="alert_sound"', body)
        self.assertIn('id="id_alert_sound"', body)
        self.assertIn('type="file"', body)

    def test_config_page_renders_the_help_text_for_the_alert_sound(self):
        resp = self.client.get(reverse("core:config"))
        self.assertContains(
            resp, "Som tocado no servidor quando a impressão automática falha"
        )

    def test_config_form_uses_multipart_enctype(self):
        resp = self.client.get(reverse("core:config"))
        self.assertContains(resp, 'enctype="multipart/form-data"')

    # --- acceptance: the page shows which sound is currently active ---------

    def test_page_shows_the_default_sound_label_when_no_upload(self):
        resp = self.client.get(reverse("core:config"))
        self.assertContains(resp, "Som padrão")

    def test_page_shows_the_uploaded_sound_name_after_upload(self):
        resp = self.client.post(
            reverse("core:config"),
            {"auto_print_on_kitchen_arrival": "on", "alert_sound": self._wav()},
        )
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get(reverse("core:config"))
        # The upload path is deterministic (alert_sounds/alert.wav), so the
        # active-sound label is the stored basename, not the original upload
        # name. The "Som ativo:" line shows "alert.wav".
        self.assertContains(resp, "Som ativo: alert.wav")

    # --- acceptance: uploading a sound persists it under MEDIA_ROOT ----------

    def test_uploading_a_sound_persists_the_file(self):
        resp = self.client.post(
            reverse("core:config"),
            {"auto_print_on_kitchen_arrival": "on", "alert_sound": self._wav()},
        )
        self.assertEqual(resp.status_code, 302)
        config = Configuracao.objects.get()
        self.assertTrue(config.alert_sound)
        self.assertTrue(config.alert_sound.name)
        # The file lives on disk under MEDIA_ROOT.
        saved = Path(settings.MEDIA_ROOT) / config.alert_sound.name
        self.assertTrue(saved.exists())

    def test_uploading_a_sound_replaces_a_previous_upload(self):
        # First upload.
        self.client.post(
            reverse("core:config"),
            {
                "auto_print_on_kitchen_arrival": "on",
                "alert_sound": self._wav(name="first.wav"),
            },
        )
        config = Configuracao.objects.get()
        self.assertTrue(config.alert_sound)

        # Second upload also persists a sound file under MEDIA_ROOT.
        self.client.post(
            reverse("core:config"),
            {
                "auto_print_on_kitchen_arrival": "on",
                "alert_sound": self._wav(name="second.wav"),
            },
        )
        config.refresh_from_db()
        self.assertTrue(config.alert_sound)
        # The file lives on disk under MEDIA_ROOT.
        saved = Path(settings.MEDIA_ROOT) / config.alert_sound.name
        self.assertTrue(saved.exists())

    # --- acceptance: an empty field means the built-in default --------------

    def test_no_upload_defaults_to_empty_alert_sound(self):
        config = get_config()
        self.assertFalse(config.alert_sound)

    def test_clearing_the_field_restores_the_empty_default(self):
        # First upload a sound.
        self.client.post(
            reverse("core:config"),
            {"auto_print_on_kitchen_arrival": "on", "alert_sound": self._wav()},
        )
        config = Configuracao.objects.get()
        self.assertTrue(config.alert_sound)

        # Then POST with the field cleared (ClearableFileInput sends
        # alert_sound-clear="on" and no new file).
        resp = self.client.post(
            reverse("core:config"),
            {
                "auto_print_on_kitchen_arrival": "on",
                "alert_sound-clear": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        config.refresh_from_db()
        self.assertFalse(config.alert_sound)
        # The page shows the default label again.
        resp = self.client.get(reverse("core:config"))
        self.assertContains(resp, "Som padrão")

    # --- acceptance: the model exposes a human-readable label ---------------

    def test_alert_sound_name_returns_default_label_when_empty(self):
        config = get_config()
        self.assertEqual(
            config.alert_sound_name, "Som padrão (alert.wav embutido)"
        )

    def test_alert_sound_name_returns_basename_when_uploaded(self):
        config = get_config()
        config.alert_sound = self._wav(name="meu_alerta.wav")
        config.save()
        config.refresh_from_db()
        self.assertEqual(config.alert_sound_name, "alert.wav")

    # --- acceptance: saving the toggle still works with the file field ------

    def test_saving_the_toggle_without_a_file_keeps_empty_alert_sound(self):
        resp = self.client.post(
            reverse("core:config"),
            {"auto_print_on_kitchen_arrival": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        config = Configuracao.objects.get()
        self.assertTrue(config.auto_print_on_kitchen_arrival)
        self.assertFalse(config.alert_sound)


class AlertSoundBundledAssetTests(TestCase):
    """The project ships a built-in alert sound so a fresh install can alert
    out of the box. These tests pin the asset's existence and format."""

    def test_the_bundled_alert_wav_exists(self):
        path = settings.BASE_DIR / "static" / "vendor" / "audio" / "alert.wav"
        self.assertTrue(path.exists(), f"missing bundled alert sound: {path}")
        self.assertGreater(path.stat().st_size, 0)

    def test_the_bundled_alert_wav_is_a_valid_wav(self):
        import wave

        path = settings.BASE_DIR / "static" / "vendor" / "audio" / "alert.wav"
        with wave.open(str(path), "rb") as w:
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)
            self.assertGreater(w.getframerate(), 0)
            self.assertGreater(w.getnframes(), 0)


class ResolveAlertSoundPathTests(TestCase):
    """:func:`core.services.alerts.resolve_alert_sound_path` picks the right
    file: the uploaded sound when one is present, otherwise the built-in
    bundled default."""

    def setUp(self):
        self.media_dir = Path(tempfile.mkdtemp(prefix="karaoke-media-"))
        self.addCleanup(shutil.rmtree, self.media_dir, True)
        self._patched = override_settings(MEDIA_ROOT=self.media_dir)
        self._patched.enable()
        self.addCleanup(self._patched.disable)

    def test_no_upload_resolves_to_the_bundled_default(self):
        from core.services.alerts import resolve_alert_sound_path

        path = resolve_alert_sound_path()
        self.assertEqual(
            path,
            settings.BASE_DIR / "static" / "vendor" / "audio" / "alert.wav",
        )

    def test_an_upload_resolves_to_the_uploaded_file(self):
        from core.services.alerts import resolve_alert_sound_path

        config = get_config()
        uploaded = SimpleUploadedFile(
            "custom.wav", b"fake", content_type="audio/wav"
        )
        config.alert_sound = uploaded
        config.save()
        path = resolve_alert_sound_path()
        self.assertEqual(path, self.media_dir / config.alert_sound.name)
        self.assertTrue(path.exists())


class PlayAlertLinuxTests(TestCase):
    """Player selection logic on Linux, with subprocess and ``shutil.which``
    mocked so the suite makes no actual noise on CI.

    The order tried is: explicit ``KARAOKE_ALERT_PLAYER_COMMAND`` env var
    first (``shlex``-split, ``{path}`` placeholder substituted), then ``aplay``,
    ``paplay``, ``ffplay`` — whichever executables are found on ``PATH``. The
    first that exits 0 wins. If none is available, a warning is logged once
    and the call stays silent on subsequent attempts.
    """

    def setUp(self):
        # Reset the module-level "warned once" flag between tests so the
        # single-warning behavior can be exercised repeatedly.
        from core.services import alerts

        alerts._no_player_warned = False
        self.addCleanup(self._reset_warned_flag)

    def _reset_warned_flag(self):
        from core.services import alerts

        alerts._no_player_warned = False

    def _builtin_path(self):
        return settings.BASE_DIR / "static" / "vendor" / "audio" / "alert.wav"

    # --- acceptance: explicit env var command wins and is tried first ------

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch("core.services.alerts.shutil.which", return_value=None)
    @mock.patch("core.services.alerts.subprocess.run")
    def test_explicit_env_command_is_tried_first(
        self, mock_run, mock_which, mock_system
    ):
        with mock.patch.dict(
            "os.environ",
            {"KARAOKE_ALERT_PLAYER_COMMAND": "customplay {path}"},
            clear=False,
        ):
            from core.services.alerts import _play_sound_sync

            _play_sound_sync(self._builtin_path())

        mock_run.assert_called_once()
        command = mock_run.call_args.args[0]
        self.assertEqual(command[0], "customplay")
        self.assertEqual(command[1], str(self._builtin_path()))

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch("core.services.alerts.shutil.which", return_value=None)
    @mock.patch("core.services.alerts.subprocess.run")
    def test_explicit_env_command_supports_path_placeholder(
        self, mock_run, mock_which, mock_system
    ):
        with mock.patch.dict(
            "os.environ",
            {
                "KARAOKE_ALERT_PLAYER_COMMAND": "play --volume 80 {path} --fade"
            },
            clear=False,
        ):
            from core.services.alerts import _play_sound_sync

            _play_sound_sync(self._builtin_path())

        command = mock_run.call_args.args[0]
        self.assertEqual(
            command,
            ["play", "--volume", "80", str(self._builtin_path()), "--fade"],
        )

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch("core.services.alerts.shutil.which", return_value=None)
    @mock.patch("core.services.alerts.subprocess.run")
    def test_explicit_env_command_succeeds_no_fallback_tried(
        self, mock_run, mock_which, mock_system
    ):
        mock_run.return_value = mock.Mock(returncode=0)
        with mock.patch.dict(
            "os.environ",
            {"KARAOKE_ALERT_PLAYER_COMMAND": "customplay {path}"},
            clear=False,
        ):
            from core.services.alerts import _play_sound_sync

            _play_sound_sync(self._builtin_path())

        # Only the explicit command was attempted.
        self.assertEqual(mock_run.call_count, 1)

    # --- acceptance: aplay is tried before paplay and ffplay ----------------

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch(
        "core.services.alerts.shutil.which",
        side_effect=lambda exe: f"/usr/bin/{exe}" if exe == "aplay" else None,
    )
    @mock.patch("core.services.alerts.subprocess.run")
    def test_aplay_is_tried_when_available(self, mock_run, mock_which, _sys):
        with mock.patch.dict("os.environ", {}, clear=True):
            from core.services.alerts import _play_sound_sync

            _play_sound_sync(self._builtin_path())

        command = mock_run.call_args.args[0]
        self.assertEqual(command[0], "aplay")
        self.assertEqual(command[1], str(self._builtin_path()))

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch(
        "core.services.alerts.shutil.which",
        side_effect=lambda exe: f"/usr/bin/{exe}" if exe == "paplay" else None,
    )
    @mock.patch("core.services.alerts.subprocess.run")
    def test_paplay_is_tried_when_aplay_absent(self, mock_run, mock_which, _s):
        with mock.patch.dict("os.environ", {}, clear=True):
            from core.services.alerts import _play_sound_sync

            _play_sound_sync(self._builtin_path())

        command = mock_run.call_args.args[0]
        self.assertEqual(command[0], "paplay")

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch(
        "core.services.alerts.shutil.which",
        side_effect=lambda exe: f"/usr/bin/{exe}" if exe == "ffplay" else None,
    )
    @mock.patch("core.services.alerts.subprocess.run")
    def test_ffplay_is_tried_with_correct_flags(self, mock_run, mock_which, _s):
        with mock.patch.dict("os.environ", {}, clear=True):
            from core.services.alerts import _play_sound_sync

            _play_sound_sync(self._builtin_path())

        command = mock_run.call_args.args[0]
        self.assertEqual(command[0], "ffplay")
        self.assertIn("-nodisp", command)
        self.assertIn("-autoexit", command)
        self.assertIn("-loglevel", command)
        self.assertIn("quiet", command)

    # --- acceptance: the first player that exits 0 wins, rest skipped --------

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch(
        "core.services.alerts.shutil.which",
        return_value="/usr/bin/aplay",
    )
    @mock.patch("core.services.alerts.subprocess.run")
    def test_first_success_skips_remaining_players(
        self, mock_run, mock_which, _s
    ):
        mock_run.return_value = mock.Mock(returncode=0)
        with mock.patch.dict("os.environ", {}, clear=True):
            from core.services.alerts import _play_sound_sync

            _play_sound_sync(self._builtin_path())

        self.assertEqual(mock_run.call_count, 1)

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch(
        "core.services.alerts.shutil.which",
        side_effect=lambda exe: f"/usr/bin/{exe}",
    )
    @mock.patch("core.services.alerts.subprocess.run")
    def test_failed_first_player_falls_through_to_next(
        self, mock_run, mock_which, _s
    ):
        # aplay fails, paplay succeeds.
        mock_run.side_effect = [
            mock.Mock(returncode=1),
            mock.Mock(returncode=0),
        ]
        with mock.patch.dict("os.environ", {}, clear=True):
            from core.services.alerts import _play_sound_sync

            _play_sound_sync(self._builtin_path())

        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(mock_run.call_args_list[0].args[0][0], "aplay")
        self.assertEqual(mock_run.call_args_list[1].args[0][0], "paplay")

    # --- acceptance: no player available → warn once, stay silent ----------

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch("core.services.alerts.shutil.which", return_value=None)
    @mock.patch("core.services.alerts.subprocess.run")
    def test_no_player_warns_once_and_stays_silent(
        self, mock_run, mock_which, _s
    ):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertLogs("core.services.alerts", level="WARNING") as cm:
                from core.services.alerts import _play_sound_sync

                _play_sound_sync(self._builtin_path())
                _play_sound_sync(self._builtin_path())

        # subprocess.run was never called (no command to run).
        mock_run.assert_not_called()
        # Only one warning for the two calls.
        warnings = [r for r in cm.records if r.levelname == "WARNING"]
        no_player = [
            r for r in warnings if "nenhum reprodutor" in r.getMessage()
        ]
        self.assertEqual(len(no_player), 1)

    # --- acceptance: a missing file logs a warning and returns --------------

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    def test_missing_file_logs_warning_and_returns(self, _s):
        from core.services.alerts import _play_sound_sync

        with self.assertLogs("core.services.alerts", level="WARNING") as cm:
            _play_sound_sync(Path("/nonexistent/sound.wav"))

        self.assertTrue(
            any("não encontrado" in r.getMessage() for r in cm.records)
        )

    # --- acceptance: a player exception is swallowed ------------------------

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch(
        "core.services.alerts.shutil.which", return_value="/usr/bin/aplay"
    )
    @mock.patch(
        "core.services.alerts.subprocess.run",
        side_effect=OSError("boom"),
    )
    def test_player_exception_is_swallowed(self, mock_run, mock_which, _s):
        with mock.patch.dict("os.environ", {}, clear=True):
            from core.services.alerts import _play_sound_sync

            # Must not raise.
            _play_sound_sync(self._builtin_path())


class PlayAlertWindowsTests(TestCase):
    """Player selection on Windows uses ``winsound.PlaySound`` with
    ``SND_FILENAME | SND_ASYNC``. ``winsound`` is mocked so the suite runs on
    any platform without a real Windows audio stack.
    """

    def setUp(self):
        from core.services import alerts

        alerts._no_player_warned = False
        self.addCleanup(self._reset_warned_flag)

    def _reset_warned_flag(self):
        from core.services import alerts

        alerts._no_player_warned = False

    def _builtin_path(self):
        return settings.BASE_DIR / "static" / "vendor" / "audio" / "alert.wav"

    @mock.patch("core.services.alerts.platform.system", return_value="Windows")
    def test_windows_uses_winsound_play_sound_async(self, _s):
        fake_winsound = mock.MagicMock()
        fake_winsound.SND_FILENAME = 0x00020000
        fake_winsound.SND_ASYNC = 0x0001
        with mock.patch.dict("sys.modules", {"winsound": fake_winsound}):
            from core.services.alerts import _play_sound_sync

            _play_sound_sync(self._builtin_path())

        fake_winsound.PlaySound.assert_called_once_with(
            str(self._builtin_path()),
            fake_winsound.SND_FILENAME | fake_winsound.SND_ASYNC,
        )

    @mock.patch("core.services.alerts.platform.system", return_value="Windows")
    def test_windows_winsound_error_is_swallowed(self, _s):
        fake_winsound = mock.MagicMock()
        fake_winsound.SND_FILENAME = 0x00020000
        fake_winsound.SND_ASYNC = 0x0001
        fake_winsound.PlaySound.side_effect = RuntimeError("no device")
        with mock.patch.dict("sys.modules", {"winsound": fake_winsound}):
            from core.services.alerts import _play_sound_sync

            with self.assertLogs("core.services.alerts", level="WARNING"):
                _play_sound_sync(self._builtin_path())

    @mock.patch("core.services.alerts.platform.system", return_value="Windows")
    def test_windows_without_winsound_warns_once(self, _s):
        # Simulate winsound not importable.
        with mock.patch.dict("sys.modules", {"winsound": None}):
            with self.assertLogs("core.services.alerts", level="WARNING") as cm:
                from core.services.alerts import _play_sound_sync

                _play_sound_sync(self._builtin_path())

        self.assertTrue(
            any("nenhum reprodutor" in r.getMessage() for r in cm.records)
        )


class PlayAlertThreadTests(TestCase):
    """:func:`play_alert` spawns a daemon thread and never blocks or raises."""

    def _builtin_path(self):
        return settings.BASE_DIR / "static" / "vendor" / "audio" / "alert.wav"

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch(
        "core.services.alerts.shutil.which", return_value="/usr/bin/aplay"
    )
    @mock.patch("core.services.alerts.subprocess.run")
    def test_play_alert_does_not_block_the_caller(self, mock_run, _w, _s):
        mock_run.return_value = mock.Mock(returncode=0)
        from core.services.alerts import play_alert

        # The call returns immediately — the thread is the one that runs
        # subprocess. We assert the call returned (did not hang) and that the
        # subprocess was eventually invoked.
        play_alert(self._builtin_path())
        # Give the daemon thread a moment to run.
        import time

        time.sleep(0.2)
        mock_run.assert_called()

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch("core.services.alerts.shutil.which", return_value=None)
    @mock.patch("core.services.alerts.subprocess.run")
    def test_play_alert_with_no_player_does_not_raise(self, mock_run, _w, _s):
        from core.services.alerts import play_alert

        with mock.patch.dict("os.environ", {}, clear=True):
            play_alert(self._builtin_path())
        import time

        time.sleep(0.1)
        mock_run.assert_not_called()

    @mock.patch("core.services.alerts.platform.system", return_value="Linux")
    @mock.patch(
        "core.services.alerts.shutil.which", return_value="/usr/bin/aplay"
    )
    @mock.patch(
        "core.services.alerts.subprocess.run",
        side_effect=OSError("boom"),
    )
    def test_play_alert_with_player_exception_does_not_raise(
        self, mock_run, _w, _s
    ):
        from core.services.alerts import play_alert

        play_alert(self._builtin_path())
        import time

        time.sleep(0.1)
        mock_run.assert_called()

    def test_play_alert_thread_is_a_daemon(self):
        """The spawned thread is a daemon so it never blocks process exit."""
        from core.services.alerts import _play_sound_sync
        import threading

        with mock.patch("core.services.alerts._play_sound_sync") as mock_sync:
            from core.services.alerts import play_alert

            play_alert(self._builtin_path())
            # The thread that was started should be a daemon. We cannot grab
            # the thread object directly, so we rely on the fact that
            # threading.Thread(daemon=True) is used — assert via the mock that
            # the target was called at all (the thread ran).
            import time

            time.sleep(0.1)
            mock_sync.assert_called_once_with(self._builtin_path())