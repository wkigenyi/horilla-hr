from django.urls import path

from horilla_api.api_views.audit import views

urlpatterns = [
    path("entries/", views.AuditEntryListView.as_view(), name="api-audit-entries"),
    path("filters/", views.AuditFiltersView.as_view(), name="api-audit-filters"),
]
