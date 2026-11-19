"""
payroll/methods/local_service_tax.py

Uganda Local Service Tax, worked out per payslip.

LST is an annual amount set by the employee's monthly income band, collected
in four equal instalments in the first four months of the financial year
(July to October). It is allowable for PAYE, so the component that uses this
strategy is a pre-tax deduction.

    monthly gross pay -> band -> annual LST -> / 4 -> one instalment per
    collection month in the pay period

A collection month counts when the pay period reaches its last day, so a
monthly run charges once a month and a weekly run charges only in the week
that closes the month. Someone who joins in September is therefore charged
for September and October only.

The band is read from the period's gross pay. For a monthly run that is the
month's gross; a shorter run uses its own, smaller, gross.

Two things on the employee's contract stop it: an exemption (the forces,
police, prisons, diplomats) and a financial year for which LST was already
paid to another employer.
"""

import calendar
from datetime import date, datetime

# (monthly income up to and including, annual LST). ``None`` = and above.
# Local Governments (Amendment) (No. 2) Act, 2008 schedule for employees.
LST_BANDS = [
    (100_000, 0),
    (200_000, 5_000),
    (300_000, 10_000),
    (400_000, 20_000),
    (500_000, 30_000),
    (600_000, 40_000),
    (700_000, 60_000),
    (800_000, 70_000),
    (900_000, 80_000),
    (1_000_000, 90_000),
    (None, 100_000),
]

COLLECTION_MONTHS = (7, 8, 9, 10)
INSTALMENTS = len(COLLECTION_MONTHS)
FY_START_MONTH = 7


def annual_lst(monthly_income):
    income = float(monthly_income or 0)
    for ceiling, amount in LST_BANDS:
        if ceiling is None or income <= ceiling:
            return float(amount)
    return float(LST_BANDS[-1][1])


def instalment(monthly_income):
    return annual_lst(monthly_income) / INSTALMENTS


def financial_year(year, month):
    """The year a Uganda financial year starts in: July 2026 -> 2026."""
    return year if month >= FY_START_MONTH else year - 1


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def collection_months(day_dict):
    """``[(year, month)]`` collection months whose last day this period reaches."""
    months = []
    for row in day_dict or []:
        month, year = row.get("month"), row.get("year")
        if month not in COLLECTION_MONTHS or not year:
            continue
        end = _as_date(row.get("end_date"))
        last_day = calendar.monthrange(int(year), int(month))[1]
        if end is not None and end.day == last_day and end.month == month:
            months.append((int(year), int(month)))
    return months


def contract_for(employee):
    from payroll.methods.contract_periods import forced_contract
    from payroll.models.models import Contract

    if not employee:
        return None
    return (
        forced_contract(employee)
        or Contract.objects.filter(employee_id=employee, contract_status="active").first()
    )


def lst_for_period(employee, gross_pay, day_dict, contract=None):
    """The LST to deduct on one payslip."""
    months = collection_months(day_dict)
    if not months:
        return 0.0
    contract = contract if contract is not None else contract_for(employee)
    if contract is not None:
        if getattr(contract, "lst_exempt", False):
            return 0.0
        paid_fy = getattr(contract, "lst_paid_elsewhere_fy", None)
        months = [(y, m) for y, m in months if financial_year(y, m) != paid_fy]
    return instalment(gross_pay) * len(months)


def calculate_based_on_uganda_lst(*_args, **kwargs):
    """Strategy for ``based_on = "uganda_lst"``; see the module docstring."""
    from payroll.methods.payslip_calc import calculate_gross_pay

    employee = kwargs.get("employee")
    if "total_allowance" in kwargs:
        gross = calculate_gross_pay(**kwargs)["gross_pay"]
    else:
        gross = kwargs.get("gross_pay") or 0
        if isinstance(gross, dict):
            gross = gross.get("gross_pay", 0)

    if employee is None and kwargs.get("start_date") is None:
        # A structure preview has no employee and no real month: show what
        # one collection month (July to October) would take.
        return instalment(gross)
    return lst_for_period(employee, gross, kwargs.get("day_dict"))
