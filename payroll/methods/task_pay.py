"""
Post completed payable Horilla Tasks into draft Pay Adjustments for a period.

Each TaskPayAllocation is that participant's amount — no splitting. Posting
never confirms adjustments; HR reviews drafts, then uses the normal confirm
flow.
"""

from collections import defaultdict

from django.db import transaction
from django.db.models import Prefetch
from django.utils.translation import gettext as _

from payroll.models.models import PayAdjustment


def _eligible_tasks(start_date, end_date, company=None):
    from project.models import Task, TaskPayAllocation

    allocations = TaskPayAllocation.objects.filter(amount__gt=0).select_related(
        "employee"
    )
    queryset = (
        Task.objects.filter(
            is_payable=True,
            status="completed",
            completed_at__gte=start_date,
            completed_at__lte=end_date,
            payroll_adjustment__isnull=True,
        )
        .select_related("project")
        .prefetch_related(Prefetch("pay_allocations", queryset=allocations))
        .order_by("completed_at", "pk")
    )
    if company is not None:
        queryset = queryset.filter(project__company_id=company)
    return queryset


def _aggregate(start_date, end_date, company=None):
    """
    Build per-employee rows and skip notes for the period.

    Each row: employee, amount, task_ids, titles.
    """
    by_employee = defaultdict(
        lambda: {"amount": 0.0, "task_ids": [], "titles": [], "employee": None}
    )
    skips = []

    for task in _eligible_tasks(start_date, end_date, company=company):
        rows = [row for row in task.pay_allocations.all() if row.amount and row.amount > 0]
        if not rows:
            skips.append(
                {
                    "task_id": task.pk,
                    "title": task.title,
                    "reason": _("No participant pay amounts."),
                }
            )
            continue
        for allocation in rows:
            employee = allocation.employee
            row = by_employee[employee.pk]
            row["employee"] = employee
            row["amount"] = round(row["amount"] + float(allocation.amount), 2)
            row["task_ids"].append(task.pk)
            if task.title not in row["titles"]:
                row["titles"].append(task.title)

    rows = sorted(
        by_employee.values(),
        key=lambda row: (row["employee"].get_full_name().lower(), row["employee"].pk),
    )
    return rows, skips


def preview_task_earnings(start_date, end_date, company=None):
    """Preview aggregates and skips for a pay period. Writes nothing."""
    rows, skips = _aggregate(start_date, end_date, company=company)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "employees": [
            {
                "employee_id": row["employee"].pk,
                "employee_name": row["employee"].get_full_name(),
                "badge_id": getattr(row["employee"], "badge_id", None),
                "amount": row["amount"],
                "task_ids": row["task_ids"],
                "titles": row["titles"],
                "month_closed": PayAdjustment._month_has_payslip(
                    row["employee"], end_date
                ),
            }
            for row in rows
        ],
        "skips": skips,
    }


def post_task_earnings(start_date, end_date, company=None):
    """
    Create one draft arrears PayAdjustment per employee and link the tasks.

    Employees whose pay month is already closed are skipped. Returns
    ``{created, skips, employees_skipped}``.
    """
    rows, skips = _aggregate(start_date, end_date, company=company)
    created = []
    employees_skipped = []
    title = _("Task earnings %(start)s–%(end)s") % {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
    }

    with transaction.atomic():
        for row in rows:
            employee = row["employee"]
            if PayAdjustment._month_has_payslip(employee, end_date):
                employees_skipped.append(
                    {
                        "employee_id": employee.pk,
                        "employee_name": employee.get_full_name(),
                        "reason": _("A payslip already exists for this month."),
                        "task_ids": row["task_ids"],
                        "amount": row["amount"],
                    }
                )
                continue
            if row["amount"] <= 0:
                continue
            reason = "; ".join(row["titles"])
            entry = PayAdjustment(
                employee_id=employee,
                kind="arrears",
                title=title[:100],
                reason=reason,
                amount=row["amount"],
                pay_date=end_date,
                status="draft",
            )
            entry.full_clean()
            entry.save()
            from project.models import Task

            Task.objects.filter(pk__in=row["task_ids"]).update(
                payroll_adjustment=entry
            )
            created.append(
                {
                    "id": entry.pk,
                    "employee_id": employee.pk,
                    "employee_name": employee.get_full_name(),
                    "amount": entry.amount,
                    "task_ids": row["task_ids"],
                }
            )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "created": created,
        "skips": skips,
        "employees_skipped": employees_skipped,
    }


def unlink_tasks_for_adjustment(adjustment):
    """Clear Task.payroll_adjustment for tasks linked to this entry."""
    from project.models import Task

    Task.objects.filter(payroll_adjustment=adjustment).update(payroll_adjustment=None)
