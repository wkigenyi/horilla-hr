"""Company GL mappings attached to the accounting summary."""

from datetime import date

from django.db import IntegrityError
from django.test import TestCase

from base.models import Department
from horilla.testkit import make_company, make_employee
from payroll.accounting_components import BASIC_PAY, INCOME_TAX, NET_PAY
from payroll.methods import accounting_report
from payroll.models.accounting_gl import PayrollGLMapping
from payroll.models.models import Contract, Payslip
from payroll.tests.factories_payroll import make_active_contract

START = date(2026, 4, 1)
END = date(2026, 4, 30)


class PayrollGLMappingModelTests(TestCase):
    def setUp(self):
        self.company = make_company("GL Co")
        self.other = make_company("Other GL Co")

    def test_unique_per_company_and_line_key(self):
        PayrollGLMapping.objects.create(
            company_id=self.company, line_key=BASIC_PAY, gl_code="5100"
        )
        with self.assertRaises(IntegrityError):
            PayrollGLMapping.objects.create(
                company_id=self.company, line_key=BASIC_PAY, gl_code="5101"
            )

    def test_same_key_allowed_on_another_company(self):
        PayrollGLMapping.objects.create(
            company_id=self.company, line_key=BASIC_PAY, gl_code="5100"
        )
        other = PayrollGLMapping.objects.create(
            company_id=self.other, line_key=BASIC_PAY, gl_code="6100"
        )
        self.assertEqual(other.gl_code, "6100")


class AttachGLCodesTests(TestCase):
    def setUp(self):
        self.company = make_company("Attach GL")
        self.employee = make_employee(
            company=self.company, email="attach-gl@test.horilla", first_name="Ann"
        )
        Contract.objects.filter(employee_id=self.employee).delete()
        make_active_contract(self.employee, wage=30000.0)
        sales = Department.objects.create(department="Sales")
        info = self.employee.employee_work_info
        info.department_id = sales
        info.save()
        PayrollGLMapping.objects.create(
            company_id=self.company, line_key=BASIC_PAY, gl_code="5100"
        )
        PayrollGLMapping.objects.create(
            company_id=self.company, line_key=INCOME_TAX, gl_code="2100"
        )

    def test_attach_fills_mapped_and_leaves_others_empty(self):
        Payslip.objects.create(
            employee_id=self.employee,
            start_date=START,
            end_date=END,
            basic_pay=10000.0,
            gross_pay=10000.0,
            deduction=500.0,
            net_pay=9500.0,
            contract_wage=30000.0,
            status="paid",
            pay_head_data={"federal_tax": 500.0},
        )
        rows, _totals = accounting_report.summarise(Payslip.objects.all())
        accounting_report.attach_gl_codes(rows, self.company)
        by_key = {row["key"]: row for row in rows}

        self.assertEqual(by_key[BASIC_PAY]["gl_code"], "5100")
        self.assertEqual(by_key[INCOME_TAX]["gl_code"], "2100")
        self.assertEqual(by_key[NET_PAY]["gl_code"], "")

    def test_mappable_keys_include_catalog(self):
        keys = {line["key"] for line in accounting_report.mappable_line_keys(self.company)}
        self.assertIn(BASIC_PAY, keys)
        self.assertIn(NET_PAY, keys)
        self.assertIn(INCOME_TAX, keys)
