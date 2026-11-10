"""
The employee My Dashboard over JWT.

``base/ess_dashboard.py`` computes every personal widget for the session
page. These pin the API door: the same JSON, scoped to the caller, with the
calendar flag and ISO dates the Next page formats.
"""

from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

ROOT = "/api/v1/employee/dashboard/"


def widget_url(slug):
    return f"{ROOT}{slug}/"


class EssDashboardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("ESS Co")
        self.user = make_user("ess_employee")
        make_employee(company=self.company, email="ess_employee@test.horilla", user=self.user)

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(widget_url("kpi")).status_code, 401)

    def test_kpi_returns_the_personal_counts(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(widget_url("kpi"))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        for key in (
            "present_this_month",
            "late_this_month",
            "pending_leave_requests",
            "upcoming_leave_count",
            "open_objectives",
        ):
            self.assertIn(key, data)
        self.assertEqual(data["present_this_month"], 0)
        self.assertEqual(data["pending_leave_requests"], 0)

    def test_calendar_reports_check_in_and_the_month(self):
        self.client.force_authenticate(user=self.user)
        today = date.today()
        response = self.client.get(
            widget_url("attendance-calendar"),
            {"from_date": today.replace(day=1).isoformat(), "to_date": today.isoformat()},
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertIn("check_in_enabled", data)
        self.assertIsInstance(data["check_in_enabled"], bool)
        self.assertGreaterEqual(len(data["days"]), 1)
        self.assertEqual(data["days"][0]["date"], today.replace(day=1).isoformat())

    def test_every_widget_answers_json(self):
        from horilla_api.api_views.dashboard.views import ESS_WIDGETS

        self.client.force_authenticate(user=self.user)
        for slug in ESS_WIDGETS:
            response = self.client.get(widget_url(slug))
            self.assertEqual(response.status_code, 200, (slug, response.content))
            self.assertTrue(
                response["Content-Type"].startswith("application/json"),
                (slug, response["Content-Type"]),
            )
            response.json()

    def test_unknown_widget_is_404(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(widget_url("nope")).status_code, 404)
