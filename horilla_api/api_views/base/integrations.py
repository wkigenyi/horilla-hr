"""
Enable/disable optional integrations for React settings.

Mirrors base.views.EnableIntegrationsView + IntegrationApps. Credential
CRUD for each app stays in that app's API (WhatsApp, LinkedIn, …).
"""

from django.apps import apps
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from base.models import Company, IntegrationApps

# Apps that use IntegrationApps.is_enabled as their on/off switch.
CATALOG = (
    {
        "app_label": "whatsapp",
        "name": "WhatsApp",
        "manage_perms": (
            "whatsapp.view_whatsappcredientials",
            "whatsapp.add_whatsappcredientials",
            "whatsapp.change_whatsappcredientials",
        ),
    },
    {
        "app_label": "horilla_meet",
        "name": "Google Meet",
        "manage_perms": (
            "horilla_meet.view_googlecloudcredential",
            "horilla_meet.change_googlecloudcredential",
        ),
    },
    {
        "app_label": "linkedin",
        "name": "LinkedIn",
        # LinkedIn posting is toggled via IntegrationApps; accounts live under recruitment.
        "manage_perms": (
            "recruitment.view_linkedinaccount",
            "recruitment.change_linkedinaccount",
            "recruitment.add_linkedinaccount",
        ),
        "installed_app": "recruitment",
    },
)


def _entry_for(app_label):
    for item in CATALOG:
        if item["app_label"] == app_label:
            return item
    return None


def _is_installed(item):
    install_name = item.get("installed_app") or item["app_label"]
    return apps.is_installed(install_name)


def _can_manage(user, item):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return any(user.has_perm(perm) for perm in item["manage_perms"])


def _company_from_request(request):
    selected = request.session.get("selected_company")
    if selected and selected != "all":
        return Company.objects.filter(pk=selected).first()
    return None


def _resolve_row(app_label, company):
    return IntegrationApps.objects.filter(
        app_label=app_label, company=company
    ).first()


def _serialize(item, company):
    row = _resolve_row(item["app_label"], company) if _is_installed(item) else None
    return {
        "app_label": item["app_label"],
        "name": item["name"],
        "installed": _is_installed(item),
        "is_enabled": bool(row and row.is_enabled),
        "company_id": company.id if company else None,
    }


class IntegrationListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        company = _company_from_request(request)
        results = [
            _serialize(item, company)
            for item in CATALOG
            if _can_manage(request.user, item)
        ]
        return Response({"count": len(results), "results": results})


class IntegrationDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, app_label):
        item = _entry_for(app_label)
        if item is None:
            return Response({"detail": "Integration not found."}, status=404)
        if not _can_manage(request.user, item):
            return Response(
                {"detail": "You do not have permission to perform this action."},
                status=403,
            )
        return Response(_serialize(item, _company_from_request(request)))

    def patch(self, request, app_label):
        item = _entry_for(app_label)
        if item is None:
            return Response({"detail": "Integration not found."}, status=404)
        if not _can_manage(request.user, item):
            return Response(
                {"detail": "You do not have permission to perform this action."},
                status=403,
            )
        if not _is_installed(item):
            return Response(
                {"detail": "This integration is not installed."}, status=400
            )
        if "is_enabled" not in request.data:
            return Response({"is_enabled": "This field is required."}, status=400)
        enabled = bool(request.data.get("is_enabled"))
        company = _company_from_request(request)
        row, _created = IntegrationApps.objects.update_or_create(
            app_label=app_label,
            company=company,
            defaults={"is_enabled": enabled},
        )
        return Response(
            {
                "app_label": row.app_label,
                "name": item["name"],
                "installed": True,
                "is_enabled": row.is_enabled,
                "company_id": company.id if company else None,
            }
        )
