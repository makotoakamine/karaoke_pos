"""URL configuration for the inventory app."""
from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.ItemListView.as_view(), name="item-list"),
    path("novo/", views.ItemCreateView.as_view(), name="item-create"),
    path("<int:pk>/editar/", views.ItemUpdateView.as_view(), name="item-update"),
    path("<int:pk>/excluir/", views.ItemDeleteView.as_view(), name="item-delete"),
]