from django.urls import path

from ohs import views

urlpatterns = [
    path("", views.ohs_index, name="ohs-index"),
    path("hx/", views.ohs_index_hx, name="ohs-index-hx"),
]
