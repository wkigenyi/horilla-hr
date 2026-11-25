"""The payroll dashboard over JWT."""

from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_user

ROOT = "/api/v1/payroll/dashboard/"


def widget_url(slug):
    return f"{ROOT}{slug}/"


class PayrollDashboardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Payroll Co")
        self.user = make_user("payroll_manager", is_superuser=True)

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(widget_url("kpi")).status_code, 401)

    def test_kpi_returns_pay_totals(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(widget_url("kpi"))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        for key in ("total_net", "total_gross", "total_deductions", "active_loans", "pending_reimbursements"):
            self.assertIn(key, data)
        self.assertEqual(data["total_net"], 0)

    def test_every_widget_answers_json(self):
        from horilla_api.api_views.dashboard.views import PAYROLL_WIDGETS

        self.client.force_authenticate(user=self.user)
        for slug in PAYROLL_WIDGETS:
            response = self.client.get(widget_url(slug))
            self.assertEqual(response.status_code, 200, (slug, response.content))
            response.json()

    def test_contracts_widget_names_each_contract(self):
        """Each row carries the contract id, so the dashboard can open that contract."""
        from datetime import date, timedelta

        from horilla.testkit.factories import make_contract, make_employee
        from payroll.models.models import Contract

        manager = make_user("contract_viewer", password="secret123", is_superuser=True)
        make_employee(company=self.company, email="viewer@test.horilla", user=manager)
        employee = make_employee(company=self.company, email="ending@test.horilla")
        Contract.objects.filter(employee_id=employee).delete()
        today = date.today()
        ended = make_contract(
            employee=employee,
            name="Ended",
            start_date=today - timedelta(days=300),
            end_date=today - timedelta(days=31),
        )
        ending = make_contract(
            employee=employee,
            name="Ending soon",
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=10),
        )
        Contract.objects.filter(pk=ending.pk).update(contract_status="active")

        # A real sign-in: the widget runs a session view, which a forced DRF user never reaches.
        login = self.client.post(
            "/api/v1/auth/login/",
            {"username": "contract_viewer", "password": "secret123"},
            format="json",
        )
        self.assertEqual(login.status_code, 200, login.content)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        response = client.get(widget_url("contracts"))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(
            [(row["contract_id"], row["id"]) for row in data["ending_soon"]],
            [(ending.id, employee.id)],
        )
        self.assertEqual(
            [(row["contract_id"], row["id"]) for row in data["expired"]],
            [(ended.id, employee.id)],
        )

    def test_unknown_widget_is_404(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(widget_url("nope")).status_code, 404)
