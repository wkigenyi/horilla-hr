"""
The analytics home dashboard over JWT.

``base/dashboard.py`` computes every widget for the session-backed web page.
These pin the API door in front of it: a bearer-authenticated caller gets
the same JSON the web page draws, permission-gated widgets still answer with
JSON, and unknown slugs are a clean 404.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

SUMMARY_URL = "/api/v1/dashboard/"


def widget_url(slug):
    return f"{SUMMARY_URL}{slug}/"


class DashboardSummaryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Dash Co")

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(SUMMARY_URL).status_code, 401)
        self.assertEqual(APIClient().get(widget_url("kpi")).status_code, 401)

    def test_plain_employee_is_the_employee_persona(self):
        user = make_user("dash_employee")
        make_employee(company=self.company, email="dash_employee@test.horilla", user=user)
        self.client.force_authenticate(user=user)

        response = self.client.get(SUMMARY_URL)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["role"], "employee")
        self.assertEqual(response.data["visible_charts"], [])
        self.assertIn("date", response.data)
        self.assertIn("company_label", response.data)

    def test_superuser_is_leadership_with_default_charts(self):
        user = make_user("dash_lead", is_superuser=True)
        make_employee(company=self.company, email="dash_lead@test.horilla", user=user)
        self.client.force_authenticate(user=user)

        response = self.client.get(SUMMARY_URL)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["role"], "leadership")
        visible = response.data["visible_charts"]
        for slug in (
            "attendance-trend",
            "department-overtime",
            "attendance-overview",
            "leave-coverage",
            "recruitment-pipeline",
            "turnover",
            "payroll-summary",
        ):
            self.assertIn(slug, visible)
        # Demoted charts stay off the default home.
        self.assertNotIn("recruitment-funnel", visible)
        self.assertNotIn("gender", visible)


class DashboardWidgetTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Widget Co")
        self.admin = make_user("widget_admin", is_superuser=True)
        make_employee(company=self.company, email="widget_admin@test.horilla", user=self.admin)
        self.employee_user = make_user("widget_employee")
        make_employee(
            company=self.company,
            email="widget_employee@test.horilla",
            user=self.employee_user,
        )

    def test_kpi_returns_the_documented_keys(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(widget_url("kpi"))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        for key in (
            "total_employees",
            "present_today",
            "absent_today",
            "attendance_rate",
            "on_leave",
            "pending_leaves",
            "new_joiners",
            "open_recruitments",
            "date",
        ):
            self.assertIn(key, data)
        self.assertEqual(data["total_employees"], 2)

    def test_every_widget_answers_json_for_leadership(self):
        from horilla_api.api_views.dashboard.views import WIDGETS

        self.client.force_authenticate(user=self.admin)
        for slug in WIDGETS:
            response = self.client.get(widget_url(slug))
            self.assertEqual(response.status_code, 200, (slug, response.content))
            self.assertTrue(
                response["Content-Type"].startswith("application/json"),
                (slug, response["Content-Type"]),
            )
            response.json()

    def test_gated_widget_still_answers_json_for_an_employee(self):
        self.client.force_authenticate(user=self.employee_user)
        response = self.client.get(widget_url("payroll-summary"))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json().get("no_permission"))

    def test_side_panels_are_readable_by_an_employee(self):
        self.client.force_authenticate(user=self.employee_user)
        for slug, key in (
            ("announcements", "announcements"),
            ("todays-leave", "leaves"),
            ("upcoming-holidays", "holidays"),
            ("birthdays-anniversaries", "birthdays"),
            ("pending-approvals", "pending"),
        ):
            response = self.client.get(widget_url(slug))
            self.assertEqual(response.status_code, 200, (slug, response.content))
            self.assertIn(key, response.json())

    def test_unknown_widget_is_404(self):
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get(widget_url("nope")).status_code, 404)
