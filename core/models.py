"""Models for the core app.

The core app owns the project's first runtime-configurable settings, exposed
through a singleton :class:`Configuracao` row. The singleton is enforced by
always reading/writing the row with ``pk=1``: the first access creates it via
:func:`get_config`, and every later access reuses that same row. There is never
more than one configuration row in the database, and a fresh project renders
the config page fine because the row is auto-created on first access.

This first round carries a single boolean — ``auto_print_on_kitchen_arrival``
— which drives whether the waiter's order page automatically sends a kitchen
ticket to the thermal printer the moment an order with at least one
kitchen-preparation line is committed (#237). The setting defaults to ``False``
so a fresh install never surprises anyone with printer traffic.
"""
from django.db import models


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

    class Meta:
        verbose_name = "Configuração"
        verbose_name_plural = "Configuração"

    def __str__(self) -> str:
        return "Configuração do site"


def get_config() -> Configuracao:
    """Return the singleton configuration row, creating it on first access.

    The row is pinned to ``pk=1``: :meth:`get_or_create` guarantees only one
    row ever exists regardless of how many callers race on startup, and every
    later read goes through the same pinned primary key so there is never a
    stale second row to accidentally edit.
    """
    config, _created = Configuracao.objects.get_or_create(pk=1)
    return config