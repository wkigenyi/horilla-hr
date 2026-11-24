"""Arrears, recovery, and the spreadsheet import."""

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.utils.translation import gettext as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from base.import_template_data import import_template_frame, write_import_xlsx
from employee.models import Employee
from horilla_api.api_methods.base.pagination import HorillaPageNumberPagination
from payroll.methods.pay_adjustment_import import (
    HEADERS,
    SheetProblem,
    check_sheet,
    create_entries,
    read_sheet,
)
from payroll.models.models import PayAdjustment

from .common import (
    as_id_list,
    employee_brief,
    parse_date,
    require_perm,
    validation_response,
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _adjustment_payload(entry):
    payslip = entry.payslip()
    return {
        "id": entry.pk,
        "employee": employee_brief(entry.employee_id),
        "kind": entry.kind,
        "title": entry.title,
        "reason": entry.reason,
        "amount": entry.amount,
        "pay_date": entry.pay_date,
        "tax_treatment": entry.tax_treatment,
        "status": entry.status,
        "approved_by": employee_brief(entry.approved_by),
        "approved_on": entry.approved_on,
        "payslip_id": payslip.pk if payslip else None,
        "is_paid": entry.is_paid(),
        "month_closed": entry.month_is_closed(),
    }


def _fill(entry, data):
    if "employee_id" in data:
        employee = Employee.objects.filter(pk=data["employee_id"]).first()
        if employee is None:
            raise ValidationError({"employee_id": _("Employee not found.")})
        entry.employee_id = employee
    if "kind" in data:
        entry.kind = data["kind"]
    if "title" in data:
        entry.title = data["title"]
    if "reason" in data:
        entry.reason = data["reason"] or ""
    if "amount" in data:
        entry.amount = data["amount"]
    if "pay_date" in data:
        parsed = parse_date(data["pay_date"])
        if parsed is None:
            raise ValidationError({"pay_date": _("Enter a pay date.")})
        entry.pay_date = parsed
    if "tax_treatment" in data:
        entry.tax_treatment = data["tax_treatment"]


class PayAdjustmentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        blocked = require_perm(request, "payroll.view_payadjustment")
        if blocked:
            return blocked
        if pk:
            entry = PayAdjustment.objects.filter(pk=pk).first()
            if entry is None:
                return Response({"detail": _("Not found.")}, status=404)
            return Response(_adjustment_payload(entry), status=200)
        queryset = PayAdjustment.objects.all()
        kind = request.GET.get("kind")
        if kind:
            queryset = queryset.filter(kind=kind)
        status = request.GET.get("status")
        if status:
            queryset = queryset.filter(status=status)
        pagination = HorillaPageNumberPagination()
        page = pagination.paginate_queryset(queryset, request)
        return pagination.get_paginated_response(
            [_adjustment_payload(entry) for entry in page]
        )

    def post(self, request):
        blocked = require_perm(request, "payroll.add_payadjustment")
        if blocked:
            return blocked
        entry = PayAdjustment(status="draft")
        try:
            _fill(entry, request.data)
            entry.full_clean()
            entry.save()
        except ValidationError as exc:
            return validation_response(exc)
        return Response(_adjustment_payload(entry), status=201)

    def put(self, request, pk):
        blocked = require_perm(request, "payroll.change_payadjustment")
        if blocked:
            return blocked
        entry = PayAdjustment.objects.filter(pk=pk).first()
        if entry is None:
            return Response({"detail": _("Not found.")}, status=404)
        if not entry.is_editable:
            return Response(
                {"detail": _("A confirmed entry is locked. Send it back to draft first.")},
                status=400,
            )
        try:
            _fill(entry, request.data)
            entry.full_clean()
            entry.save()
        except ValidationError as exc:
            return validation_response(exc)
        return Response(_adjustment_payload(entry), status=200)

    def delete(self, request, pk):
        blocked = require_perm(request, "payroll.delete_payadjustment")
        if blocked:
            return blocked
        entry = PayAdjustment.objects.filter(pk=pk).first()
        if entry is None:
            return Response({"detail": _("Not found.")}, status=404)
        try:
            entry.delete()
        except ValidationError as exc:
            return validation_response(exc)
        return Response({"status": "deleted"}, status=200)


class PayAdjustmentStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        blocked = require_perm(request, "payroll.change_payadjustment")
        if blocked:
            return blocked
        entry = PayAdjustment.objects.filter(pk=pk).first()
        if entry is None:
            return Response({"detail": _("Not found.")}, status=404)
        wanted = request.data.get("status")
        approver = getattr(request.user, "employee_get", None)
        try:
            if wanted == "approved":
                entry.approve(approved_by=approver)
            elif wanted == "draft":
                entry.revert()
            else:
                return Response({"status": [_("Status must be approved or draft.")]}, status=400)
        except ValidationError as exc:
            return validation_response(exc)
        entry.refresh_from_db()
        return Response(_adjustment_payload(entry), status=200)


class PayAdjustmentBulkStatusView(APIView):
    """Confirm several entries, or send several back to draft, by the rules of one."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        blocked = require_perm(request, "payroll.change_payadjustment")
        if blocked:
            return blocked
        wanted = request.data.get("status")
        if wanted not in ("approved", "draft"):
            return Response({"status": [_("Status must be approved or draft.")]}, status=400)
        ids = as_id_list(request.data.get("ids"))
        if not ids:
            return Response({"ids": [_("Select at least one entry.")]}, status=400)
        entries = list(PayAdjustment.objects.filter(pk__in=ids))
        updated, problems = PayAdjustment.bulk_change(
            entries,
            status=wanted,
            approved_by=getattr(request.user, "employee_get", None),
        )
        return Response(
            {"updated": updated, "problems": problems, "status": wanted}, status=200
        )


class PayAdjustmentImportTemplateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.add_payadjustment")
        if blocked:
            return blocked
        response = HttpResponse(content_type=XLSX)
        response["Content-Disposition"] = (
            'attachment; filename="arrears_recovery_import_template.xlsx"'
        )
        write_import_xlsx(import_template_frame("pay_adjustment"), response)
        return response


class PayAdjustmentImportView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        blocked = require_perm(request, "payroll.add_payadjustment")
        if blocked:
            return blocked
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": [_("Choose a file to import.")]}, status=400)
        try:
            rows, table = check_sheet(read_sheet(upload))
        except SheetProblem as problem:
            return Response({"file": [str(problem)]}, status=400)
        failed = [row for row in table if row["errors"]]
        return Response(
            {
                "headers": HEADERS,
                "rows": rows,
                "table": table,
                "valid_count": len(rows),
                "failed_count": len(failed),
                "failed": failed,
            },
            status=200,
        )


class PayAdjustmentImportConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        blocked = require_perm(request, "payroll.add_payadjustment")
        if blocked:
            return blocked
        rows = request.data.get("rows") or []
        if not isinstance(rows, list) or not rows:
            return Response({"rows": [_("Nothing to import.")]}, status=400)
        created, skipped = create_entries(rows)
        return Response(
            {
                "created": created,
                "skipped": [{"row": row, "reason": reason} for row, reason in skipped],
            },
            status=200,
        )


class PayAdjustmentImportErrorsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        blocked = require_perm(request, "payroll.add_payadjustment")
        if blocked:
            return blocked
        failed = request.data.get("failed") or []
        if not failed:
            return Response({"detail": _("There are no failed rows to download.")}, status=404)
        import pandas as pd

        frame = pd.DataFrame(
            [
                [
                    row.get("badge"),
                    row.get("kind"),
                    row.get("title"),
                    row.get("amount"),
                    row.get("pay_date"),
                    {"Yes": "Yes", "No": "No"}.get(str(row.get("tax")), ""),
                    row.get("reason"),
                    "; ".join(row.get("errors") or []),
                ]
                for row in failed
            ],
            columns=HEADERS + ["Errors"],
        )
        response = HttpResponse(content_type=XLSX)
        response["Content-Disposition"] = (
            'attachment; filename="arrears_recovery_import_errors.xlsx"'
        )
        write_import_xlsx(frame, response)
        return response
