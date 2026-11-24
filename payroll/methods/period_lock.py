"""
What a closed pay period locks.

Closing a period is a statement that its pay is settled. Anything that would
change what that pay should have been is refused afterwards, at the model
(``pre_save`` / ``pre_delete``) rather than in each view, so the classic
screens, the API, imports and scheduled jobs all meet the same rule:

- payroll runs and payslips for those dates (new ones, deleting, and moving a
  run's status)
- arrears and recovery entries paid in it
- payable tasks completed in it, and their participants' amounts
- attendance on those days
- leave that touches those days

Only *closed* periods lock. Days after the open period, or before a company's
first period, are free: attendance does not stop because nobody has opened the
next period yet.

Reopening the period (``PayPeriod.reopen``) is the way to make a correction.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete, pre_save
from django.utils.translation import gettext as _

_suspended = ContextVar("pay_period_lock_suspended", default=False)


class PeriodClosed(ValidationError):
    """A change refused because its date is inside a closed pay period."""


@contextmanager
def suspended():
    """Data repair and migrations only: let saves through regardless of period."""
    token = _suspended.set(True)
    try:
        yield
    finally:
        _suspended.reset(token)


def locked_period(company, start, end=None):
    from payroll.models.pay_period import PayPeriod

    if _suspended.get() or company is None or start is None:
        return None
    return PayPeriod.closed_covering(company, start, end)


def refuse_if_closed(company, start, end=None, what=None):
    period = locked_period(company, start, end)
    if period is None:
        return
    raise PeriodClosed(
        _(
            "%(what)s falls in the pay period %(start)s to %(end)s, which is closed. "
            "Reopen the period to change it."
        )
        % {
            "what": what or _("This"),
            "start": period.start_date,
            "end": period.end_date,
        }
    )


def _employee_company(employee):
    if employee is None:
        return None
    from employee.models import EmployeeWorkInformation

    return (
        EmployeeWorkInformation._base_manager.filter(
            employee_id=getattr(employee, "pk", employee)
        )
        .values_list("company_id", flat=True)
        .first()
    )


def _stored(instance, *fields):
    """The saved row's values, or None for a new record."""
    if not instance.pk:
        return None
    return (
        type(instance)._base_manager.filter(pk=instance.pk).values(*fields).first()
    )


# ---- arrears and recovery ----
def _adjustment_saved(sender, instance, **kwargs):
    company = _employee_company(instance.employee_id_id)
    before = _stored(instance, "pay_date")
    what = _("This arrears or recovery entry")
    if before:
        refuse_if_closed(company, before["pay_date"], what=what)
    refuse_if_closed(company, instance.pay_date, what=what)


def _adjustment_deleted(sender, instance, **kwargs):
    refuse_if_closed(
        _employee_company(instance.employee_id_id),
        instance.pay_date,
        what=_("This arrears or recovery entry"),
    )


# ---- attendance ----
def _attendance_saved(sender, instance, **kwargs):
    company = _employee_company(instance.employee_id_id)
    before = _stored(instance, "attendance_date")
    what = _("This attendance")
    if before:
        refuse_if_closed(company, before["attendance_date"], what=what)
    refuse_if_closed(company, instance.attendance_date, what=what)


def _attendance_deleted(sender, instance, **kwargs):
    refuse_if_closed(
        _employee_company(instance.employee_id_id),
        instance.attendance_date,
        what=_("This attendance"),
    )


# ---- leave ----
def _leave_saved(sender, instance, **kwargs):
    company = _employee_company(instance.employee_id_id)
    before = _stored(instance, "start_date", "end_date")
    what = _("This leave")
    if before:
        refuse_if_closed(
            company, before["start_date"], before["end_date"], what=what
        )
    refuse_if_closed(company, instance.start_date, instance.end_date, what=what)


def _leave_deleted(sender, instance, **kwargs):
    refuse_if_closed(
        _employee_company(instance.employee_id_id),
        instance.start_date,
        instance.end_date,
        what=_("This leave"),
    )


# ---- payslips: making and removing them; a paid slip's own flags may still change ----
def _payslip_saved(sender, instance, **kwargs):
    if instance.pk:
        return
    refuse_if_closed(
        _employee_company(instance.employee_id_id),
        instance.start_date,
        instance.end_date,
        what=_("This payslip"),
    )


def _payslip_deleted(sender, instance, **kwargs):
    refuse_if_closed(
        _employee_company(instance.employee_id_id),
        instance.start_date,
        instance.end_date,
        what=_("This payslip"),
    )


# ---- payroll runs: starting one, deleting one, or moving its status ----
def _batch_saved(sender, instance, **kwargs):
    before = _stored(instance, "status")
    if before and before["status"] == instance.status:
        return
    refuse_if_closed(
        instance.company_id_id,
        instance.period_start,
        instance.period_end,
        what=_("This payroll run"),
    )


def _batch_deleted(sender, instance, **kwargs):
    refuse_if_closed(
        instance.company_id_id,
        instance.period_start,
        instance.period_end,
        what=_("This payroll run"),
    )


# ---- payable tasks ----
def _task_company(task):
    from project.models import Project

    return (
        Project._base_manager.filter(pk=task.project_id)
        .values_list("company_id", flat=True)
        .first()
    )


def _task_saved(sender, instance, **kwargs):
    before = _stored(instance, "status", "completed_at", "is_payable")
    after = {
        "status": instance.status,
        "completed_at": instance.completed_at,
        "is_payable": instance.is_payable,
    }
    if before == after:
        return
    company = _task_company(instance)
    what = _("This task's completion")
    if before and before["is_payable"]:
        refuse_if_closed(company, before["completed_at"], what=what)
    if instance.is_payable:
        refuse_if_closed(company, instance.completed_at, what=what)


def _task_deleted(sender, instance, **kwargs):
    if instance.is_payable:
        refuse_if_closed(
            _task_company(instance),
            instance.completed_at,
            what=_("This task's completion"),
        )


def _refuse_task_pay(task_id):
    """Judge by the task as saved, not by an instance someone may have edited."""
    from project.models import Project, Task

    task = (
        Task._base_manager.filter(pk=task_id)
        .values("is_payable", "completed_at", "project_id")
        .first()
    )
    if not task or not task["is_payable"]:
        return
    company = (
        Project._base_manager.filter(pk=task["project_id"])
        .values_list("company_id", flat=True)
        .first()
    )
    refuse_if_closed(company, task["completed_at"], what=_("This task's pay"))


def _task_pay_changed(sender, instance, **kwargs):
    before = _stored(instance, "amount", "employee_id")
    if before and (before["amount"], before["employee_id"]) == (
        instance.amount,
        instance.employee_id,
    ):
        return
    _refuse_task_pay(instance.task_id)


def _task_pay_deleted(sender, instance, **kwargs):
    _refuse_task_pay(instance.task_id)


def connect():
    """Wire the guards. Called once, from the payroll app's ``ready()``."""
    from django.apps import apps

    from payroll.models.models import PayAdjustment, Payslip
    from payroll.models.payroll_batch import PayrollBatch

    guards = [
        (PayAdjustment, _adjustment_saved, _adjustment_deleted),
        (Payslip, _payslip_saved, _payslip_deleted),
        (PayrollBatch, _batch_saved, _batch_deleted),
    ]
    optional = [
        ("attendance", "Attendance", _attendance_saved, _attendance_deleted),
        ("leave", "LeaveRequest", _leave_saved, _leave_deleted),
        ("project", "Task", _task_saved, _task_deleted),
        ("project", "TaskPayAllocation", _task_pay_changed, _task_pay_deleted),
    ]
    for app_label, name, on_save, on_delete in optional:
        if apps.is_installed(app_label):
            guards.append((apps.get_model(app_label, name), on_save, on_delete))
    for model, on_save, on_delete in guards:
        uid = f"pay_period_lock_{model._meta.label_lower}"
        pre_save.connect(on_save, sender=model, dispatch_uid=f"{uid}_save")
        pre_delete.connect(on_delete, sender=model, dispatch_uid=f"{uid}_delete")
