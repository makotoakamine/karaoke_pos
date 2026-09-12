"""Forms for the core app.

The configuration form is a :class:`ModelForm` bound to the singleton
:class:`core.models.Configuracao` row. It only exposes the fields the config
page edits — today just ``auto_print_on_kitchen_arrival`` — so adding a new
setting means adding the field to the model, a migration, and one line here.
"""
from django import forms

from .models import Configuracao


class ConfiguracaoForm(forms.ModelForm):
    """Edits the singleton site-configuration row.

    Only the fields the config page owns are listed in ``Meta.fields`` so a
    future internal-only column on :class:`Configuracao` cannot be written
    through this form by accident.
    """

    class Meta:
        model = Configuracao
        fields = ["auto_print_on_kitchen_arrival"]