"""Uganda statutory schedule: JSON preview, CSV and XLSX downloads."""

import csv
from io import BytesIO, StringIO

from django.http import HttpResponse
from django.utils.translation import gettext as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from horilla_api.api_methods.payroll.uganda_schedule import (
    ALL_STATUSES,
    DEFAULT_STATUSES,
    LAYOUTS,
    build_schedule,
    month_bounds,
    table,
)
from payroll.models.models import Payslip

from .common import company_for, require_perm


def _scope(request):
    """``(start, end, payslips, error_response)`` for the requested month."""
    bounds = month_bounds(request.GET.get("month"))
    if bounds is None:
        return None, None, None, Response(
            {"month": [_("Choose a month as YYYY-MM.")]}, status=400
        )
    start, end = bounds
    # A pay period belongs to the month it ends in, so a 26th-to-25th cycle
    # is filed with the month that pays it.
    queryset = Payslip.objects.filter(end_date__gte=start, end_date__lte=end)
    company = company_for(request)
    if company is not None:
        queryset = queryset.filter(employee_id__employee_work_info__company_id=company)
    status = (request.GET.get("status") or "").strip()
    if status == "all":
        statuses = ALL_STATUSES
    elif status in ALL_STATUSES:
        statuses = (status,)
    elif status:
        return None, None, None, Response(
            {"status": [_("Unknown payslip status.")]}, status=400
        )
    else:
        statuses = DEFAULT_STATUSES
    queryset = queryset.filter(status__in=statuses).select_related("employee_id")
    return start, end, queryset, None


def _layout(request):
    layout = (request.GET.get("layout") or "summary").strip()
    return layout if layout in LAYOUTS else None


class UgandaScheduleView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_payslip")
        if blocked:
            return blocked
        start, end, payslips, error = _scope(request)
        if error:
            return error
        rows, totals, missing = build_schedule(payslips)
        return Response(
            {
                "month": start.strftime("%Y-%m"),
                "period_start": start,
                "period_end": end,
                "layouts": sorted(LAYOUTS),
                "totals": totals,
                "missing": missing,
                "rows": rows,
            },
            status=200,
        )


class UgandaScheduleExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_payslip")
        if blocked:
            return blocked
        start, _end, payslips, error = _scope(request)
        if error:
            return error
        layout = _layout(request)
        if layout is None:
            return Response({"layout": [_("Unknown layout.")]}, status=400)
        file_format = (request.GET.get("file_format") or "csv").strip().lower()
        if file_format not in ("csv", "xlsx"):
            return Response(
                {"file_format": [_("Choose csv or xlsx.")]}, status=400
            )

        rows, totals, _missing = build_schedule(payslips)
        header, body, footer, columns = table(rows, totals, layout)
        name = f"uganda-statutory-{start.strftime('%Y-%m')}-{layout}"

        if file_format == "csv":
            buffer = StringIO()
            writer = csv.writer(buffer)
            writer.writerow(header)
            writer.writerows(body)
            writer.writerow(footer)
            response = HttpResponse(buffer.getvalue(), content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="{name}.csv"'
            return response

        from openpyxl import Workbook
        from openpyxl.styles import Font

        book = Workbook()
        sheet = book.active
        sheet.title = start.strftime("%Y-%m")
        sheet.append(header)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for values in body:
            sheet.append(values)
        sheet.append(footer)
        for cell in sheet[sheet.max_row]:
            cell.font = Font(bold=True)
        for index, column in enumerate(columns, start=1):
            letter = sheet.cell(row=1, column=index).column_letter
            sheet.column_dimensions[letter].width = max(12, len(column.header) + 2)
            if column.money:
                for (cell,) in sheet.iter_rows(
                    min_row=2, min_col=index, max_col=index
                ):
                    cell.number_format = "#,##0.00"
        sheet.freeze_panes = "A2"
        output = BytesIO()
        book.save(output)
        response = HttpResponse(
            output.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = f'attachment; filename="{name}.xlsx"'
        return response
