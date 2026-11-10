from django.urls import path

from ...api_views.dashboard.views import DashboardAPIView, DashboardWidgetAPIView

urlpatterns = [
    path("", DashboardAPIView.as_view(), name="api-dashboard"),
    path(
        "<slug:widget>/",
        DashboardWidgetAPIView.as_view(),
        name="api-dashboard-widget",
    ),
]
