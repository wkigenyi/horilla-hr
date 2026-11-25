"""
Which contracts do not start on the employee's joining date, and why.

New employees used to get a contract the moment they were saved, before their
joining date or salary was filled in: active, dated the day they were added, at
a wage of 0. Contracts now start on the joining date, as drafts, and may not
start before it. This lists what was made the old way, plus any contract that
starts before the employee joined, so each can be put right by someone who
knows the real dates and pay.

It only reads. Pass --csv to write the list to a file as well.
"""

import csv

from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand

from payroll.models.models import Contract

COLUMNS = [
    "contract_id",
    "badge_id",
    "employee",
    "company",
    "contract",
    "status",
    "start_date",
    "joining_date",
    "wage",
    "wage_type",
    "payslips",
    "problems",
]


def _work_info(employee):
    try:
        return employee.employee_work_info
    except ObjectDoesNotExist:
        return None


def problems_for(contract):
    """What is wrong with this contract's start, as short phrases; empty when nothing is."""
    employee = contract.employee_id
    work = _work_info(employee) if employee else None
    joined = work.date_joining if work else None
    automatic = contract.contract_name == f"{employee}'s Contract"
    found = []
    if joined is None:
        found.append("employee has no joining date")
    elif contract.contract_start_date < joined:
        found.append("starts before the joining date")
    elif automatic and contract.contract_start_date != joined:
        found.append("made automatically, not on the joining date")
    if automatic and not contract.wage and contract.wage_type != "task":
        found.append("made automatically with a wage of 0")
    return found


class Command(BaseCommand):
    help = "List contracts that do not start on the employee's joining date."

    def add_arguments(self, parser):
        parser.add_argument("--csv", help="Also write the list to this CSV file.")

    def handle(self, *args, **options):
        contracts = (
            Contract.objects.entire()
            .select_related("employee_id__employee_work_info__company_id")
            .order_by("employee_id__employee_first_name", "employee_id__badge_id", "id")
        )
        rows = []
        for contract in contracts:
            found = problems_for(contract)
            if not found:
                continue
            employee = contract.employee_id
            work = _work_info(employee) if employee else None
            rows.append(
                {
                    "contract_id": contract.pk,
                    "badge_id": getattr(employee, "badge_id", "") or "",
                    "employee": employee.get_full_name() if employee else "",
                    "company": str(work.company_id) if work and work.company_id else "",
                    "contract": contract.contract_name,
                    "status": contract.contract_status,
                    "start_date": contract.contract_start_date.isoformat(),
                    "joining_date": (
                        work.date_joining.isoformat() if work and work.date_joining else ""
                    ),
                    "wage": contract.wage,
                    "wage_type": contract.wage_type,
                    "payslips": contract.employee_id.payslip_set.filter(
                        start_date__gte=contract.contract_start_date
                    ).count()
                    if employee
                    else 0,
                    "problems": "; ".join(found),
                }
            )

        total = contracts.count()
        if not rows:
            self.stdout.write(
                self.style.SUCCESS(f"All {total} contracts start on or after the joining date.")
            )
            return

        people = len({row["badge_id"] or row["employee"] for row in rows})
        self.stdout.write(f"{len(rows)} of {total} contracts, for {people} employees:")
        self.stdout.write("")
        for row in rows:
            self.stdout.write(
                f"  #{row['contract_id']}  {row['employee']} ({row['badge_id'] or 'no badge'})"
                f"  {row['company'] or 'no company'}  {row['status']}"
                f"  start {row['start_date']}  joined {row['joining_date'] or '—'}"
                f"  wage {row['wage']:g}  payslips {row['payslips']}"
                f"  — {row['problems']}"
            )
        counts = {}
        for row in rows:
            for problem in row["problems"].split("; "):
                counts[problem] = counts.get(problem, 0) + 1
        self.stdout.write("")
        for problem, count in sorted(counts.items(), key=lambda item: -item[1]):
            self.stdout.write(f"  {count:>5}  {problem}")

        if options.get("csv"):
            with open(options["csv"], "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            self.stdout.write("")
            self.stdout.write(f"Written to {options['csv']}.")
