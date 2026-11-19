"""An employee sees their own payslip only once payroll has confirmed or paid it."""

from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from payroll.models.models import Payslip


class PayslipEmployeeVisibilityTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.client = APIClient()
        self.company = make_company("Slip Co")
        self.user = make_user("slip_employee", password="secret123")
        self.employee = make_employee(
            company=self.company,
            email="slip_employee@test.horilla",
            first_name="Ama",
            user=self.user,
        )
        self.slips = {
            status: self._slip(status, month)
            for month, status in enumerate(["draft", "review_ongoing", "confirmed", "paid"], 1)
        }

    def tearDown(self):
        set_selected_company(None)

    def _slip(self, status, month):
        return Payslip.objects.create(
            employee_id=self.employee,
            start_date=date(2026, month, 1),
            end_date=date(2026, month, 28),
            pay_head_data={"federal_tax": 0, "allowances": []},
            status=status,
            basic_pay=1000,
            gross_pay=1000,
            deduction=0,
            net_pay=1000,
        )

    def test_list_leaves_out_slips_still_being_worked_on(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/v1/payroll/payslip/?employee_id={self.employee.pk}")
        self.assertEqual(response.status_code, 200, response.data)
        statuses = sorted(row["status"] for row in response.data["results"])
        self.assertEqual(statuses, ["confirmed", "paid"])

    def test_detail_and_pdf_hide_a_draft(self):
        self.client.force_authenticate(user=self.user)
        for status in ("draft", "review_ongoing"):
            slip = self.slips[status]
            self.assertEqual(
                self.client.get(f"/api/v1/payroll/payslip/{slip.pk}").status_code, 404
            )
            self.assertEqual(
                self.client.get(f"/api/v1/payroll/payslip-download/{slip.pk}").status_code,
                404,
            )
        paid = self.slips["paid"]
        self.assertEqual(self.client.get(f"/api/v1/payroll/payslip/{paid.pk}").status_code, 200)

    def test_payroll_staff_still_see_drafts(self):
        staff = make_user("slip_staff", password="secret123", is_superuser=True)
        make_employee(company=self.company, email="slip_staff@test.horilla", user=staff)
        self.client.force_authenticate(user=staff)
        response = self.client.get(f"/api/v1/payroll/payslip/?employee_id={self.employee.pk}")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["results"]), 4)
        draft = self.slips["draft"]
        self.assertEqual(self.client.get(f"/api/v1/payroll/payslip/{draft.pk}").status_code, 200)
