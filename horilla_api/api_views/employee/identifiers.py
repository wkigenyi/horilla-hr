"""
JSON CRUD for identity documents other than National ID and Tax ID.

Those two are columns on the employee. React owns this screen.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from base.methods import employees_in_scope
from employee.models import Employee, EmployeeIdentifier, ProfileEditFeature
from horilla_api.api_methods.base.pagination import HorillaPageNumberPagination


class OptionalCharField(serializers.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("allow_blank", True)
        kwargs.setdefault("allow_null", True)
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)

    def run_validation(self, data=serializers.empty):
        if data is None or (isinstance(data, str) and not data.strip()):
            return None
        if isinstance(data, str):
            data = data.strip()
        return super().run_validation(data)


class OptionalDateField(serializers.DateField):
    def __init__(self, **kwargs):
        kwargs.setdefault("allow_null", True)
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)

    def to_internal_value(self, value):
        if value in ("", None):
            return None
        return super().to_internal_value(value)


class RequiredTrimmedField(serializers.CharField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        value = value.strip()
        if not value:
            self.fail("blank")
        return value


class EmployeeIdentifierSerializer(serializers.ModelSerializer):
    document_number = RequiredTrimmedField(max_length=64)
    document_type_other = serializers.CharField(
        required=False, allow_blank=True, max_length=100
    )
    document_type_display = serializers.CharField(
        source="get_document_type_display", read_only=True
    )
    issuing_authority = OptionalCharField(max_length=200)
    issue_date = OptionalDateField()
    expiry_date = OptionalDateField()

    class Meta:
        model = EmployeeIdentifier
        fields = (
            "id",
            "document_type",
            "document_type_display",
            "document_type_other",
            "document_number",
            "issuing_authority",
            "issue_date",
            "expiry_date",
        )
        read_only_fields = ("id", "document_type_display")

    def validate(self, attrs):
        document_type = attrs.get(
            "document_type", getattr(self.instance, "document_type", None)
        )
        sent_other = "document_type_other" in attrs
        if document_type != EmployeeIdentifier.TYPE_OTHER:
            if sent_other and (attrs.get("document_type_other") or "").strip():
                raise serializers.ValidationError(
                    {
                        "document_type_other": _(
                            "Only used when the document type is Other."
                        )
                    }
                )
            attrs["document_type_other"] = ""
        else:
            if sent_other:
                other = attrs.get("document_type_other")
            elif self.instance is not None:
                other = self.instance.document_type_other
            else:
                other = ""
            other = (other or "").strip()
            if not other:
                raise serializers.ValidationError(
                    {"document_type_other": _("Specify the document type.")}
                )
            attrs["document_type_other"] = other

        issue = attrs["issue_date"] if "issue_date" in attrs else getattr(
            self.instance, "issue_date", None
        )
        expiry = attrs["expiry_date"] if "expiry_date" in attrs else getattr(
            self.instance, "expiry_date", None
        )
        if issue and expiry and expiry < issue:
            raise serializers.ValidationError(
                {
                    "expiry_date": _(
                        "Expiry date cannot be before the issue date."
                    )
                }
            )
        return attrs


def _employee_or_none(employee_id):
    return (
        Employee.objects.select_related("employee_user_id", "employee_work_info")
        .filter(pk=employee_id)
        .first()
    )


def _forbidden(detail=None):
    return Response(
        {"detail": detail or _("You do not have permission to perform this action.")},
        status=status.HTTP_403_FORBIDDEN,
    )


def _not_found(detail):
    return Response({"detail": detail}, status=status.HTTP_404_NOT_FOUND)


def _validation_error(exc):
    if hasattr(exc, "message_dict"):
        return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)
    return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)


def can_view_identifiers(request, employee):
    """The employee, their reporting manager, or a holder of view_employee."""
    return employees_in_scope(
        request, [employee.pk], "employee.view_employee", include_self=True
    )


def can_edit_identifiers(request, employee):
    """
    Same scope as family members: change_employee, a reporting manager, or
    the employee themselves when profile edit is on.
    """
    if not employees_in_scope(
        request, [employee.pk], "employee.change_employee", include_self=True
    ):
        return False, None
    user = request.user
    caller = getattr(user, "employee_get", None)
    is_self = caller is not None and caller.pk == employee.pk
    if is_self and not user.has_perm("employee.change_employee"):
        if not ProfileEditFeature.objects.filter(is_enabled=True).exists():
            return False, _("Profile editing is disabled.")
    return True, None


class EmployeeIdentifierAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, employee_id, pk=None):
        employee = _employee_or_none(employee_id)
        if employee is None:
            return _not_found(_("Employee not found."))
        if not can_view_identifiers(request, employee):
            return _forbidden()
        if pk is None:
            documents = EmployeeIdentifier.objects.filter(employee=employee)
            paginator = HorillaPageNumberPagination()
            page = paginator.paginate_queryset(documents, request)
            return paginator.get_paginated_response(
                EmployeeIdentifierSerializer(page, many=True).data
            )
        document = EmployeeIdentifier.objects.filter(employee=employee, pk=pk).first()
        if document is None:
            return _not_found(_("Identity document not found."))
        return Response(EmployeeIdentifierSerializer(document).data)

    def post(self, request, employee_id, pk=None):
        if pk is not None:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
        employee = _employee_or_none(employee_id)
        if employee is None:
            return _not_found(_("Employee not found."))
        allowed, detail = can_edit_identifiers(request, employee)
        if not allowed:
            return _forbidden(detail)
        serializer = EmployeeIdentifierSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            document = serializer.save(employee=employee)
        except DjangoValidationError as exc:
            return _validation_error(exc)
        return Response(
            EmployeeIdentifierSerializer(document).data,
            status=status.HTTP_201_CREATED,
        )

    def patch(self, request, employee_id, pk=None):
        if pk is None:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
        employee = _employee_or_none(employee_id)
        if employee is None:
            return _not_found(_("Employee not found."))
        allowed, detail = can_edit_identifiers(request, employee)
        if not allowed:
            return _forbidden(detail)
        document = EmployeeIdentifier.objects.filter(employee=employee, pk=pk).first()
        if document is None:
            return _not_found(_("Identity document not found."))
        serializer = EmployeeIdentifierSerializer(
            document, data=request.data, partial=True
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            document = serializer.save()
        except DjangoValidationError as exc:
            return _validation_error(exc)
        return Response(EmployeeIdentifierSerializer(document).data)

    def delete(self, request, employee_id, pk=None):
        if pk is None:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
        employee = _employee_or_none(employee_id)
        if employee is None:
            return _not_found(_("Employee not found."))
        allowed, detail = can_edit_identifiers(request, employee)
        if not allowed:
            return _forbidden(detail)
        document = EmployeeIdentifier.objects.filter(employee=employee, pk=pk).first()
        if document is None:
            return _not_found(_("Identity document not found."))
        document.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
