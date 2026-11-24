"""Post completed payable tasks into draft pay adjustments for a period."""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.utils.translation import gettext as _

from horilla.horilla_middlewares import get_selected_company
from payroll.methods.task_pay import post_task_earnings, preview_task_earnings

from .common import parse_date, require_perm


def _scope_company():
    """The company whose projects to post, or None for every company in view.

    This is the company the request is scoped to (the switcher for a
    superuser, the work company for everyone else), not the caller's own
    employer: someone running payroll for another company must find that
    company's tasks. The Task manager already limits rows to the same scope,
    so None never reaches further than the caller can see.
    """
    selected = get_selected_company()
    if not selected or selected == "all":
        return None
    return selected


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
            preview_task_earnings(start, end, company=_scope_company()),
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
        result = post_task_earnings(start, end, company=_scope_company())
        return Response(result, status=201 if result["created"] else 200)
