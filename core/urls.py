"""URL configuration for the core app."""
from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.LandingLoginView.as_view(), name="login"),
    path("home/", views.HomeView.as_view(), name="home"),
    path("configuracao/", views.ConfigView.as_view(), name="config"),
    path("logout/", LogoutView.as_view(), name="logout"),
]