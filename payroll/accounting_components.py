"""
Payroll figures that accounting needs when a company pays staff.

Horilla does not keep a chart of accounts or post journals. It computes payroll;
the books consume exported figures later. This module locks the v1 catalog of
reportable lines and how each line is meant to hit the books. GL codes and the
import file are a later step.

Agreement (v1):

* Earnings: basic + rolled allowances (+ arrears separate); not every allowance title
* Income tax: always its own line from ``federal_tax``
* Statutory contributions: one employee line and one employer line per component
* Other employee deductions: single bucket unless remittance-backed
* Net pay: always its own settlement line
* Loans, advances, reimbursements, recoveries: kept off wage expense
* Loss of pay: reduction of wage expense, not a third-party liability
* Summary grain: department × catalog line (no department → Unassigned)
"""

from django.utils.translation import gettext_lazy as _

# How the line should be thought of when someone later assigns a GL code.
CATEGORY_EARNING = "earning"
CATEGORY_WITHHOLDING = "withholding"
CATEGORY_EMPLOYER = "employer_burden"
CATEGORY_SETTLEMENT = "settlement"
CATEGORY_BALANCE_SHEET = "balance_sheet"
CATEGORY_FLAG = "flag"

# Debit / credit hint for a future journal export (not posted here).
NATURE_EXPENSE = "expense"
NATURE_LIABILITY = "liability"
NATURE_ASSET = "asset"
NATURE_SETTLEMENT = "settlement"
NATURE_CONTRA_EXPENSE = "contra_expense"
NATURE_FLAG = "flag"

# Fixed catalog keys (not tied to a configurable Allowance/Deduction id).
BASIC_PAY = "basic_pay"
TAXABLE_ALLOWANCES = "taxable_allowances"
NON_TAXABLE_ALLOWANCES = "non_taxable_allowances"
ARREARS = "arrears"
INCOME_TAX = "income_tax"
OTHER_DEDUCTIONS = "other_deductions"
LOSS_OF_PAY = "loss_of_pay"
NET_PAY = "net_pay"
UNCOVERED_DEDUCTION = "uncovered_deduction"
LOAN_PAYOUT = "loan_payout"
ADVANCE_PAYOUT = "advance_payout"
LOAN_REPAYMENT = "loan_repayment"
ADVANCE_REPAYMENT = "advance_repayment"
FINE = "fine"
PENALTY = "penalty"
REIMBURSEMENT = "reimbursement"
RECOVERY = "recovery"

# Prefixes for per-component contribution lines: ``contribution_employee:12``.
CONTRIBUTION_EMPLOYEE_PREFIX = "contribution_employee:"
CONTRIBUTION_EMPLOYER_PREFIX = "contribution_employer:"

# Generated earning kinds pulled out of the rolled allowances buckets.
SPECIAL_EARNING_KEYS = {
    "arrears": ARREARS,
    "loan_payout": LOAN_PAYOUT,
    "advance_payout": ADVANCE_PAYOUT,
    "reimbursement": REIMBURSEMENT,
}

# Generated deduction kinds pulled out of "other deductions".
SPECIAL_DEDUCTION_KEYS = {
    "loan_repayment": LOAN_REPAYMENT,
    "advance_repayment": ADVANCE_REPAYMENT,
    "fine": FINE,
    "penalty": PENALTY,
    "recovery": RECOVERY,
}

CATALOG = (
    {
        "key": BASIC_PAY,
        "title": _("Basic pay"),
        "category": CATEGORY_EARNING,
        "nature": NATURE_EXPENSE,
        "posting": True,
    },
    {
        "key": TAXABLE_ALLOWANCES,
        "title": _("Taxable allowances"),
        "category": CATEGORY_EARNING,
        "nature": NATURE_EXPENSE,
        "posting": True,
    },
    {
        "key": NON_TAXABLE_ALLOWANCES,
        "title": _("Non-taxable allowances"),
        "category": CATEGORY_EARNING,
        "nature": NATURE_EXPENSE,
        "posting": True,
    },
    {
        "key": ARREARS,
        "title": _("Arrears"),
        "category": CATEGORY_EARNING,
        "nature": NATURE_EXPENSE,
        "posting": True,
    },
    {
        "key": INCOME_TAX,
        "title": _("Income tax"),
        "category": CATEGORY_WITHHOLDING,
        "nature": NATURE_LIABILITY,
        "posting": True,
    },
    {
        "key": OTHER_DEDUCTIONS,
        "title": _("Other deductions"),
        "category": CATEGORY_WITHHOLDING,
        "nature": NATURE_LIABILITY,
        "posting": True,
    },
    {
        "key": LOSS_OF_PAY,
        "title": _("Loss of pay"),
        "category": CATEGORY_EARNING,
        "nature": NATURE_CONTRA_EXPENSE,
        "posting": True,
    },
    {
        "key": NET_PAY,
        "title": _("Net pay"),
        "category": CATEGORY_SETTLEMENT,
        "nature": NATURE_SETTLEMENT,
        "posting": True,
    },
    {
        "key": UNCOVERED_DEDUCTION,
        "title": _("Uncovered deduction"),
        "category": CATEGORY_FLAG,
        "nature": NATURE_FLAG,
        "posting": False,
    },
    {
        "key": LOAN_PAYOUT,
        "title": _("Loan payout"),
        "category": CATEGORY_BALANCE_SHEET,
        "nature": NATURE_ASSET,
        "posting": True,
    },
    {
        "key": ADVANCE_PAYOUT,
        "title": _("Salary advance payout"),
        "category": CATEGORY_BALANCE_SHEET,
        "nature": NATURE_ASSET,
        "posting": True,
    },
    {
        "key": LOAN_REPAYMENT,
        "title": _("Loan repayment"),
        "category": CATEGORY_BALANCE_SHEET,
        "nature": NATURE_ASSET,
        "posting": True,
    },
    {
        "key": ADVANCE_REPAYMENT,
        "title": _("Salary advance repayment"),
        "category": CATEGORY_BALANCE_SHEET,
        "nature": NATURE_ASSET,
        "posting": True,
    },
    {
        "key": FINE,
        "title": _("Fine"),
        "category": CATEGORY_BALANCE_SHEET,
        "nature": NATURE_LIABILITY,
        "posting": True,
    },
    {
        "key": PENALTY,
        "title": _("Attendance penalty"),
        "category": CATEGORY_BALANCE_SHEET,
        "nature": NATURE_LIABILITY,
        "posting": True,
    },
    {
        "key": REIMBURSEMENT,
        "title": _("Reimbursement"),
        "category": CATEGORY_BALANCE_SHEET,
        "nature": NATURE_EXPENSE,
        "posting": True,
    },
    {
        "key": RECOVERY,
        "title": _("Recovery"),
        "category": CATEGORY_BALANCE_SHEET,
        "nature": NATURE_ASSET,
        "posting": True,
    },
)

BY_KEY = {entry["key"]: entry for entry in CATALOG}


def contribution_employee_key(component_id):
    return f"{CONTRIBUTION_EMPLOYEE_PREFIX}{component_id}"


def contribution_employer_key(component_id):
    return f"{CONTRIBUTION_EMPLOYER_PREFIX}{component_id}"


def is_contribution_key(key):
    return key.startswith(CONTRIBUTION_EMPLOYEE_PREFIX) or key.startswith(
        CONTRIBUTION_EMPLOYER_PREFIX
    )


def catalog_entry(key, title=None):
    """
    Fixed catalog row for ``key``, or a contribution row synthesised from the key.

    ``title`` is used for per-component contribution lines (the Deduction title).
    """
    if key in BY_KEY:
        return dict(BY_KEY[key])
    if key.startswith(CONTRIBUTION_EMPLOYEE_PREFIX):
        return {
            "key": key,
            "title": title or _("Employee contribution"),
            "category": CATEGORY_WITHHOLDING,
            "nature": NATURE_LIABILITY,
            "posting": True,
        }
    if key.startswith(CONTRIBUTION_EMPLOYER_PREFIX):
        return {
            "key": key,
            "title": title or _("Employer contribution"),
            "category": CATEGORY_EMPLOYER,
            "nature": NATURE_EXPENSE,
            "posting": True,
        }
    return None
