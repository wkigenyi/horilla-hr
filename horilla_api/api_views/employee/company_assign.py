"""
Put several employees in one company from the directory.

``EmployeeBulkUpdateView`` can already set ``company_id``, but through a
queryset ``update()``: it takes any work-info field, skips the model's save
(and the history it writes), says nothing about rows it could not touch, and
leaves out anyone without a work-info record. This sets the company only,
saves each record, and reports per employee.

Who: holders of ``employee.change_employee``, the same as the bulk update.
Which employees: only those the caller's company scope already shows, because
``Employee.objects`` applies it; an id outside it is reported as not found.
Which company: when company-scoped permissions are on, a non-superuser may
only assign a company they are allowed into, so nobody can move people into a
company they cannot see.
"""

from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from base.auth_backends import company_scoped_active, get_allowed_company_ids
from base.models import Company
from employee.models import Employee, EmployeeWorkInformation

from ..payroll.common import as_id_list

MAX_EMPLOYEES = 1000


def _name(employee):
    return (
        f"{employee.employee_first_name or ''} {employee.employee_last_name or ''}".strip()
        or _("Employee %(id)s") % {"id": employee.pk}
    )


class EmployeeBulkCompanyView(APIView):
    """``POST {"ids": [...], "company_id": n}`` -> ``{updated, unchanged, problems}``."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.has_perm("employee.change_employee"):
            return Response(
                {"error": _("You do not have permission to perform this action.")},
                status=403,
            )

        ids = list(dict.fromkeys(as_id_list(request.data.get("ids"))))
        if not ids:
            return Response({"ids": [_("Select at least one employee.")]}, status=400)
        if len(ids) > MAX_EMPLOYEES:
            return Response(
                {"ids": [_("Choose %(max)s employees or fewer.") % {"max": MAX_EMPLOYEES}]},
                status=400,
            )

        company_ids = as_id_list(request.data.get("company_id"))
        company = (
            Company.objects.filter(pk=company_ids[0]).first() if company_ids else None
        )
        if company is None:
            return Response({"company_id": [_("Choose a company.")]}, status=400)
        if company_scoped_active() and not request.user.is_superuser:
            if company.pk not in set(get_allowed_company_ids(request.user) or []):
                return Response(
                    {"company_id": [_("You cannot assign people to that company.")]},
                    status=403,
                )

        employees = {
            employee.pk: employee
            for employee in Employee.objects.filter(pk__in=ids).select_related(
                "employee_work_info"
            )
        }
        updated = 0
        unchanged = 0
        problems = []
        with transaction.atomic():
            for pk in ids:
                employee = employees.get(pk)
                if employee is None:
                    problems.append(_("Employee %(id)s was not found.") % {"id": pk})
                    continue
                work_info = getattr(employee, "employee_work_info", None)
                if work_info is None:
                    work_info, _created = EmployeeWorkInformation.objects.get_or_create(
                        employee_id=employee
                    )
                if work_info.company_id_id == company.pk:
                    unchanged += 1
                    continue
                work_info.company_id = company
                work_info.save()
                updated += 1

        return Response(
            {
                "updated": updated,
                "unchanged": unchanged,
                "problems": problems,
                "company_id": company.pk,
                "company": company.company,
            },
            status=200,
        )
