"""Views for the core app."""
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import TemplateView


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