from django.urls import path

from horilla_api.api_views.setup.views import (
    SetupStatusAPIView,
    SetupUserAPIView,
    SetupVerifyAPIView,
)

urlpatterns = [
    path("status/", SetupStatusAPIView.as_view(), name="api-setup-status"),
    path("verify/", SetupVerifyAPIView.as_view(), name="api-setup-verify"),
    path("user/", SetupUserAPIView.as_view(), name="api-setup-user"),
]
