"""
WhatsApp credential maintenance for React.

Mirrors whatsapp.cbv credential list/form/delete/test-message. The Meta
webhook at /whatsapp/ stays Meta→Django and is not part of this surface.
"""

import requests
from django.utils.translation import gettext as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from base.models import IntegrationApps
from horilla_api.api_methods.base.pagination import HorillaPageNumberPagination
from horilla_api.api_serializers.whatsapp.serializers import (
    WhatsappCredentialSerializer,
)
from whatsapp.models import WhatsappCredientials
from whatsapp.utils import get_meta_details_from_id


def _integration_on():
    return IntegrationApps.objects.filter(
        app_label="whatsapp", is_enabled=True
    ).exists()


def _forbidden(detail=None):
    return Response(
        {"detail": detail or "You do not have permission to perform this action."},
        status=403,
    )


def _require_enabled():
    if not _integration_on():
        return Response(
            {"detail": "WhatsApp integration is disabled."},
            status=403,
        )
    return None


class WhatsappCredentialListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.has_perm("whatsapp.view_whatsappcredientials"):
            return _forbidden()
        blocked = _require_enabled()
        if blocked:
            return blocked
        qs = WhatsappCredientials.objects.all().order_by("-id")
        paginator = HorillaPageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        data = WhatsappCredentialSerializer(page, many=True).data
        return paginator.get_paginated_response(data)

    def post(self, request):
        if not request.user.has_perm("whatsapp.add_whatsappcredientials"):
            return _forbidden()
        blocked = _require_enabled()
        if blocked:
            return blocked
        serializer = WhatsappCredentialSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        instance = serializer.save()
        return Response(
            WhatsappCredentialSerializer(instance).data, status=201
        )


class WhatsappCredentialDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        return WhatsappCredientials.objects.filter(pk=pk).first()

    def get(self, request, pk):
        if not request.user.has_perm("whatsapp.view_whatsappcredientials"):
            return _forbidden()
        blocked = _require_enabled()
        if blocked:
            return blocked
        instance = self._get(pk)
        if instance is None:
            return Response({"detail": "Credential not found."}, status=404)
        return Response(WhatsappCredentialSerializer(instance).data)

    def patch(self, request, pk):
        if not request.user.has_perm("whatsapp.change_whatsappcredientials"):
            return _forbidden()
        blocked = _require_enabled()
        if blocked:
            return blocked
        instance = self._get(pk)
        if instance is None:
            return Response({"detail": "Credential not found."}, status=404)
        serializer = WhatsappCredentialSerializer(
            instance, data=request.data, partial=True
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        instance = serializer.save()
        return Response(WhatsappCredentialSerializer(instance).data)

    def delete(self, request, pk):
        if not request.user.has_perm("whatsapp.delete_whatsappcredientials"):
            return _forbidden()
        blocked = _require_enabled()
        if blocked:
            return blocked
        instance = self._get(pk)
        if instance is None:
            return Response({"detail": "Credential not found."}, status=404)
        instance.delete()
        return Response(status=204)


class WhatsappTestMessageAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not request.user.has_perm("whatsapp.view_whatsappcredientials"):
            return _forbidden()
        blocked = _require_enabled()
        if blocked:
            return blocked
        instance = WhatsappCredientials.objects.filter(pk=pk).first()
        if instance is None:
            return Response({"detail": "Credential not found."}, status=404)
        number = str(request.data.get("number") or "").strip()
        if not number:
            return Response({"number": "This field is required."}, status=400)
        message = str(
            request.data.get("message") or _("This is a test message")
        ).strip()
        meta = get_meta_details_from_id(instance.id)
        headers = {
            "Authorization": f'Bearer {meta.get("token", "")}',
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {"body": message},
        }
        try:
            response = requests.post(
                meta.get("url", ""), headers=headers, json=payload, timeout=30
            )
            body = response.json() if response.content else {}
        except Exception as exc:
            return Response({"detail": str(exc)}, status=502)
        if "error" in body or response.status_code not in (200, 201):
            detail = (
                body.get("error", {}).get("message")
                if isinstance(body.get("error"), dict)
                else body.get("error") or body
            )
            return Response({"detail": detail}, status=502)
        return Response({"detail": "Message sent successfully."}, status=200)
