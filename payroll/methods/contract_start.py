"""
When a contract may start, and the draft contract a new employee gets.

A contract follows the employee's joining date: it may not start before it, and
the one made for a new employee starts on it. That contract is a draft, so pay
is confirmed and the contract activated by someone, never assumed.
"""

from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext as _


def joining_date(employee):
    """The employee's joining date, or None when there is none yet."""
    if employee is None:
        return None
    try:
        work_info = employee.employee_work_info
    except ObjectDoesNotExist:
        return None
    return work_info.date_joining if work_info else None


def _shown(day):
    return f"{day.day} {day:%b %Y}"


def start_before_joining_error(employee, start):
    """The message for a contract starting before the employee joined, else None."""
    joined = joining_date(employee)
    if joined is None or start is None or start >= joined:
        return None
    return _(
        "A contract cannot start before the employee joined on %(date)s."
    ) % {"date": _shown(joined)}


def create_draft_contract(employee, work_info):
    """
    A draft contract starting on the joining date, at the basic salary on file.

    Returns None when there is no joining date yet, or the employee already has
    a contract: the draft is only ever the first one.
    """
    from payroll.models.models import Contract

    if employee is None or work_info is None or work_info.date_joining is None:
        return None
    if Contract.objects.entire().filter(employee_id=employee).exists():
        return None
    return Contract.objects.create(
        contract_name=f"{employee}'s Contract",
        employee_id=employee,
        contract_start_date=work_info.date_joining,
        wage=work_info.basic_salary if work_info.basic_salary is not None else 0,
        contract_status="draft",
    )


def follow_joining_date(employee, previous, joined):
    """
    Move a draft that started on the old joining date to the new one.

    Only drafts: an active contract has been confirmed, and moving its start
    would change what has been, or will be, paid.
    """
    from payroll.models.models import Contract

    if employee is None or previous is None or joined is None or previous == joined:
        return 0
    moved = 0
    drafts = Contract.objects.entire().filter(
        employee_id=employee, contract_status="draft", contract_start_date=previous
    )
    for contract in drafts:
        if contract.contract_end_date and contract.contract_end_date < joined:
            continue
        contract.contract_start_date = joined
        contract.save()
        moved += 1
    return moved
