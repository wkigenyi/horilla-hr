"""API error shapes that DRF does not produce by itself."""

from rest_framework.response import Response
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    """
    DRF's handler, plus a 400 for a change refused inside a closed pay period.

    The lock is enforced when the row is saved (payroll/methods/period_lock.py),
    below every view, so the refusal surfaces as a Django ValidationError that
    DRF would otherwise turn into a 500.
    """
    from payroll.methods.period_lock import PeriodClosed

    if isinstance(exc, PeriodClosed):
        return Response(
            {"detail": [str(message) for message in exc.messages]}, status=400
        )
    return exception_handler(exc, context)
