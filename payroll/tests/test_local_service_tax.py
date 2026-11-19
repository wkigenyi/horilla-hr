"""
Uganda Local Service Tax.

The bands and the July-to-October window are checked on their own, then a
whole payslip is run so the interaction with PAYE is seen end to end: LST is
allowable for PAYE, so in a collection month it lowers the tax.
"""

import json
from datetime import date
from unittest.mock import patch

from django.test import TestCase

from horilla.testkit import make_company, make_employee
from payroll.methods.local_service_tax import (
    annual_lst,
    collection_months,
    financial_year,
    instalment,
    lst_for_period,
)
from payroll.methods.payroll_run import payroll_calculation
from payroll.models.models import Contract, FilingStatus
from payroll.tax_packs import load_tax_packs
from payroll.tests.factories_payroll import make_active_contract, make_deduction
from payroll.tests.test_payroll_calculation_golden import EMPTY_LEAVES


def month(year, number, start_day=1, end_day=None):
    import calendar

    last = calendar.monthrange(year, number)[1]
    return {
        "month": number,
        "year": year,
        "days": last,
        "start_date": f"{year}-{number:02d}-{start_day:02d}",
        "end_date": f"{year}-{number:02d}-{(end_day or last):02d}",
    }


class BandTests(TestCase):
    def test_the_schedule(self):
        for income, expected in (
            (0, 0),
            (100_000, 0),
            (100_001, 5_000),
            (150_000, 5_000),
            (200_000, 5_000),
            (200_001, 10_000),
            (650_000, 60_000),
            (1_000_000, 90_000),
            (1_000_001, 100_000),
            (5_000_000, 100_000),
        ):
            with self.subTest(income=income):
                self.assertEqual(annual_lst(income), expected)

    def test_an_instalment_is_a_quarter_of_the_year(self):
        self.assertEqual(instalment(150_000), 1_250)
        self.assertEqual(instalment(5_000_000), 25_000)

    def test_financial_year_starts_in_july(self):
        self.assertEqual(financial_year(2026, 7), 2026)
        self.assertEqual(financial_year(2027, 6), 2026)


class WindowTests(TestCase):
    def test_july_to_october_are_collection_months(self):
        for number in (7, 8, 9, 10):
            self.assertEqual(collection_months([month(2026, number)]), [(2026, number)])

    def test_other_months_are_not(self):
        for number in (1, 6, 11, 12):
            self.assertEqual(collection_months([month(2026, number)]), [])

    def test_a_week_inside_july_is_not_charged_but_the_week_ending_it_is(self):
        self.assertEqual(collection_months([month(2026, 7, 6, 12)]), [])
        self.assertEqual(collection_months([month(2026, 7, 27, 31)]), [(2026, 7)])

    def test_no_contract_flags_charges_the_instalment(self):
        self.assertEqual(lst_for_period(None, 150_000, [month(2026, 7)]), 1_250)
        self.assertEqual(lst_for_period(None, 150_000, [month(2026, 11)]), 0)


class PayslipTests(TestCase):
    """A 5,000,000 monthly earner on the Uganda pack."""

    WAGE = 5_000_000.0
    WORKING_DAYS = 22

    def setUp(self):
        company = make_company("Kampala Payroll Co")
        self.employee = make_employee(company=company, email="lst@test.horilla")
        Contract.objects.filter(employee_id=self.employee).delete()
        load_tax_packs(["ug_paye"])
        self.contract = make_active_contract(
            self.employee,
            wage=self.WAGE,
            contract_start_date=date(2026, 1, 1),
            filing_status=FilingStatus.objects.get(
                filing_status="Uganda PAYE (FY 2025/26)"
            ),
        )
        make_deduction(
            self.employee,
            "LST",
            is_fixed=False,
            based_on="uganda_lst",
            is_pretax=True,
            sequence=102,
        )

    def run_month(self, year, number):
        import calendar

        last = calendar.monthrange(year, number)[1]
        per_day = self.WAGE / self.WORKING_DAYS
        slice_ = month(year, number)
        slice_.update(
            {"working_days_on_period": self.WORKING_DAYS, "per_day_amount": per_day}
        )
        with patch(
            "payroll.methods.methods.months_between_range", return_value=[slice_]
        ), patch(
            "payroll.methods.methods.get_daily_salary",
            return_value={"day_wage": per_day},
        ), patch("payroll.methods.methods.get_leaves", return_value=EMPTY_LEAVES):
            data = payroll_calculation(
                self.employee, date(year, number, 1), date(year, number, last)
            )
        return json.loads(data["json_data"])

    def lst(self, payslip):
        return sum(
            line["amount"] for line in payslip["pretax_deductions"] if line["title"] == "LST"
        )

    def test_july_takes_an_instalment_and_paye_falls_by_its_tax(self):
        payslip = self.run_month(2026, 7)
        self.assertAlmostEqual(payslip["gross_pay"], self.WAGE, places=2)
        self.assertAlmostEqual(self.lst(payslip), 25_000, places=2)
        # 1,402,000 less 30% of the 25,000 LST
        self.assertAlmostEqual(payslip["federal_tax"], 1_394_500, places=2)

    def test_november_takes_none(self):
        payslip = self.run_month(2026, 11)
        self.assertEqual(self.lst(payslip), 0)
        self.assertAlmostEqual(payslip["federal_tax"], 1_402_000, places=2)

    def test_an_exempt_employee_pays_none(self):
        self.contract.lst_exempt = True
        self.contract.save()
        payslip = self.run_month(2026, 7)
        self.assertEqual(self.lst(payslip), 0)
        self.assertAlmostEqual(payslip["federal_tax"], 1_402_000, places=2)

    def test_lst_already_paid_elsewhere_this_year_is_not_taken_again(self):
        self.contract.lst_paid_elsewhere_fy = 2026
        self.contract.save()
        self.assertEqual(self.lst(self.run_month(2026, 8)), 0)

    def test_paid_elsewhere_last_year_does_not_cover_this_year(self):
        self.contract.lst_paid_elsewhere_fy = 2025
        self.contract.save()
        self.assertAlmostEqual(self.lst(self.run_month(2026, 8)), 25_000, places=2)


class StructurePreviewTests(TestCase):
    """The worked example on a salary structure, which has no employee."""

    def lines(self, preview):
        found = {}

        def walk(node):
            if isinstance(node, dict):
                if "title" in node and "amount" in node:
                    found[node["title"]] = node
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(preview)
        return found

    def test_gross_pay_deductions_and_lst_are_worked_out(self):
        from django.apps import apps

        from payroll.models.models import Allowance, Deduction
        from payroll.views.salary_structure_preview import (
            build_salary_structure_preview,
        )

        structure = apps.get_model("payroll", "SalaryStructure").objects.create(
            title="Uganda teachers"
        )
        structure.allowances.add(
            Allowance.objects.create(
                title="Housing",
                is_fixed=True,
                amount=1_000_000,
                is_taxable=True,
                maximum_unit="full_period",
            )
        )
        structure.deductions.add(
            Deduction.objects.create(
                title="Employee NSSF",
                is_fixed=False,
                based_on="gross_pay",
                rate=5,
                is_pretax=False,
            ),
            Deduction.objects.create(
                title="LST", is_fixed=False, based_on="uganda_lst", is_pretax=True
            ),
        )
        lines = self.lines(
            build_salary_structure_preview(structure, 0, 5_000_000, 0, None)
        )
        # 5% of the 6,000,000 gross, not of the 5,000,000 basic
        self.assertAlmostEqual(lines["Employee NSSF"]["amount"], 300_000, places=2)
        # The example shows one collection month's instalment.
        self.assertAlmostEqual(lines["LST"]["amount"], 25_000, places=2)


class SmallEarnerTests(PayslipTests):
    WAGE = 150_000.0

    def test_july_takes_an_instalment_and_paye_falls_by_its_tax(self):
        payslip = self.run_month(2026, 7)
        self.assertAlmostEqual(self.lst(payslip), 1_250, places=2)
        # Under the 235,000 threshold either way.
        self.assertAlmostEqual(payslip["federal_tax"], 0, places=2)

    def test_november_takes_none(self):
        self.assertEqual(self.lst(self.run_month(2026, 11)), 0)

    def test_an_exempt_employee_pays_none(self):
        self.contract.lst_exempt = True
        self.contract.save()
        self.assertEqual(self.lst(self.run_month(2026, 7)), 0)

    def test_paid_elsewhere_last_year_does_not_cover_this_year(self):
        self.contract.lst_paid_elsewhere_fy = 2025
        self.contract.save()
        self.assertAlmostEqual(self.lst(self.run_month(2026, 8)), 1_250, places=2)
