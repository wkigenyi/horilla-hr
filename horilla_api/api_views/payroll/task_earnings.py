"""Post completed payable tasks into draft pay adjustments for a period."""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.utils.translation import gettext as _

from payroll.methods.task_pay import post_task_earnings, preview_task_earnings

from .common import company_for, parse_date, require_perm


def _period_dates(data):
    start = parse_date(data.get("start_date"))
    end = parse_date(data.get("end_date"))
    errors = {}
    if start is None:
        errors["start_date"] = [_("Enter a start date.")]
    if end is None:
        errors["end_date"] = [_("Enter an end date.")]
    if start is not None and end is not None and start > end:
        errors["end_date"] = [_("End date must be on or after the start date.")]
    return start, end, errors


class TaskEarningsPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = require_perm(request, "payroll.view_payadjustment")
        if blocked:
            return blocked
        start, end, errors = _period_dates(request.query_params)
        if errors:
            return Response(errors, status=400)
        return Response(
            preview_task_earnings(start, end, company=company_for(request)),
            status=200,
        )


class TaskEarningsPostView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        blocked = require_perm(request, "payroll.add_payadjustment")
        if blocked:
            return blocked
        start, end, errors = _period_dates(request.data)
        if errors:
            return Response(errors, status=400)
        result = post_task_earnings(start, end, company=company_for(request))
        return Response(result, status=201 if result["created"] else 200)
