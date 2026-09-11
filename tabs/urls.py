"""URL configuration for the tabs app."""
from django.urls import path

from . import views

app_name = "tabs"

urlpatterns = [
    path("", views.TabListView.as_view(), name="tab-list"),
    path("nova/", views.TabCreateView.as_view(), name="tab-create"),
    path("<int:pk>/editar/", views.TabUpdateView.as_view(), name="tab-update"),
]
