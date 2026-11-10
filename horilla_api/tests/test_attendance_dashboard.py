"""
The attendance dashboard over JWT.

``attendance/dashboard.py`` computes every KPI and chart the reference page
draws. These pin the API door: the same JSON, for an authenticated caller.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

ROOT = "/api/v1/attendance/dashboard/"


def widget_url(slug):
    return f"{ROOT}{slug}/"


class AttendanceDashboardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Attendance Co")
        self.user = make_user("attendance_manager")
        make_employee(
            company=self.company,
            email="attendance_manager@test.horilla",
            user=self.user,
        )

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(widget_url("kpi")).status_code, 401)

    def test_kpi_returns_todays_counts(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(widget_url("kpi"))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        for key in (
            "present_today",
            "attendance_rate",
            "on_time",
            "late_come",
            "early_out",
            "expected_to_check_in",
            "pending_overtime",
            "date",
        ):
            self.assertIn(key, data)
        self.assertEqual(data["present_today"], 0)
        self.assertEqual(data["pending_overtime"], 0)

    def test_every_widget_answers_json(self):
        from horilla_api.api_views.dashboard.views import ATTENDANCE_WIDGETS

        self.client.force_authenticate(user=self.user)
        for slug in ATTENDANCE_WIDGETS:
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
