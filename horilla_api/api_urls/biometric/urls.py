from django.urls import path

from horilla_api.api_views.biometric import views

urlpatterns = [
    path("devices/", views.DeviceListCreateAPIView.as_view()),
    path("devices/<uuid:pk>/", views.DeviceDetailAPIView.as_view()),
    path("devices/<uuid:pk>/test/", views.DeviceTestAPIView.as_view()),
    path("devices/<uuid:pk>/fetch/", views.DeviceFetchAPIView.as_view()),
    path("devices/<uuid:pk>/mappings/", views.DeviceMappingsAPIView.as_view()),
    path(
        "devices/<uuid:pk>/mappings/<uuid:mapping_id>/",
        views.DeviceMappingDetailAPIView.as_view(),
    ),
    path("devices/<uuid:pk>/users/", views.DeviceUsersAPIView.as_view()),
    path("devices/<uuid:pk>/users/<int:uid>/", views.DeviceUserDetailAPIView.as_view()),
    path("devices/<uuid:pk>/enrol/", views.DeviceEnrolAPIView.as_view()),
    path("devices/<uuid:pk>/match-badges/", views.DeviceMatchBadgesAPIView.as_view()),
]
