"""Shared helpers for the payroll JSON API."""

from datetime import date, datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework.response import Response


def denied():
    return Response({"detail": _("Permission denied.")}, status=403)


def require_perm(request, perm):
    if request.user.has_perm(perm):
        return None
    return denied()


def parse_date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value.strip():
        return date.fromisoformat(value.strip()[:10])
    return None


def as_id_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        parts = text.split(",")
        return [int(item) for item in parts if item.strip().isdigit()]
    if isinstance(value, (int, float)):
        return [int(value)]
    if not isinstance(value, (list, tuple)):
        return []
    ids = []
    for item in value:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def company_for(request):
    """
    The company a payroll request is about.

    The company the request is scoped to comes first: the one picked in the
    switcher for a superuser, the work company for everyone else. Only when no
    single company is selected ("All companies") does it fall back to the
    caller's own employer, so payroll run for a sister company uses that
    company's pay period and settings rather than the caller's.
    """
    from base.models import Company
    from horilla.horilla_middlewares import get_selected_company

    selected = get_selected_company()
    if selected and selected != "all":
        company = Company._base_manager.filter(pk=selected).first()
        if company is not None:
            return company
    employee = getattr(request.user, "employee_get", None)
    getter = getattr(employee, "get_company", None)
    return getter() if getter else None


def validation_response(exc):
    if getattr(exc, "message_dict", None):
        return Response(exc.message_dict, status=400)
    messages = getattr(exc, "messages", None) or [str(exc)]
    return Response({"detail": [str(message) for message in messages]}, status=400)


def django_to_rest(exc: DjangoValidationError):
    if getattr(exc, "message_dict", None):
        return {key: [str(item) for item in value] for key, value in exc.message_dict.items()}
    return {"detail": [str(message) for message in exc.messages]}


def employee_brief(employee):
    if employee is None:
        return None
    return {
        "id": employee.pk,
        "name": employee.get_full_name(),
        "badge_id": getattr(employee, "badge_id", None),
    }


def payslip_edit_block(payslip):
    """Paid slips, and slips inside an approved or paid batch, cannot be edited or deleted."""
    if payslip.status == "paid" or payslip.status_locked:
        message = (
            payslip.status_lock_message
            if payslip.status_locked
            else _("A paid payslip cannot be changed.")
        )
        return Response({"detail": message}, status=400)
    return None
