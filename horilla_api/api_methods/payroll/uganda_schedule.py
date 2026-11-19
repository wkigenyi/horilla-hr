"""
Uganda statutory schedule for one payroll month.

One row per employee with what has to be remitted for them: PAYE to URA,
NSSF (employee 5% and employer 10%) to the Fund, and Local Service Tax to the
local authority. Totals for each, and the people whose TIN or NSSF number is
missing, because a return cannot be filed for them as it stands.

Figures are read from the payslips that were issued, never recomputed, for the
same reason the contributions report does it: a remittance has to agree with
the payslips people were paid by.

Columns are data, not code. ``LAYOUTS["summary"]`` is Imara's own layout. The
official URA PAYE e-return and the NSSF contribution schedule have their own
column orders and headings; each becomes another entry in ``LAYOUTS`` (a list
of ``Column``) once the templates are in hand. Nothing here guesses them.
"""

import calendar
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from typing import Callable

# Payslips that count towards a return. Drafts and slips still in review have
# not been issued, so they are left out unless asked for.
DEFAULT_STATUSES = ("confirmed", "paid")
ALL_STATUSES = ("draft", "review_ongoing", "confirmed", "paid")

DEDUCTION_KEYS = (
    "pretax_deductions",
    "post_tax_deductions",
    "tax_deductions",
    "net_deductions",
)


def month_bounds(text):
    """``"2026-11"`` -> (date(2026, 11, 1), date(2026, 11, 30)), or None."""
    try:
        year, month = (int(part) for part in str(text or "").split("-", 1))
        last = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last)
    except (TypeError, ValueError):
        return None


def statutory_components():
    """
    Deduction ids that are NSSF or LST.

    NSSF is recognised by name: it is a percentage like any other, and the
    title is what everyone gives it. LST is the component on the Uganda LST
    bands, or one simply called LST.
    """
    from django.db.models import Q

    from payroll.models.models import Deduction

    every = Deduction.objects.entire()
    nssf = set(every.filter(title__icontains="nssf").values_list("pk", flat=True))
    lst = set(
        every.filter(
            Q(based_on="uganda_lst")
            | Q(title__iexact="lst")
            | Q(title__icontains="local service tax")
        ).values_list("pk", flat=True)
    )
    return nssf, lst


def _lines(data):
    for key in DEDUCTION_KEYS:
        for row in data.get(key) or []:
            if isinstance(row, dict):
                yield row


def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _text(value):
    return (value or "").strip() if isinstance(value, str) else ""


def build_schedule(payslips):
    """
    ``(rows, totals, missing)`` for the payslips given.

    A person paid more than once in the month (weekly or semi-monthly pay) has
    their payslips added together into one row.
    """
    nssf_ids, lst_ids = statutory_components()
    by_employee = OrderedDict()

    for payslip in payslips.order_by(
        "employee_id__employee_first_name", "employee_id__employee_last_name", "pk"
    ):
        data = payslip.pay_head_data if isinstance(payslip.pay_head_data, dict) else {}
        employee = payslip.employee_id
        row = by_employee.get(employee.pk)
        if row is None:
            row = by_employee[employee.pk] = {
                "employee_id": employee.pk,
                "name": employee.get_full_name(),
                "badge_id": _text(getattr(employee, "badge_id", "")),
                "tin": _text(getattr(employee, "tax_id", "")),
                "nssf_number": _text(getattr(employee, "nssf_id", "")),
                "national_id": _text(getattr(employee, "national_id", "")),
                "payslips": 0,
                "gross_pay": 0.0,
                "chargeable_income": 0.0,
                "paye": 0.0,
                "nssf_employee": 0.0,
                "nssf_employer": 0.0,
                "lst": 0.0,
            }
        row["payslips"] += 1
        row["gross_pay"] += _number(payslip.gross_pay or data.get("gross_pay"))
        row["chargeable_income"] += _number(data.get("taxable_gross_pay"))
        # PAYE is the income tax worked out from the filing status. Deductions
        # merely flagged as a tax (a professional tax, say) are not PAYE.
        row["paye"] += _number(data.get("federal_tax"))
        for line in _lines(data):
            component = line.get("deduction_id")
            if component in nssf_ids:
                row["nssf_employee"] += _number(line.get("amount"))
                row["nssf_employer"] += _number(line.get("employer_contribution_amount"))
            elif component in lst_ids:
                row["lst"] += _number(line.get("amount"))

    rows = []
    for row in by_employee.values():
        for key in (
            "gross_pay",
            "chargeable_income",
            "paye",
            "nssf_employee",
            "nssf_employer",
            "lst",
        ):
            row[key] = round(row[key], 2)
        row["nssf_total"] = round(row["nssf_employee"] + row["nssf_employer"], 2)
        row["missing"] = [
            label
            for label, value in (("TIN", row["tin"]), ("NSSF number", row["nssf_number"]))
            if not value
        ]
        rows.append(row)

    def total(key):
        return round(sum(row[key] for row in rows), 2)

    totals = {
        "employees": len(rows),
        "payslips": sum(row["payslips"] for row in rows),
        "gross_pay": total("gross_pay"),
        "chargeable_income": total("chargeable_income"),
        "paye": total("paye"),
        "nssf_employee": total("nssf_employee"),
        "nssf_employer": total("nssf_employer"),
        "nssf_total": total("nssf_total"),
        "lst": total("lst"),
    }
    missing = {
        "tin": [row["employee_id"] for row in rows if not row["tin"]],
        "nssf_number": [row["employee_id"] for row in rows if not row["nssf_number"]],
    }
    return rows, totals, missing


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    value: Callable[[dict], object]
    money: bool = False


def _get(key):
    return lambda row: row.get(key)


# Imara's own layout. Official templates go alongside it as further entries.
LAYOUTS = {
    "summary": [
        Column("name", "Employee", _get("name")),
        Column("badge_id", "Employee number", _get("badge_id")),
        Column("tin", "TIN", _get("tin")),
        Column("nssf_number", "NSSF number", _get("nssf_number")),
        Column("national_id", "National ID", _get("national_id")),
        Column("gross_pay", "Gross pay", _get("gross_pay"), money=True),
        Column(
            "chargeable_income", "Chargeable income", _get("chargeable_income"), money=True
        ),
        Column("paye", "PAYE", _get("paye"), money=True),
        Column("nssf_employee", "NSSF employee (5%)", _get("nssf_employee"), money=True),
        Column("nssf_employer", "NSSF employer (10%)", _get("nssf_employer"), money=True),
        Column("nssf_total", "NSSF total", _get("nssf_total"), money=True),
        Column("lst", "LST", _get("lst"), money=True),
        Column("missing", "Missing", lambda row: ", ".join(row.get("missing") or [])),
    ],
}


def table(rows, totals, layout="summary"):
    """Header row, data rows, and a totals row, for CSV or a spreadsheet."""
    columns = LAYOUTS[layout]
    header = [column.header for column in columns]
    body = [[column.value(row) for column in columns] for row in rows]
    footer = [
        (
            "Total"
            if index == 0
            else (totals.get(column.key) if column.money else "")
        )
        for index, column in enumerate(columns)
    ]
    return header, body, footer, columns
