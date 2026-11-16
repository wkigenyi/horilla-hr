"""GL mappings and department-grained accounting summary / CSV export."""

import csv
from datetime import date
from io import StringIO

from django.http import HttpResponse
from django.utils.translation import gettext as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from payroll.methods.accounting_report import (
    attach_gl_codes,
    is_mappable_key,
    mappable_line_keys,
    summarise,
)
from payroll.models.accounting_gl import PayrollGLMapping
from payroll.models.models import PayPeriodSettings, Payslip

from .common import company_for, parse_date, require_perm

CSV_COLUMNS = (
    "period_start",
    "period_end",
    "department_id",
    "department",
    "line_key",
    "title",
    "category",
    "nature",
    "posting",
    "amount",
    "gl_code",
    "component_id",
)


def _period(request):
    company = company_for(request)
    settings = PayPeriodSettings.for_company(company)
    default_start, default_end = settings.period_for(date.today())
    start = parse_date(request.GET.get("start_date")) or default_start
    end = parse_date(request.GET.get("end_date")) or default_end
    return company, start, end


def _accounting_payslips(request, start, end):
    company = company_for(request)
    queryset = Payslip.objects.filter(start_date__gte=start, end_date__lte=end)
    if company is not None:
        queryset = queryset.filter(
            employee_id__employee_work_info__company_id=company
        )
    status = request.GET.get("status")
    if status is None or status == "":
        queryset = queryset.filter(status="paid")
    else:
        queryset = queryset.filter(status=status)
    batch = request.GET.get("batch") or request.GET.get("payroll_batch")
    if batch:
        try:
            queryset = queryset.filter(payroll_batch_id=int(batch))
        except (TypeError, ValueError):
            queryset = queryset.none()
    return queryset.select_related(
        "employee_id__employee_work_info__department_id"
    )


def _row_payload(row):
    return {
        "key": row["key"],
        "title": str(row["title"]),
        "category": row["category"],
        "nature": row["nature"],
        "posting": row["posting"],
        "amount": row["amount"],
        "department_id": row.get("department_id"),
        "department": row.get("department"),
        "gl_code": row.get("gl_code") or "",
        "component_id": row.get("component_id"),
    }


class AccountingGLMappingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_payrollsettings")
        if blocked:
            return blocked
        company = company_for(request)
        if company is None:
            return Response(
                {"detail": _("No company assigned to this account.")}, status=400
            )
        stored = {
            row.line_key: row
            for row in PayrollGLMapping.objects.filter(company_id=company)
        }
        mappings = []
        for line in mappable_line_keys(company):
            row = stored.get(line["key"])
            mappings.append(
                {
                    "line_key": line["key"],
                    "title": str(line["title"]),
                    "category": line["category"],
                    "nature": line["nature"],
                    "posting": line["posting"],
                    "component_id": line.get("component_id"),
                    "gl_code": (row.gl_code if row else "") or "",
                    "label": (row.label if row else "") or "",
                }
            )
        return Response({"company_id": company.pk, "mappings": mappings}, status=200)

    def put(self, request):
        blocked = require_perm(request, "payroll.change_payrollsettings")
        if blocked:
            return blocked
        company = company_for(request)
        if company is None:
            return Response(
                {"detail": _("No company assigned to this account.")}, status=400
            )
        payload = request.data.get("mappings")
        if not isinstance(payload, list):
            return Response(
                {"detail": _("Expected a mappings list.")}, status=400
            )
        unknown = []
        for item in payload:
            if not isinstance(item, dict):
                return Response(
                    {"detail": _("Each mapping must be an object.")}, status=400
                )
            line_key = (item.get("line_key") or "").strip()
            if not is_mappable_key(line_key, company):
                unknown.append(line_key or "")
        if unknown:
            return Response(
                {
                    "detail": _("Unknown line keys."),
                    "line_keys": unknown,
                },
                status=400,
            )

        for item in payload:
            line_key = (item.get("line_key") or "").strip()
            gl_code = item.get("gl_code")
            if gl_code is None:
                gl_code = ""
            label = item.get("label")
            if label is None:
                label = ""
            row, _created = PayrollGLMapping.objects.get_or_create(
                company_id=company,
                line_key=line_key,
            )
            row.gl_code = str(gl_code)
            row.label = str(label)
            row.save()

        # Return the same shape as GET.
        return self.get(request)


class AccountingSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_payslip")
        if blocked:
            return blocked
        company, start, end = _period(request)
        payslips = _accounting_payslips(request, start, end)
        rows, totals = summarise(payslips)
        attach_gl_codes(rows, company)
        return Response(
            {
                "period_start": start,
                "period_end": end,
                "totals": totals,
                "rows": [_row_payload(row) for row in rows],
            },
            status=200,
        )


class AccountingExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_payslip")
        if blocked:
            return blocked
        company, start, end = _period(request)
        payslips = _accounting_payslips(request, start, end)
        rows, _totals = summarise(payslips)
        attach_gl_codes(rows, company)

        buffer = StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "period_start": start.isoformat(),
                    "period_end": end.isoformat(),
                    "department_id": row.get("department_id") or "",
                    "department": row.get("department") or "",
                    "line_key": row["key"],
                    "title": str(row["title"]),
                    "category": row["category"],
                    "nature": row["nature"],
                    "posting": "1" if row.get("posting") else "0",
                    "amount": row["amount"],
                    "gl_code": row.get("gl_code") or "",
                    "component_id": row.get("component_id") or "",
                }
            )

        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="payroll-accounting-{start}-{end}.csv"'
        )
        return response
