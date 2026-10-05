"""URL configuration for the inventory app."""
from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.ItemListView.as_view(), name="item-list"),
    path("novo/", views.ItemCreateView.as_view(), name="item-create"),
    path("importar/", views.ItemImportView.as_view(), name="item-import"),
    path("categorias/", views.CategoryListView.as_view(), name="category-list"),
    path("categorias/nova/", views.CategoryCreateView.as_view(), name="category-create"),
    path(
        "categorias/<int:pk>/editar/",
        views.CategoryUpdateView.as_view(),
        name="category-update",
    ),
    path(
        "categorias/<int:pk>/excluir/",
        views.CategoryDeleteView.as_view(),
        name="category-delete",
    ),
    path("<int:pk>/editar/", views.ItemUpdateView.as_view(), name="item-update"),
    path("<int:pk>/excluir/", views.ItemDeleteView.as_view(), name="item-delete"),
]
