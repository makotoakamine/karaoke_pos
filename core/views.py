"""Views for the core app.

The config page (:class:`ConfigView`) is the project's first runtime-
configurable settings surface. It is a login-required :class:`ModelForm` bound
to the singleton :class:`core.models.Configuracao` row (``pk=1``), rendered
with the same dark theme every other staff page uses. The row is auto-created
on first access through :func:`core.models.get_config`, so a fresh project
with no config row renders the page fine and defaults to auto-print OFF.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import TemplateView, UpdateView

from .forms import ConfiguracaoForm
from .models import get_config


class LandingLoginView(LoginView):
    """Branded landing page that doubles as the login form.

    Uses Django's stock :class:`LoginView` so authentication, CSRF and the
    "next" redirect handling all come from ``django.contrib.auth``. Only the
    template is custom, and already-authenticated visitors are bounced to the
    logged-in home page instead of seeing the form again.
    """

    template_name = "core/landing.html"
    redirect_authenticated_user = True
    next_page = "core:home"
    extra_context = {"title": "Karaokê POS"}

    @method_decorator(sensitive_post_parameters())
    @method_decorator(csrf_protect)
    @method_decorator(never_cache)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)


class HomeView(TemplateView):
    """Minimal logged-in home page stub.

    Later tasks will grow this into the app's navigation hub. For now it only
    confirms the user is authenticated and offers a logout link.
    """

    template_name = "core/home.html"
    extra_context = {"title": "Início"}

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("core:login")
        return super().dispatch(request, *args, **kwargs)


class ConfigView(LoginRequiredMixin, UpdateView):
    """Login-required config page bound to the singleton configuration row.

    The view is an :class:`UpdateView` over :class:`Configuracao` pinned to
    ``pk=1``. :meth:`get_object` returns the singleton — creating it on first
    access via :func:`get_config` — so a fresh project with no config row
    renders the page fine and defaults to auto-print OFF. Saving persists the
    toggle across reloads and there is only ever one row in the DB because the
    singleton invariant is enforced at the model layer.

    The template uses the same dark Bootstrap theme as the other staff pages
    (#203/#204), with a single switch for the auto-print toggle.
    """

    form_class = ConfiguracaoForm
    template_name = "core/config.html"
    extra_context = {"title": "Configurações"}
    success_url = reverse_lazy("core:config")

    def get_object(self, queryset=None):
        # Always the singleton row — created on first access. There is never a
        # second row because get_or_create pins pk=1.
        return get_config()

    def form_valid(self, form):
        messages.success(self.request, _("Configurações salvas."))
        return super().form_valid(form)