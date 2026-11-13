"""
JSON CRUD for an employee's family members.

React owns the screen. These endpoints do not replace the personal-info
fields (marital status, children count, emergency contact).
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from base.methods import employees_in_scope
from employee.models import (
    Employee,
    EmployeeFamilyMember,
    ProfileEditFeature,
    phone_validator,
)
from horilla_api.api_methods.base.pagination import HorillaPageNumberPagination


class OptionalCharField(serializers.CharField):
    """Blank or whitespace becomes null, and model validators see the trimmed value."""

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


class OptionalEmailField(serializers.EmailField):
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


class OptionalChoiceField(serializers.ChoiceField):
    def to_internal_value(self, data):
        if data in ("", None):
            return None
        return super().to_internal_value(data)


class RequiredNameField(serializers.CharField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        value = value.strip()
        if not value:
            self.fail("blank")
        return value


class EmployeeFamilyMemberSerializer(serializers.ModelSerializer):
    first_name = RequiredNameField(max_length=200)
    last_name = OptionalCharField(max_length=200)
    relation_other = serializers.CharField(
        required=False, allow_blank=True, max_length=100
    )
    relation_display = serializers.CharField(
        source="get_relation_display", read_only=True
    )
    gender = OptionalChoiceField(
        choices=Employee.choice_gender, required=False, allow_null=True
    )
    date_of_birth = OptionalDateField()
    phone = OptionalCharField(max_length=25, validators=[phone_validator])
    alternative_phone = OptionalCharField(max_length=25, validators=[phone_validator])
    email = OptionalEmailField()
    address = OptionalCharField(max_length=200)

    class Meta:
        model = EmployeeFamilyMember
        fields = (
            "id",
            "first_name",
            "last_name",
            "relation",
            "relation_display",
            "relation_other",
            "gender",
            "date_of_birth",
            "phone",
            "alternative_phone",
            "email",
            "address",
        )
        read_only_fields = ("id", "relation_display")

    def validate(self, attrs):
        relation = attrs.get("relation", getattr(self.instance, "relation", None))
        sent_other = "relation_other" in attrs
        if relation != EmployeeFamilyMember.RELATION_OTHER:
            if sent_other and (attrs.get("relation_other") or "").strip():
                raise serializers.ValidationError(
                    {
                        "relation_other": _(
                            "Only used when the relation is Other."
                        )
                    }
                )
            attrs["relation_other"] = ""
            return attrs

        if sent_other:
            other = attrs.get("relation_other")
        elif self.instance is not None:
            other = self.instance.relation_other
        else:
            other = ""
        other = (other or "").strip()
        if not other:
            raise serializers.ValidationError(
                {"relation_other": _("Specify the relation.")}
            )
        attrs["relation_other"] = other
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


def can_view_family(request, employee):
    """The employee, their reporting manager, or a holder of view_employee."""
    return employees_in_scope(
        request, [employee.pk], "employee.view_employee", include_self=True
    )


def can_edit_family(request, employee):
    """
    Same scope as a personal-info update: change_employee, a reporting
    manager, or the employee themselves. Self-edit also requires the
    profile-edit feature, matching PUT /employee/employees/<pk>/.
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


class EmployeeFamilyAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, employee_id, pk=None):
        employee = _employee_or_none(employee_id)
        if employee is None:
            return _not_found(_("Employee not found."))
        if not can_view_family(request, employee):
            return _forbidden()
        if pk is None:
            members = EmployeeFamilyMember.objects.filter(employee=employee)
            paginator = HorillaPageNumberPagination()
            page = paginator.paginate_queryset(members, request)
            return paginator.get_paginated_response(
                EmployeeFamilyMemberSerializer(page, many=True).data
            )
        member = EmployeeFamilyMember.objects.filter(employee=employee, pk=pk).first()
        if member is None:
            return _not_found(_("Family member not found."))
        return Response(EmployeeFamilyMemberSerializer(member).data)

    def post(self, request, employee_id, pk=None):
        if pk is not None:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
        employee = _employee_or_none(employee_id)
        if employee is None:
            return _not_found(_("Employee not found."))
        allowed, detail = can_edit_family(request, employee)
        if not allowed:
            return _forbidden(detail)
        serializer = EmployeeFamilyMemberSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            member = serializer.save(employee=employee)
        except DjangoValidationError as exc:
            return _validation_error(exc)
        return Response(
            EmployeeFamilyMemberSerializer(member).data,
            status=status.HTTP_201_CREATED,
        )

    def patch(self, request, employee_id, pk=None):
        if pk is None:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
        employee = _employee_or_none(employee_id)
        if employee is None:
            return _not_found(_("Employee not found."))
        allowed, detail = can_edit_family(request, employee)
        if not allowed:
            return _forbidden(detail)
        member = EmployeeFamilyMember.objects.filter(employee=employee, pk=pk).first()
        if member is None:
            return _not_found(_("Family member not found."))
        serializer = EmployeeFamilyMemberSerializer(
            member, data=request.data, partial=True
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            member = serializer.save()
        except DjangoValidationError as exc:
            return _validation_error(exc)
        return Response(EmployeeFamilyMemberSerializer(member).data)

    def delete(self, request, employee_id, pk=None):
        if pk is None:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
        employee = _employee_or_none(employee_id)
        if employee is None:
            return _not_found(_("Employee not found."))
        allowed, detail = can_edit_family(request, employee)
        if not allowed:
            return _forbidden(detail)
        member = EmployeeFamilyMember.objects.filter(employee=employee, pk=pk).first()
        if member is None:
            return _not_found(_("Family member not found."))
        member.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
