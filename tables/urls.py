"""URL configuration for the tables app."""
from django.urls import path

from . import views

app_name = "tables"

urlpatterns = [
    path("", views.TableListView.as_view(), name="table-list"),
    path("nova/", views.TableCreateView.as_view(), name="table-create"),
    path("<int:pk>/editar/", views.TableUpdateView.as_view(), name="table-update"),
]