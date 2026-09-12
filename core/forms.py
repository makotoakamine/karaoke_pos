"""Forms for the core app.

The configuration form is a :class:`ModelForm` bound to the singleton
:class:`core.models.Configuracao` row. It only exposes the fields the config
page edits — ``auto_print_on_kitchen_arrival`` (#237) and ``alert_sound``
(#238) — so adding a new setting means adding the field to the model, a
migration, and one line here.
"""
from django import forms

from .models import Configuracao


class ConfiguracaoForm(forms.ModelForm):
    """Edits the singleton site-configuration row.

    Only the fields the config page owns are listed in ``Meta.fields`` so a
    future internal-only column on :class:`Configuracao` cannot be written
    through this form by accident. The ``alert_sound`` field is a
    :class:`~django.forms.FileField`/``ClearableFileInput`` — clearing it
    restores the built-in default sound.
    """

    class Meta:
        model = Configuracao
        fields = ["auto_print_on_kitchen_arrival", "alert_sound"]