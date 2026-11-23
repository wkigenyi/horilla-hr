"""Pay period, payroll review, and the batch run."""

from datetime import date

from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from employee.models import Employee
from horilla_api.api_methods.base.pagination import HorillaPageNumberPagination
from payroll.methods import batch_run
from payroll.models.models import PayPeriodSettings, PayrollBatch, PayrollBatchLine
from payroll.scheduler import generate_for_setting

from .common import (
    as_id_list,
    company_for,
    employee_brief,
    parse_date,
    require_perm,
    validation_response,
)


def _period_payload(settings, today=None):
    today = today or date.today()
    current = settings.period_for(today)
    last = settings.last_completed_period(today)
    auto = settings.next_auto_run(today) if settings.pk else (last[0], last[1], last[1])
    return {
        "id": settings.pk,
        "company_id": settings.company_id_id,
        "boundary": settings.boundary,
        "cycle_start_day": settings.cycle_start_day,
        "pay_day_of_month": settings.pay_day_of_month,
        "pay_day_offset": settings.pay_day_offset,
        "input_cutoff_days": settings.input_cutoff_days,
        "auto_generate": settings.auto_generate,
        "last_generated_end": settings.last_generated_end,
        "summary": settings.summary() if settings.pk or settings.cycle_start_day else "",
        "current_period": {"start": current[0], "end": current[1]},
        "last_completed_period": {"start": last[0], "end": last[1]},
        "pay_date": settings.pay_date_for(last[1]),
        "next_auto_run": {"start": auto[0], "end": auto[1], "run_date": auto[2]},
    }


def _apply_period(settings, data):
    for field in (
        "cycle_start_day",
        "pay_day_of_month",
        "pay_day_offset",
        "input_cutoff_days",
    ):
        if field in data and data[field] not in (None, ""):
            setattr(settings, field, int(data[field]))
    if "auto_generate" in data:
        settings.auto_generate = bool(data["auto_generate"])
    if "company_id" in data:
        settings.company_id_id = data.get("company_id") or None
    settings.full_clean()
    settings.save()


class PayPeriodView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        blocked = require_perm(request, "payroll.view_payslip")
        if blocked:
            return blocked
        if pk:
            row = PayPeriodSettings.objects.entire().filter(pk=pk).first()
            if row is None:
                return Response({"detail": _("Pay period not found.")}, status=404)
            return Response(_period_payload(row), status=200)
        rows = PayPeriodSettings.objects.entire().order_by("company_id_id", "pk")
        return Response([_period_payload(row) for row in rows], status=200)

    def post(self, request):
        blocked = require_perm(request, "payroll.change_payslipautogenerate")
        if blocked:
            return blocked
        row = PayPeriodSettings(company_id=company_for(request))
        try:
            _apply_period(row, request.data)
        except Exception as exc:
            if hasattr(exc, "message_dict") or hasattr(exc, "messages"):
                return validation_response(exc)
            raise
        return Response(_period_payload(row), status=201)

    def put(self, request, pk):
        blocked = require_perm(request, "payroll.change_payslipautogenerate")
        if blocked:
            return blocked
        row = PayPeriodSettings.objects.entire().filter(pk=pk).first()
        if row is None:
            return Response({"detail": _("Pay period not found.")}, status=404)
        try:
            _apply_period(row, request.data)
        except Exception as exc:
            if hasattr(exc, "message_dict") or hasattr(exc, "messages"):
                return validation_response(exc)
            raise
        return Response(_period_payload(row), status=200)

    def delete(self, request, pk):
        blocked = require_perm(request, "payroll.delete_payslipautogenerate")
        if blocked:
            return blocked
        row = PayPeriodSettings.objects.entire().filter(pk=pk).first()
        if row is None:
            return Response({"detail": _("Pay period not found.")}, status=404)
        row.delete()
        return Response({"status": "deleted"}, status=200)


class PayPeriodGenerateView(APIView):
    """Generate payslips for the company's last completed period."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        blocked = require_perm(request, "payroll.add_payslip")
        if blocked:
            return blocked
        row = PayPeriodSettings.objects.entire().filter(pk=pk).first()
        if row is None:
            return Response({"detail": _("Pay period not found.")}, status=404)
        start, end = row.manual_period()
        created = generate_for_setting(row, date.today(), force=True)
        return Response(
            {
                "created": created or 0,
                "period_start": start,
                "period_end": end,
            },
            status=200,
        )


def _review_payload(result):
    rows = []
    for row in result["rows"]:
        rows.append(
            {
                "employee": employee_brief(row["employee"]),
                "contract_id": row["contract"].pk,
                "present": row["present"],
                "paid_leave": row["paid_leave"],
                "unpaid_leave": row["unpaid_leave"],
                "absent": row["absent"],
                "week_off": row["week_off"],
                "holiday": row["holiday"],
                "total_working": row["total_working"],
                "unresolved_conflicts": row["unresolved_conflicts"],
                "paid_days": row["paid_days"],
                "overtime_label": row["overtime_label"],
                "overtime_seconds": row["overtime_seconds"],
                "blocked": row["blocked"],
                "low_paid": row["low_paid"],
                "problems": [
                    {"severity": level, "message": str(message)}
                    for level, message in row["problems"]
                ],
            }
        )
    return {
        "rows": rows,
        "excluded": [
            {"employee": employee_brief(employee), "reason": str(reason)}
            for employee, reason in result["excluded"]
        ],
        "blocked_count": result["blocked_count"],
        "ready_count": result["ready_count"],
        "low_paid_count": result["low_paid_count"],
        "low_paid_threshold": result["low_paid_threshold"],
    }


class PayrollReviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        blocked = require_perm(request, "payroll.add_payslip")
        if blocked:
            return blocked
        start = parse_date(request.data.get("period_start") or request.data.get("start_date"))
        end = parse_date(request.data.get("period_end") or request.data.get("end_date"))
        employee_ids = as_id_list(
            request.data.get("employee_ids") or request.data.get("employee_id")
        )
        errors = {}
        if not start:
            errors["period_start"] = [_("Start date is required.")]
        if not end:
            errors["period_end"] = [_("End date is required.")]
        if start and end and end < start:
            errors["period_end"] = [
                _("The end date must be greater than or equal to the start date.")
            ]
        if not employee_ids:
            errors["employee_ids"] = [_("Select at least one employee.")]
        if errors:
            return Response(errors, status=400)
        employees = list(Employee.objects.filter(pk__in=employee_ids))
        return Response(_review_payload(batch_run.review(employees, start, end)), status=200)


def _line_payload(line):
    return {
        "id": line.pk,
        "employee": employee_brief(line.employee_id),
        "status": line.status,
        "message": line.message,
        "payslip_id": line.payslip_id,
    }


def _batch_payload(batch, include_lines=False):
    data = {
        "id": batch.pk,
        "batch_name": batch.batch_name,
        "period_start": batch.period_start,
        "period_end": batch.period_end,
        "pay_date": batch.pay_date,
        "status": batch.status,
        "status_display": batch.get_status_display(),
        "progress_state": batch.progress_state,
        "percent_complete": batch.percent_complete,
        "employee_count": batch.employee_count,
        "processed_count": batch.processed_count,
        "generated_count": batch.generated_count,
        "failed_count": batch.failed_count,
        "flagged_count": batch.flagged_count,
        "total_gross": batch.total_gross,
        "total_deductions": batch.total_deductions,
        "total_net": batch.total_net,
        "total_employer": batch.total_employer,
        "last_error": batch.last_error,
        "next_statuses": [
            {
                "value": value,
                "label": str(label),
                "allowed": batch.can_transition_to(value)[0],
                "reason": batch.can_transition_to(value)[1],
            }
            for value, label in PayrollBatch.STATUS_CHOICES
            if value != batch.status
            and (
                batch.can_transition_to(value)[0]
                or value in PayrollBatch.ALLOWED_TRANSITIONS[batch.status]
            )
        ],
    }
    if include_lines:
        lines = batch.lines.select_related("employee_id", "payslip")
        data["lines"] = [_line_payload(line) for line in lines]
    return data


def _mirror_payslip_status(batch):
    mirrored = {
        PayrollBatch.DRAFT: "draft",
        PayrollBatch.REVIEW: "review_ongoing",
        PayrollBatch.APPROVED: "confirmed",
        PayrollBatch.PAID: "paid",
        PayrollBatch.CANCELLED: "draft",
    }.get(batch.status)
    if mirrored:
        batch.payslips.update(status=mirrored)


class PayrollBatchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        blocked = require_perm(request, "payroll.view_payslip")
        if blocked:
            return blocked
        if pk:
            batch = PayrollBatch.objects.filter(pk=pk).first()
            if batch is None:
                return Response({"detail": _("Batch not found.")}, status=404)
            batch.refresh_totals()
            batch.refresh_from_db()
            return Response(_batch_payload(batch, include_lines=True), status=200)
        batches = PayrollBatch.objects.all().order_by("-period_end", "-created_at")
        pagination = HorillaPageNumberPagination()
        page = pagination.paginate_queryset(batches, request)
        return pagination.get_paginated_response(
            [_batch_payload(batch) for batch in page]
        )

    def post(self, request):
        blocked = require_perm(request, "payroll.add_payslip")
        if blocked:
            return blocked
        start = parse_date(request.data.get("period_start"))
        end = parse_date(request.data.get("period_end"))
        name = (request.data.get("batch_name") or "").strip()
        employee_ids = as_id_list(request.data.get("employee_ids"))
        errors = {}
        if not name:
            errors["batch_name"] = [_("Batch name is required.")]
        if not start:
            errors["period_start"] = [_("Start date is required.")]
        if not end:
            errors["period_end"] = [_("End date is required.")]
        if start and end and end < start:
            errors["period_end"] = [
                _("The end date must be greater than or equal to the start date.")
            ]
        if not employee_ids:
            errors["employee_ids"] = [_("Select at least one employee.")]
        if errors:
            return Response(errors, status=400)

        # One run per stretch of days. Review only leaves out the people who
        # already have a payslip; a second run for the same dates is refused
        # outright, until the first is reopened or deleted.
        taken = batch_run.overlapping_batches(start, end).first()
        if taken is not None:
            return Response(
                {
                    "detail": _(
                        "%(name)s already covers %(start)s to %(end)s. Reopen or "
                        "delete that run before running these dates again."
                    )
                    % {
                        "name": taken.batch_name,
                        "start": taken.period_start,
                        "end": taken.period_end,
                    },
                    "overlapping_batch_id": taken.pk,
                },
                status=400,
            )

        employees = list(Employee.objects.filter(pk__in=employee_ids))
        reviewed = batch_run.review(employees, start, end)
        ready = [row["employee"] for row in reviewed["rows"] if not row["blocked"]]
        payload = _review_payload(reviewed)
        if not ready:
            payload["detail"] = _("Nobody in this batch can be paid yet.")
            return Response(payload, status=400)
        settings = PayPeriodSettings.for_company(company_for(request))
        batch = batch_run.create_batch(
            name=name,
            start_date=start,
            end_date=end,
            employees=ready,
            user=request.user,
            settings=settings,
        )
        body = _batch_payload(batch, include_lines=True)
        body["review"] = payload
        return Response(body, status=201)

    def delete(self, request, pk):
        blocked = require_perm(request, "payroll.delete_payslip")
        if blocked:
            return blocked
        batch = PayrollBatch.objects.filter(pk=pk).first()
        if batch is None:
            return Response({"detail": _("Batch not found.")}, status=404)
        if batch.status == PayrollBatch.PAID:
            return Response(
                {"detail": _("A paid batch cannot be deleted.")},
                status=400,
            )
        removed = batch.payslips.count()
        with transaction.atomic():
            batch.payslips.all().delete()
            batch.delete()
        return Response({"status": "deleted", "payslips": removed}, status=200)


class PayrollBatchGenerateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        blocked = require_perm(request, "payroll.add_payslip")
        if blocked:
            return blocked
        batch = PayrollBatch.objects.filter(pk=pk).first()
        if batch is None:
            return Response({"detail": _("Batch not found.")}, status=404)
        handled = 0
        if not batch.is_finished:
            try:
                handled = batch_run.generate_slice(batch)
            except Exception as exc:
                batch.progress_state = PayrollBatch.FAILED
                batch.last_error = f"{type(exc).__name__}: {exc}"
                batch.save(update_fields=["progress_state", "last_error"])
        batch.refresh_from_db()
        failed = batch.lines.filter(status=PayrollBatchLine.FAILED).select_related(
            "employee_id"
        )
        body = _batch_payload(batch)
        body["handled"] = handled
        body["failed_lines"] = [_line_payload(line) for line in failed]
        return Response(body, status=200)


class PayrollBatchStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        blocked = require_perm(request, "payroll.change_payslip")
        if blocked:
            return blocked
        batch = PayrollBatch.objects.filter(pk=pk).first()
        if batch is None:
            return Response({"detail": _("Batch not found.")}, status=404)
        wanted = request.data.get("status") or ""
        allowed, reason = batch.can_transition_to(wanted)
        if not allowed:
            return Response({"status": [str(reason)]}, status=400)
        batch.status = wanted
        batch.save(update_fields=["status"])
        _mirror_payslip_status(batch)
        return Response(_batch_payload(batch), status=200)


class PayrollBatchReopenView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        for perm in ("payroll.delete_payslip", "payroll.add_payslip"):
            blocked = require_perm(request, perm)
            if blocked:
                return blocked
        batch = PayrollBatch.objects.filter(pk=pk).first()
        if batch is None:
            return Response({"detail": _("Batch not found.")}, status=404)
        if (
            batch.status != PayrollBatch.DRAFT
            or batch.payslips.exclude(status="draft").exists()
        ):
            return Response(
                {"detail": _("Only a draft batch can be sent back to check its inputs.")},
                status=400,
            )
        state = {
            "batch_name": batch.batch_name,
            "period_start": batch.period_start,
            "period_end": batch.period_end,
            "employee_ids": list(batch.lines.values_list("employee_id_id", flat=True)),
        }
        with transaction.atomic():
            batch.payslips.all().delete()
            batch.delete()
        state["detail"] = _(
            "The draft payslips were discarded. Review the inputs and generate again."
        )
        return Response(state, status=200)
