from django.urls import path

from ...api_views.dashboard.views import (
    DashboardAPIView,
    DashboardPrefsAPIView,
    DashboardSetupChecklistAPIView,
    DashboardSetupChecklistDismissAPIView,
    DashboardWidgetAPIView,
)

urlpatterns = [
    path("", DashboardAPIView.as_view(), name="api-dashboard"),
    path("prefs/", DashboardPrefsAPIView.as_view(), name="api-dashboard-prefs"),
    path(
        "setup-checklist/dismiss/",
        DashboardSetupChecklistDismissAPIView.as_view(),
        name="api-dashboard-setup-checklist-dismiss",
    ),
    path(
        "setup-checklist/",
        DashboardSetupChecklistAPIView.as_view(),
        name="api-dashboard-setup-checklist",
    ),
    path(
        "<slug:widget>/",
        DashboardWidgetAPIView.as_view(),
        name="api-dashboard-widget",
    ),
]
