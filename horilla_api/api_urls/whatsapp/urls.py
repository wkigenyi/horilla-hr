from django.urls import path

from ...api_views.whatsapp.credentials import (
    WhatsappCredentialDetailAPIView,
    WhatsappCredentialListCreateAPIView,
    WhatsappTestMessageAPIView,
)

urlpatterns = [
    path(
        "credentials/",
        WhatsappCredentialListCreateAPIView.as_view(),
        name="api-whatsapp-credentials",
    ),
    path(
        "credentials/<int:pk>/",
        WhatsappCredentialDetailAPIView.as_view(),
        name="api-whatsapp-credential-detail",
    ),
    path(
        "credentials/<int:pk>/test-message/",
        WhatsappTestMessageAPIView.as_view(),
        name="api-whatsapp-test-message",
    ),
]
