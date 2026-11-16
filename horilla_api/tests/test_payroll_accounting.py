"""GL mapping API and accounting summary / CSV export."""

import csv
from datetime import date
from io import StringIO

from django.test import TestCase
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model

from base.models import Department
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from payroll.accounting_components import BASIC_PAY, INCOME_TAX, NET_PAY
from payroll.models.accounting_gl import PayrollGLMapping
from payroll.models.models import Contract, Payslip
from payroll.tests.factories_payroll import make_active_contract

START = date(2026, 4, 1)
END = date(2026, 4, 30)


class AccountingApiTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.client = APIClient()
        self.company = make_company("Acct API Co")
        self.user = make_user("acct_api", password="secret123", is_superuser=True)
        self.admin = make_employee(
            company=self.company, email="acct_api@test.horilla", user=self.user
        )
        # Reload the user so the reverse employee_get link is visible to the API.
        self.user = get_user_model().objects.get(pk=self.user.pk)
        self.assertEqual(self.user.employee_get.get_company(), self.company)
        self.employee = make_employee(
            company=self.company,
            email="worker-acct@test.horilla",
            first_name="Ben",
        )
        Contract.objects.filter(employee_id=self.employee).delete()
        make_active_contract(self.employee, wage=30000.0)
        sales = Department.objects.create(department="Sales")
        info = self.employee.employee_work_info
        info.department_id = sales
        info.save()
        self.client.force_authenticate(user=self.user)

        Payslip.objects.create(
            employee_id=self.employee,
            start_date=START,
            end_date=END,
            basic_pay=20000.0,
            gross_pay=20000.0,
            deduction=1000.0,
            net_pay=19000.0,
            contract_wage=30000.0,
            status="paid",
            pay_head_data={"federal_tax": 1000.0},
        )

    def tearDown(self):
        set_selected_company(None)

    def test_gl_mapping_get_lists_catalog_keys(self):
        response = self.client.get("/api/v1/payroll/accounting/gl-mappings/")
        self.assertEqual(response.status_code, 200, response.content)
        keys = {row["line_key"] for row in response.data["mappings"]}
        self.assertIn(BASIC_PAY, keys)
        self.assertIn(NET_PAY, keys)
        basic = next(
            row for row in response.data["mappings"] if row["line_key"] == BASIC_PAY
        )
        self.assertEqual(basic["gl_code"], "")

    def test_gl_mapping_put_upserts(self):
        response = self.client.put(
            "/api/v1/payroll/accounting/gl-mappings/",
            {
                "mappings": [
                    {"line_key": BASIC_PAY, "gl_code": "5100", "label": "Salaries"},
                    {"line_key": INCOME_TAX, "gl_code": "2100", "label": "PAYE"},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        stored = {
            row.line_key: row.gl_code
            for row in PayrollGLMapping.objects.filter(company_id=self.company)
        }
        self.assertEqual(stored[BASIC_PAY], "5100")
        self.assertEqual(stored[INCOME_TAX], "2100")
        by_key = {row["line_key"]: row for row in response.data["mappings"]}
        self.assertEqual(by_key[BASIC_PAY]["gl_code"], "5100")
        self.assertEqual(by_key[BASIC_PAY]["label"], "Salaries")

    def test_gl_mapping_put_rejects_unknown_keys(self):
        response = self.client.put(
            "/api/v1/payroll/accounting/gl-mappings/",
            {"mappings": [{"line_key": "not_a_real_line", "gl_code": "9"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("not_a_real_line", response.data["line_keys"])

    def test_summary_includes_department_and_gl_code(self):
        PayrollGLMapping.objects.create(
            company_id=self.company, line_key=BASIC_PAY, gl_code="5100"
        )
        response = self.client.get(
            "/api/v1/payroll/accounting/summary/",
            {"start_date": START.isoformat(), "end_date": END.isoformat()},
        )
        self.assertEqual(response.status_code, 200, response.content)
        by_key = {row["key"]: row for row in response.data["rows"]}
        self.assertEqual(by_key[BASIC_PAY]["department"], "Sales")
        self.assertEqual(by_key[BASIC_PAY]["gl_code"], "5100")
        self.assertEqual(by_key[NET_PAY]["gl_code"], "")
        self.assertEqual(by_key[BASIC_PAY]["amount"], 20000.0)

    def test_csv_export_includes_unmapped_empty_gl(self):
        PayrollGLMapping.objects.create(
            company_id=self.company, line_key=BASIC_PAY, gl_code="5100"
        )
        response = self.client.get(
            "/api/v1/payroll/accounting/export/",
            {"start_date": START.isoformat(), "end_date": END.isoformat()},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Content-Type"], "text/csv")
        reader = csv.DictReader(StringIO(response.content.decode("utf-8")))
        rows = list(reader)
        by_key = {row["line_key"]: row for row in rows}
        self.assertEqual(by_key[BASIC_PAY]["gl_code"], "5100")
        self.assertEqual(by_key[BASIC_PAY]["department"], "Sales")
        self.assertEqual(by_key[NET_PAY]["gl_code"], "")
        self.assertIn("amount", reader.fieldnames)
