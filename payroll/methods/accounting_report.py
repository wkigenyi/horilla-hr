"""
Roll paid payslip figures into the accounting catalog.

Primary grain is department × catalog line. Employees with no department land
in Unassigned. Reads ``pay_head_data`` the same way remittance reporting does:
the books must agree with what was issued, not with a second calculation. GL
codes are not attached here; that is the next step after this catalog.
"""

from collections import defaultdict

from django.utils.translation import gettext as _

from payroll.accounting_components import (
    ARREARS,
    BASIC_PAY,
    CATALOG,
    INCOME_TAX,
    LOSS_OF_PAY,
    NET_PAY,
    NON_TAXABLE_ALLOWANCES,
    OTHER_DEDUCTIONS,
    PENALTY,
    RECOVERY,
    REIMBURSEMENT,
    SPECIAL_DEDUCTION_KEYS,
    SPECIAL_EARNING_KEYS,
    TAXABLE_ALLOWANCES,
    UNCOVERED_DEDUCTION,
    catalog_entry,
    contribution_employee_key,
    contribution_employer_key,
    is_contribution_key,
)
from payroll.methods.contributions import DEDUCTION_KEYS, contribution_components
from payroll.methods.deductions import LOAN_PAYOUT_KEYS, LOAN_REPAYMENT_KEYS
from payroll.methods.system_sync import REIMBURSEMENT_KEYS

# Compensation-update buckets are withholdings too; remittance reporting skips
# them because they are not remitted as a named contribution.
ALL_DEDUCTION_KEYS = DEDUCTION_KEYS + (
    "basic_pay_deductions",
    "gross_pay_deductions",
)

_CATALOG_ORDER = {entry["key"]: index for index, entry in enumerate(CATALOG)}

UNASSIGNED_DEPARTMENT = "Unassigned"


def _amount(row):
    return float(row.get("amount") or 0)


def _employer_amount(row):
    return float(row.get("employer_contribution_amount") or 0)


def _as_payslip_list(payslips):
    if hasattr(payslips, "select_related"):
        return list(
            payslips.select_related(
                "employee_id__employee_work_info__department_id"
            )
        )
    return list(payslips)


def _department_of(payslip):
    """
    ``(department_id, department_name)`` for the employee on the payslip.

    Missing work info or department becomes Unassigned (``id`` is None).
    """
    employee = getattr(payslip, "employee_id", None)
    work = getattr(employee, "employee_work_info", None) if employee else None
    department = getattr(work, "department_id", None) if work is not None else None
    if department is None:
        return None, _(UNASSIGNED_DEPARTMENT)
    return department.pk, str(department.department)


def _collect_ids(payslips):
    allowance_ids = set()
    deduction_ids = set()
    for payslip in payslips:
        data = payslip.pay_head_data or {}
        if not isinstance(data, dict):
            continue
        for row in data.get("allowances") or []:
            if isinstance(row, dict) and row.get("allowance_id"):
                allowance_ids.add(row["allowance_id"])
        for key in ALL_DEDUCTION_KEYS:
            for row in data.get(key) or []:
                if isinstance(row, dict) and row.get("deduction_id"):
                    deduction_ids.add(row["deduction_id"])
        for pk in payslip.installment_ids.values_list("id", flat=True):
            if pk:
                deduction_ids.add(pk)
    return allowance_ids, deduction_ids


def _owner_classification(allowance_ids, deduction_ids):
    """
    Map generated component ids to catalog keys via their owning records.

    Generated rows do not copy ``system_key``; the LoanAccount / Reimbursement /
    PayAdjustment / PenaltyAccounts owner is the source of truth (same as
    ``system_sync.rows_to_check``).
    """
    from base.models import PenaltyAccounts
    from payroll.models.models import LoanAccount, PayAdjustment, Reimbursement

    allowance_kind = {}
    deduction_kind = {}

    if not allowance_ids and not deduction_ids:
        return allowance_kind, deduction_kind

    if allowance_ids:
        for loan in LoanAccount.objects.entire().filter(
            allowance_id_id__in=allowance_ids
        ):
            key = LOAN_PAYOUT_KEYS.get(loan.type)
            if key and loan.allowance_id_id in allowance_ids:
                allowance_kind[loan.allowance_id_id] = SPECIAL_EARNING_KEYS[key]

        for claim in Reimbursement.objects.entire().filter(
            allowance_id_id__in=allowance_ids, status="approved"
        ):
            # Expense reimbursements stay off wage expense. Leave / bonus
            # encashment stays in rolled taxable allowances.
            if claim.type == "reimbursement" or claim.type not in REIMBURSEMENT_KEYS:
                if claim.allowance_id_id:
                    allowance_kind[claim.allowance_id_id] = REIMBURSEMENT

        for entry in PayAdjustment.objects.entire().filter(
            status="approved", kind="arrears", allowance_id_id__in=allowance_ids
        ):
            allowance_kind[entry.allowance_id_id] = ARREARS

    if deduction_ids:
        for loan in LoanAccount.objects.entire().prefetch_related("deduction_ids"):
            repayment = LOAN_REPAYMENT_KEYS.get(loan.type)
            catalog_key = SPECIAL_DEDUCTION_KEYS.get(repayment)
            if not catalog_key:
                continue
            for deduction_id in loan.deduction_ids.values_list("id", flat=True):
                if deduction_id in deduction_ids:
                    deduction_kind[deduction_id] = catalog_key

        for entry in PayAdjustment.objects.entire().filter(
            status="approved", kind="recovery", deduction_id_id__in=deduction_ids
        ):
            deduction_kind[entry.deduction_id_id] = RECOVERY

        for account in PenaltyAccounts._base_manager.all():
            ids = (account.additional_info or {}).get("deduction_ids") or []
            for deduction_id in ids:
                if deduction_id in deduction_ids:
                    deduction_kind[deduction_id] = PENALTY

    return allowance_kind, deduction_kind


def summarise(payslips):
    """
    One accounting line per department × catalog key (and per contribution
    component), over the payslips given.

    Returns ``(rows, totals)``. ``rows`` skip zero amounts. Contribution
    components appear as an employee-share line and an employer-share line,
    each still split by department. People with no department use Unassigned.
    """
    payslips = _as_payslip_list(payslips)
    allowance_ids, deduction_ids = _collect_ids(payslips)
    allowance_kind, deduction_kind = _owner_classification(
        allowance_ids, deduction_ids
    )
    configured = contribution_components()

    amounts = defaultdict(float)
    titles = {}
    component_ids = {}
    department_names = {}
    company = defaultdict(float)

    def add(department_id, department_name, key, amount):
        if not amount:
            return
        department_names[department_id] = department_name
        amounts[(department_id, key)] += amount

    for payslip in payslips:
        department_id, department_name = _department_of(payslip)
        basic = float(payslip.basic_pay or 0)
        net = float(payslip.net_pay or 0)
        add(department_id, department_name, BASIC_PAY, basic)
        add(department_id, department_name, NET_PAY, net)
        company[BASIC_PAY] += basic
        company[NET_PAY] += net

        data = payslip.pay_head_data or {}
        if not isinstance(data, dict):
            continue

        federal_tax = float(data.get("federal_tax") or 0)
        add(department_id, department_name, INCOME_TAX, federal_tax)
        company[INCOME_TAX] += federal_tax
        add(
            department_id,
            department_name,
            LOSS_OF_PAY,
            float(data.get("loss_of_pay") or 0),
        )
        add(
            department_id,
            department_name,
            UNCOVERED_DEDUCTION,
            float(data.get("uncovered_deduction") or 0),
        )

        for row in data.get("allowances") or []:
            if not isinstance(row, dict):
                continue
            amount = _amount(row)
            if not amount:
                continue
            allowance_id = row.get("allowance_id")
            special = allowance_kind.get(allowance_id) if allowance_id else None
            if special:
                add(department_id, department_name, special, amount)
            elif row.get("is_taxable"):
                add(department_id, department_name, TAXABLE_ALLOWANCES, amount)
            else:
                add(department_id, department_name, NON_TAXABLE_ALLOWANCES, amount)

        for key in ALL_DEDUCTION_KEYS:
            for row in data.get(key) or []:
                if not isinstance(row, dict):
                    continue
                deduction_id = row.get("deduction_id")
                employee = _amount(row)
                employer = _employer_amount(row)
                special = deduction_kind.get(deduction_id) if deduction_id else None

                if special:
                    add(department_id, department_name, special, employee)
                    continue

                is_contribution = deduction_id in configured or employer
                if is_contribution and deduction_id:
                    emp_key = contribution_employee_key(deduction_id)
                    er_key = contribution_employer_key(deduction_id)
                    add(department_id, department_name, emp_key, employee)
                    add(department_id, department_name, er_key, employer)
                    title = row.get("title") or ""
                    component = configured.get(deduction_id)
                    if component is not None:
                        title = component.title
                    titles[emp_key] = title
                    titles[er_key] = title
                    component_ids[emp_key] = deduction_id
                    component_ids[er_key] = deduction_id
                elif employee:
                    add(department_id, department_name, OTHER_DEDUCTIONS, employee)

    rows = []
    for (department_id, key), amount in amounts.items():
        rounded = round(amount, 2)
        if not rounded:
            continue
        entry = catalog_entry(key, title=titles.get(key))
        if entry is None:
            continue
        if key.startswith("contribution_employee:"):
            entry["title"] = _("%(title)s (employee)") % {
                "title": titles.get(key) or entry["title"]
            }
        elif key.startswith("contribution_employer:"):
            entry["title"] = _("%(title)s (employer)") % {
                "title": titles.get(key) or entry["title"]
            }
        row = {
            **entry,
            "amount": rounded,
            "department_id": department_id,
            "department": department_names.get(department_id)
            or _(UNASSIGNED_DEPARTMENT),
        }
        if key in component_ids:
            row["component_id"] = component_ids[key]
        rows.append(row)

    def sort_key(row):
        key = row["key"]
        unassigned = 1 if row["department_id"] is None else 0
        dept_name = str(row["department"])
        if key in _CATALOG_ORDER:
            return (unassigned, dept_name, 0, _CATALOG_ORDER[key], str(row["title"]))
        if key.startswith("contribution_employee:"):
            return (
                unassigned,
                dept_name,
                1,
                row.get("component_id") or 0,
                0,
                str(row["title"]),
            )
        if key.startswith("contribution_employer:"):
            return (
                unassigned,
                dept_name,
                1,
                row.get("component_id") or 0,
                1,
                str(row["title"]),
            )
        return (unassigned, dept_name, 2, 0, 0, str(row["title"]))

    rows.sort(key=sort_key)

    totals = {
        "lines": len(rows),
        "posting_amount": round(
            sum(r["amount"] for r in rows if r.get("posting")), 2
        ),
        "payslips": len(payslips),
        "departments": len(department_names),
        "basic_pay": round(company[BASIC_PAY], 2),
        "net_pay": round(company[NET_PAY], 2),
        "income_tax": round(company[INCOME_TAX], 2),
    }
    return rows, totals


def gl_map_for(company):
    """``{line_key: gl_code}`` for the company, empty dict when company is missing."""
    if company is None:
        return {}
    from payroll.models.accounting_gl import PayrollGLMapping

    return {
        row.line_key: row.gl_code or ""
        for row in PayrollGLMapping.objects.filter(company_id=company)
    }


def gl_labels_for(company):
    """``{line_key: label}`` for the company."""
    if company is None:
        return {}
    from payroll.models.accounting_gl import PayrollGLMapping

    return {
        row.line_key: row.label or ""
        for row in PayrollGLMapping.objects.filter(company_id=company)
    }


def attach_gl_codes(rows, company):
    """
    Set ``gl_code`` on each summary row from the company mapping.

    Unmapped keys get ``""`` so export can still include the amount.
    """
    codes = gl_map_for(company)
    for row in rows:
        row["gl_code"] = codes.get(row["key"], "")
    return rows


def mappable_line_keys(company=None):
    """
    Catalog keys a company can map, as dicts ready for the mapping API.

    Fixed catalog lines plus employee/employer keys for every contribution
    component. ``company`` is accepted for callers; contribution discovery
    uses the same global contribution set as remittance reporting.
    """
    del company  # reserved for company-scoped contribution lists later
    lines = []
    for entry in CATALOG:
        item = dict(entry)
        item["title"] = str(entry["title"])
        item["component_id"] = None
        lines.append(item)

    for component_id, component in sorted(
        contribution_components().items(), key=lambda pair: pair[0]
    ):
        title = component.title
        for key, side_title in (
            (
                contribution_employee_key(component_id),
                _("%(title)s (employee)") % {"title": title},
            ),
            (
                contribution_employer_key(component_id),
                _("%(title)s (employer)") % {"title": title},
            ),
        ):
            entry = catalog_entry(key, title=title)
            lines.append(
                {
                    **entry,
                    "title": side_title,
                    "component_id": component_id,
                }
            )
    return lines


def is_mappable_key(line_key, company=None):
    if not line_key:
        return False
    if any(entry["key"] == line_key for entry in CATALOG):
        return True
    if not is_contribution_key(line_key):
        return False
    allowed = {line["key"] for line in mappable_line_keys(company)}
    return line_key in allowed
