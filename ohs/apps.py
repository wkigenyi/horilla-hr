from django.apps import AppConfig
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class OhsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ohs"
    verbose_name = _("Occupational Health and Safety")

    def ready(self):
        from django.urls import include, path

        from horilla.urls import urlpatterns

        settings.APPS.append("ohs")
        urlpatterns.append(
            path("ohs/", include("ohs.urls")),
        )
        super().ready()
