"""Pay periods as records: the open one, closing it, opening the next."""

from datetime import date

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from payroll.models.pay_period import PayPeriod

from .common import company_for, parse_date, require_perm, validation_response


def _who(user):
    if user is None:
        return None
    employee = getattr(user, "employee_get", None)
    name = employee.get_full_name() if employee else ""
    return name or user.get_username()


def period_payload(period, detail=False):
    refusal = period.reopen_refusal() if period.status == PayPeriod.CLOSED else None
    body = {
        "id": period.pk,
        "company_id": period.company_id_id,
        "company": period.company_id.company,
        "start_date": period.start_date,
        "end_date": period.end_date,
        "status": period.status,
        "closed_on": period.closed_on,
        "closed_by": _who(period.closed_by),
        "reopened_on": period.reopened_on,
        "reopened_by": _who(period.reopened_by),
        "can_reopen": period.status == PayPeriod.CLOSED and refusal is None,
        "reopen_refusal": str(refusal) if refusal else None,
    }
    if detail and period.status == PayPeriod.OPEN:
        body["blockers"] = period.close_blockers()
        body["warnings"] = period.close_warnings()
    return body


def _overview(company):
    periods = list(
        PayPeriod.of(company).select_related("company_id", "closed_by", "reopened_by")
    )
    current = PayPeriod.current(company)
    start, end, follows = PayPeriod.suggest_next(company, date.today())
    return {
        "company_id": company.pk,
        "company": company.company,
        "current": period_payload(current, detail=True) if current else None,
        "can_open": current is None,
        "suggested": {"start_date": start, "end_date": end, "start_fixed": follows},
        "periods": [period_payload(period) for period in periods],
    }


def _no_company():
    return Response(
        {"detail": _("Choose a company to see its pay periods.")}, status=400
    )


class PayPeriodsView(APIView):
    """List a company's periods, and open the next one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_payperiod")
        if blocked:
            return blocked
        company = company_for(request)
        if company is None:
            return _no_company()
        return Response(_overview(company), status=200)

    def post(self, request):
        blocked = require_perm(request, "payroll.add_payperiod")
        if blocked:
            return blocked
        company = company_for(request)
        if company is None:
            return _no_company()
        suggested_start, suggested_end, _follows = PayPeriod.suggest_next(
            company, date.today()
        )
        try:
            start = parse_date(request.data.get("start_date")) or suggested_start
            end = parse_date(request.data.get("end_date")) or suggested_end
        except ValueError:
            return Response({"end_date": ["Enter a valid date."]}, status=400)
        try:
            PayPeriod.open_next(company, start, end, user=request.user)
        except DjangoValidationError as exc:
            return validation_response(exc)
        return Response(_overview(company), status=201)


class PayPeriodActionView(APIView):
    """Close or reopen one period."""

    permission_classes = [IsAuthenticated]
    action = None

    def post(self, request, pk):
        perm = (
            "payroll.change_payperiod"
            if self.action == "close"
            else "payroll.reopen_payperiod"
        )
        blocked = require_perm(request, perm)
        if blocked:
            return blocked
        company = company_for(request)
        period = (
            PayPeriod.of(company).filter(pk=pk).first() if company is not None else None
        )
        if period is None:
            return Response({"detail": _("Pay period not found.")}, status=404)
        try:
            if self.action == "close":
                period.close(user=request.user)
            else:
                period.reopen(user=request.user)
        except DjangoValidationError as exc:
            return validation_response(exc)
        return Response(_overview(company), status=200)
