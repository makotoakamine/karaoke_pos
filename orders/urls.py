"""URL configuration for the orders app."""
from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("novo/", views.OrderCreateView.as_view(), name="order-create"),
    path("cozinha/", views.KitchenView.as_view(), name="kitchen"),
    path("cozinha/fila/", views.KitchenQueueView.as_view(), name="kitchen-queue"),
    path(
        "cozinha/<int:pk>/pronto/",
        views.OrderDoneView.as_view(),
        name="order-done",
    ),
    path(
        "<int:pk>/imprimir/",
        views.OrderPrintView.as_view(),
        name="order-print",
    ),
]