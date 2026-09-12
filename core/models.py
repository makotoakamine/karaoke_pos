"""Models for the core app.

The core app owns the project's first runtime-configurable settings, exposed
through a singleton :class:`Configuracao` row. The singleton is enforced by
always reading/writing the row with ``pk=1``: the first access creates it via
:func:`get_config`, and every later access reuses that same row. There is never
more than one configuration row in the database, and a fresh project renders
the config page fine because the row is auto-created on first access.

The first runtime-configurable setting is ``auto_print_on_kitchen_arrival``
(#237), which drives whether the waiter's order page automatically sends a
kitchen ticket to the thermal printer the moment an order with at least one
kitchen-preparation line is committed. The setting defaults to ``False`` so a
fresh install never surprises anyone with printer traffic.

Since #238 the singleton also carries an optional ``alert_sound`` file: when a
kitchen auto-print attempt fails because no printer answers, the POS server
host plays that sound (or the built-in bundled default when none is uploaded)
through :func:`core.services.alerts.play_alert`. The field is a
:class:`~django.db.models.FileField`, blank/optional, stored under
``MEDIA_ROOT``; an empty field means the built-in sound is used.
"""
from django.conf import settings
from django.db import models


def _alert_sound_upload_to(instance, filename: str) -> str:
    """Storage path (relative to ``MEDIA_ROOT``) for an uploaded alert sound.

    The singleton row only ever keeps one alert sound at a time, so the upload
    path is fixed and deterministic — a new upload replaces the previous file
    rather than accumulating copies.
    """
    return "alert_sounds/alert.wav"


class Configuracao(models.Model):
    """Singleton site-configuration row.

    Exactly one row is meant to exist, with ``pk=1``. :func:`get_config` is the
    single access point: it returns the existing row or creates it on first
    call, so callers never have to think about the singleton invariant. Adding
    new settings later means adding fields here and a migration — the access
    pattern stays the same.
    """

    auto_print_on_kitchen_arrival = models.BooleanField(
        "Imprimir pedido automaticamente ao chegar na cozinha",
        default=False,
        help_text=(
            "Quando ativado, todo pedido com ao menos uma linha de preparo de "
            "cozinha é enviado automaticamente para a impressora térmica assim "
            "que é registrado. Pedidos apenas de balcão (sem linha de preparo) "
            "nunca disparam a impressão automática."
        ),
    )
    alert_sound = models.FileField(
        "som do alerta de falha de impressão",
        upload_to=_alert_sound_upload_to,
        blank=True,
        null=True,
        help_text=(
            "Som tocado no servidor quando a impressão automática falha. Em "
            "branco usa o som padrão embutido no projeto."
        ),
    )

    class Meta:
        verbose_name = "Configuração"
        verbose_name_plural = "Configuração"

    def __str__(self) -> str:
        return "Configuração do site"

    @property
    def alert_sound_name(self) -> str:
        """A human-readable label for the currently configured alert sound.

        Used by the config page to show which sound is active. Returns the
        uploaded file's basename when one is present, otherwise a fixed label
        for the built-in default sound.
        """
        if self.alert_sound:
            import os

            return os.path.basename(self.alert_sound.name)
        return "Som padrão (alert.wav embutido)"


def get_config() -> Configuracao:
    """Return the singleton configuration row, creating it on first access.

    The row is pinned to ``pk=1``: :meth:`get_or_create` guarantees only one
    row ever exists regardless of how many callers race on startup, and every
    later read goes through the same pinned primary key so there is never a
    stale second row to accidentally edit.
    """
    config, _created = Configuracao.objects.get_or_create(pk=1)
    return config