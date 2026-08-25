"""Views for the core app."""
from django.shortcuts import render


def index(request):
    """Página inicial do Karaoke POS."""
    return render(request, "core/index.html", {"title": "Início"})