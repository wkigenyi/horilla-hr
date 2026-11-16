"""
Accounting catalog: which payslip figures become reportable book lines.
"""

from datetime import date
from unittest.mock import patch

from django.test import TestCase

from base.models import Department
from horilla.testkit import make_company, make_employee, make_user
from payroll.accounting_components import (
    ARREARS,
    BASIC_PAY,
    CATALOG,
    INCOME_TAX,
    LOAN_REPAYMENT,
    NET_PAY,
    OTHER_DEDUCTIONS,
    REIMBURSEMENT,
    TAXABLE_ALLOWANCES,
    UNCOVERED_DEDUCTION,
    catalog_entry,
    contribution_employee_key,
    contribution_employer_key,
)
from payroll.methods import accounting_report, contributions
from payroll.methods.accounting_report import UNASSIGNED_DEPARTMENT
from payroll.methods.methods import payslip_fields, save_payslip
from payroll.methods.payroll_run import payroll_calculation
from payroll.models.models import (
    Allowance,
    Contract,
    Deduction,
    LoanAccount,
    PayAdjustment,
    Payslip,
    Reimbursement,
)
from payroll.tests.factories_payroll import make_active_contract

START = date(2026, 4, 1)
END = date(2026, 4, 30)

NO_LEAVE = {
    "paid_leave": 0,
    "unpaid_leaves": 0,
    "partial_pay_days": 0,
    "total_leaves": 0,
    "paid_leave_dates": [],
    "unpaid_leave_dates": [],
    "custom_leave_dates": [],
    "custom_leave_breakdown": [],
    "leave_dates": [],
}


class CatalogTests(TestCase):
    def test_every_fixed_line_has_a_posting_flag(self):
        for entry in CATALOG:
            resolved = catalog_entry(entry["key"])
            self.assertEqual(resolved["key"], entry["key"])
            self.assertIn("posting", entry)
            self.assertIn("category", entry)
            self.assertIn("nature", entry)

    def test_uncovered_deduction_is_a_flag_not_a_posting(self):
        entry = catalog_entry(UNCOVERED_DEDUCTION)
        self.assertFalse(entry["posting"])
        self.assertEqual(entry["category"], "flag")

    def test_contribution_keys_are_synthesised(self):
        employee = catalog_entry(contribution_employee_key(9), title="NSSF")
        employer = catalog_entry(contribution_employer_key(9), title="NSSF")
        self.assertEqual(employee["category"], "withholding")
        self.assertEqual(employer["category"], "employer_burden")
        self.assertTrue(employee["posting"])
        self.assertTrue(employer["posting"])


class SummariseFixture(TestCase):
    def setUp(self):
        self.company = make_company("Books Co")
        self.employee = make_employee(
            company=self.company,
            email="books@test.horilla",
            first_name="Ann",
        )
        Contract.objects.filter(employee_id=self.employee).delete()
        make_active_contract(self.employee, wage=30000.0)

    def payslip(self, **fields):
        defaults = dict(
            employee_id=self.employee,
            start_date=START,
            end_date=END,
            basic_pay=20000.0,
            gross_pay=25000.0,
            deduction=5000.0,
            net_pay=20000.0,
            contract_wage=30000.0,
            status="paid",
            pay_head_data={},
        )
        defaults.update(fields)
        return Payslip.objects.create(**defaults)


class HandBuiltSummariseTests(SummariseFixture):
    def test_basic_allowances_tax_and_net(self):
        taxable = Allowance.objects.create(
            title="Housing",
            amount=3000.0,
            is_fixed=True,
            is_taxable=True,
            include_active_employees=True,
        )
        nontax = Allowance.objects.create(
            title="Transport",
            amount=2000.0,
            is_fixed=True,
            is_taxable=False,
            include_active_employees=True,
        )
        ordinary = Deduction.objects.create(
            title="Union",
            amount=200.0,
            is_fixed=True,
            include_active_employees=True,
            is_pretax=False,
            employer_rate=0,
        )
        self.payslip(
            basic_pay=20000.0,
            net_pay=19800.0,
            pay_head_data={
                "federal_tax": 1000.0,
                "loss_of_pay": 0,
                "uncovered_deduction": 50.0,
                "allowances": [
                    {
                        "allowance_id": taxable.pk,
                        "title": "Housing",
                        "is_taxable": True,
                        "amount": 3000.0,
                    },
                    {
                        "allowance_id": nontax.pk,
                        "title": "Transport",
                        "is_taxable": False,
                        "amount": 2000.0,
                    },
                ],
                "post_tax_deductions": [
                    {
                        "deduction_id": ordinary.pk,
                        "title": "Union",
                        "amount": 200.0,
                    }
                ],
            },
        )

        rows, totals = accounting_report.summarise(Payslip.objects.all())
        by_key = {row["key"]: row for row in rows}

        self.assertEqual(by_key[BASIC_PAY]["amount"], 20000.0)
        self.assertEqual(by_key[BASIC_PAY]["department"], UNASSIGNED_DEPARTMENT)
        self.assertIsNone(by_key[BASIC_PAY]["department_id"])
        self.assertEqual(by_key[TAXABLE_ALLOWANCES]["amount"], 3000.0)
        self.assertEqual(by_key["non_taxable_allowances"]["amount"], 2000.0)
        self.assertEqual(by_key[INCOME_TAX]["amount"], 1000.0)
        self.assertEqual(by_key[OTHER_DEDUCTIONS]["amount"], 200.0)
        self.assertEqual(by_key[NET_PAY]["amount"], 19800.0)
        self.assertEqual(by_key[UNCOVERED_DEDUCTION]["amount"], 50.0)
        self.assertFalse(by_key[UNCOVERED_DEDUCTION]["posting"])
        self.assertEqual(totals["payslips"], 1)
        self.assertEqual(totals["departments"], 1)
        self.assertEqual(totals["basic_pay"], 20000.0)
        self.assertEqual(totals["income_tax"], 1000.0)

    def test_arrears_and_reimbursement_are_kept_off_allowances(self):
        arrears = PayAdjustment.objects.create(
            employee_id=self.employee,
            kind="arrears",
            title="Back pay",
            amount=1500.0,
            pay_date=START,
        )
        arrears.approve()

        earning = Allowance.objects.create(
            title="Travel",
            amount=800.0,
            is_fixed=True,
            only_show_under_employee=True,
            include_active_employees=False,
            is_taxable=True,
        )
        earning.specific_employees.add(self.employee)
        # Reimbursement.save() needs a request thread and an attachment; insert
        # the approved owner row the classifier reads without going through save().
        claim = Reimbursement(
            title="Travel",
            employee_id=self.employee,
            allowance_on=START,
            amount=800.0,
            type="reimbursement",
            status="approved",
            description="trip",
            allowance_id=earning,
        )
        Reimbursement.objects.bulk_create([claim])

        ot = Allowance.objects.create(
            title="OT",
            amount=500.0,
            is_fixed=True,
            is_taxable=True,
            include_active_employees=True,
        )

        self.payslip(
            basic_pay=20000.0,
            net_pay=22300.0,
            pay_head_data={
                "allowances": [
                    {
                        "allowance_id": arrears.allowance_id_id,
                        "title": "Back pay",
                        "is_taxable": False,
                        "amount": 1500.0,
                    },
                    {
                        "allowance_id": earning.pk,
                        "title": "Travel",
                        "is_taxable": True,
                        "amount": 800.0,
                    },
                    {
                        "allowance_id": ot.pk,
                        "title": "OT",
                        "is_taxable": True,
                        "amount": 500.0,
                    },
                ],
            },
        )

        rows, _totals = accounting_report.summarise(Payslip.objects.all())
        by_key = {row["key"]: row for row in rows}

        self.assertEqual(by_key[ARREARS]["amount"], 1500.0)
        self.assertEqual(by_key[REIMBURSEMENT]["amount"], 800.0)
        self.assertEqual(by_key[TAXABLE_ALLOWANCES]["amount"], 500.0)

    def test_loan_repayment_is_balance_sheet_not_other_deductions(self):
        loan = LoanAccount.objects.create(
            title="Staff loan",
            employee_id=self.employee,
            type="loan",
            loan_amount=1200.0,
            provided_date=START,
            installments=2,
            installment_start_date=START,
        )
        installment = Deduction.objects.create(
            title="Staff loan - instalment",
            amount=600.0,
            is_fixed=True,
            only_show_under_employee=True,
            is_installment=True,
            include_active_employees=False,
            is_pretax=True,
        )
        installment.specific_employees.add(self.employee)
        loan.deduction_ids.add(installment)

        payslip = self.payslip(
            basic_pay=20000.0,
            net_pay=19400.0,
            pay_head_data={
                "pretax_deductions": [
                    {
                        "deduction_id": installment.pk,
                        "title": installment.title,
                        "amount": 600.0,
                    }
                ],
            },
        )
        payslip.installment_ids.add(installment)

        rows, _totals = accounting_report.summarise(Payslip.objects.all())
        by_key = {row["key"]: row for row in rows}

        self.assertEqual(by_key[LOAN_REPAYMENT]["amount"], 600.0)
        self.assertNotIn(OTHER_DEDUCTIONS, by_key)


class EngineContributionTests(TestCase):
    def setUp(self):
        self.user = make_user("acctadmin", is_superuser=True)
        self.company = make_company("Acct Co")
        make_employee(
            company=self.company, email="acctadmin@test.horilla", user=self.user
        )
        self.employee = make_employee(
            company=self.company,
            email="worker@acct.horilla",
            first_name="Ben",
        )
        Contract.objects.filter(employee_id=self.employee).delete()
        make_active_contract(self.employee, wage=30000.0)

    def test_contribution_splits_employee_and_employer_lines(self):
        Deduction.objects.create(
            title="Provident Fund",
            is_fixed=False,
            based_on="basic_pay",
            rate=12.0,
            employer_rate=12.0,
            include_active_employees=True,
            is_condition_based=False,
            is_pretax=True,
        )
        with patch("payroll.methods.methods.get_leaves", return_value=NO_LEAVE):
            result = payroll_calculation(self.employee, START, END)
            save_payslip(**payslip_fields(result, self.employee, status="paid"))

        rows, totals = accounting_report.summarise(Payslip.objects.all())
        contribution_rows = [
            row for row in rows if str(row["key"]).startswith("contribution_")
        ]
        self.assertEqual(len(contribution_rows), 2)
        by_side = {
            "employee" if "employee" in row["key"] else "employer": row
            for row in contribution_rows
        }
        expected = 30000 * 0.12
        self.assertAlmostEqual(by_side["employee"]["amount"], expected, places=2)
        self.assertAlmostEqual(by_side["employer"]["amount"], expected, places=2)
        self.assertEqual(by_side["employee"]["category"], "withholding")
        self.assertEqual(by_side["employer"]["category"], "employer_burden")
        self.assertEqual(totals["payslips"], 1)

        # Remittance report still sees the same component once with both shares.
        remittance, _ = contributions.summarise(Payslip.objects.all())
        self.assertEqual(len(remittance), 1)
        self.assertAlmostEqual(
            remittance[0]["employee_amount"], by_side["employee"]["amount"], places=2
        )
        self.assertAlmostEqual(
            remittance[0]["employer_amount"], by_side["employer"]["amount"], places=2
        )


class DepartmentGrainTests(TestCase):
    def setUp(self):
        self.company = make_company("Dept Books")
        self.sales = Department.objects.create(department="Sales")
        self.ops = Department.objects.create(department="Ops")
        self.ann = make_employee(
            company=self.company, email="ann-dept@test.horilla", first_name="Ann"
        )
        self.ben = make_employee(
            company=self.company, email="ben-dept@test.horilla", first_name="Ben"
        )
        self.cam = make_employee(
            company=self.company, email="cam-dept@test.horilla", first_name="Cam"
        )
        for employee in (self.ann, self.ben, self.cam):
            Contract.objects.filter(employee_id=employee).delete()
            make_active_contract(employee, wage=30000.0)

        ann_info = self.ann.employee_work_info
        ann_info.department_id = self.sales
        ann_info.save()
        ben_info = self.ben.employee_work_info
        ben_info.department_id = self.ops
        ben_info.save()
        # Cam keeps no department → Unassigned.

    def payslip(self, employee, basic_pay, net_pay, pay_head_data=None):
        return Payslip.objects.create(
            employee_id=employee,
            start_date=START,
            end_date=END,
            basic_pay=basic_pay,
            gross_pay=basic_pay,
            deduction=0,
            net_pay=net_pay,
            contract_wage=30000.0,
            status="paid",
            pay_head_data=pay_head_data or {},
        )

    def test_same_catalog_key_splits_across_departments(self):
        self.payslip(self.ann, basic_pay=10000.0, net_pay=9000.0)
        self.payslip(self.ben, basic_pay=15000.0, net_pay=14000.0)

        rows, totals = accounting_report.summarise(Payslip.objects.all())
        basic_rows = [row for row in rows if row["key"] == BASIC_PAY]
        by_dept = {row["department"]: row for row in basic_rows}

        self.assertEqual(len(basic_rows), 2)
        self.assertEqual(by_dept["Sales"]["amount"], 10000.0)
        self.assertEqual(by_dept["Sales"]["department_id"], self.sales.pk)
        self.assertEqual(by_dept["Ops"]["amount"], 15000.0)
        self.assertEqual(by_dept["Ops"]["department_id"], self.ops.pk)
        self.assertEqual(totals["basic_pay"], 25000.0)
        self.assertEqual(totals["net_pay"], 23000.0)
        self.assertEqual(totals["departments"], 2)

    def test_missing_department_is_unassigned(self):
        self.payslip(self.cam, basic_pay=8000.0, net_pay=7000.0)

        rows, totals = accounting_report.summarise(Payslip.objects.all())
        basic = next(row for row in rows if row["key"] == BASIC_PAY)

        self.assertEqual(basic["department"], UNASSIGNED_DEPARTMENT)
        self.assertIsNone(basic["department_id"])
        self.assertEqual(basic["amount"], 8000.0)
        self.assertEqual(totals["departments"], 1)

    def test_contributions_split_by_department(self):
        Deduction.objects.create(
            title="Provident Fund",
            is_fixed=False,
            based_on="basic_pay",
            rate=12.0,
            employer_rate=12.0,
            include_active_employees=True,
            is_condition_based=False,
            is_pretax=True,
        )
        with patch("payroll.methods.methods.get_leaves", return_value=NO_LEAVE):
            for employee in (self.ann, self.ben):
                result = payroll_calculation(employee, START, END)
                save_payslip(**payslip_fields(result, employee, status="paid"))

        rows, _totals = accounting_report.summarise(Payslip.objects.all())
        employee_rows = [
            row
            for row in rows
            if str(row["key"]).startswith("contribution_employee:")
        ]
        by_dept = {row["department"]: row for row in employee_rows}

        self.assertEqual(len(employee_rows), 2)
        expected = 30000 * 0.12
        self.assertAlmostEqual(by_dept["Sales"]["amount"], expected, places=2)
        self.assertAlmostEqual(by_dept["Ops"]["amount"], expected, places=2)

    def test_company_total_matches_sum_across_departments(self):
        self.payslip(
            self.ann,
            basic_pay=10000.0,
            net_pay=8500.0,
            pay_head_data={"federal_tax": 400.0},
        )
        self.payslip(
            self.ben,
            basic_pay=12000.0,
            net_pay=10000.0,
            pay_head_data={"federal_tax": 600.0},
        )
        self.payslip(
            self.cam,
            basic_pay=5000.0,
            net_pay=4500.0,
            pay_head_data={"federal_tax": 200.0},
        )

        rows, totals = accounting_report.summarise(Payslip.objects.all())
        tax_rows = [row for row in rows if row["key"] == INCOME_TAX]

        self.assertEqual(len(tax_rows), 3)
        self.assertAlmostEqual(
            sum(row["amount"] for row in tax_rows), totals["income_tax"], places=2
        )
        self.assertEqual(totals["income_tax"], 1200.0)
        self.assertEqual(totals["basic_pay"], 27000.0)
        self.assertEqual(totals["departments"], 3)
        # Named departments sort before Unassigned.
        self.assertEqual(
            [row["department"] for row in tax_rows],
            ["Ops", "Sales", UNASSIGNED_DEPARTMENT],
        )
