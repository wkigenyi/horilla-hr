"""
The analytics home dashboard over JWT.

``base/dashboard.py`` computes every widget for the session-backed web page.
These pin the API door in front of it: a bearer-authenticated caller gets
the same JSON the web page draws, permission-gated widgets still answer with
JSON, and unknown slugs are a clean 404.
"""

from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from base.models import DashboardEmployeeCharts
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

SUMMARY_URL = "/api/v1/dashboard/"
PREFS_URL = f"{SUMMARY_URL}prefs/"
SETUP_URL = f"{SUMMARY_URL}setup-checklist/"
SETUP_DISMISS_URL = f"{SUMMARY_URL}setup-checklist/dismiss/"


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
        self.assertEqual(APIClient().get(PREFS_URL).status_code, 401)
        self.assertEqual(APIClient().get(SETUP_URL).status_code, 401)

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
        self.assertTrue(response.data["can_open_ess"])
        self.assertFalse(response.data["can_open_analytics"])
        self.assertIsInstance(response.data["chart_prefs"], list)

    def test_superuser_is_leadership_with_default_charts(self):
        user = make_user("dash_lead", is_superuser=True)
        make_employee(company=self.company, email="dash_lead@test.horilla", user=user)
        self.client.force_authenticate(user=user)

        response = self.client.get(SUMMARY_URL)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["role"], "leadership")
        visible = response.data["visible_charts"]
        # Matches ROLE_DEFAULT_VISIBLE["leadership"] mapped through CHART_WIDGETS.
        # Charts removed from the web home defaults (attendance-trend, etc.) stay
        # available by slug but are not in the default persona set.
        for slug in (
            "department-headcount",
            "gender",
            "leave-breakdown",
            "leave-trends",
            "attendance-overview",
            "recruitment-pipeline",
            "turnover",
        ):
            self.assertIn(slug, visible)
        self.assertNotIn("recruitment-funnel", visible)
        self.assertNotIn("attendance-trend", visible)
        self.assertNotIn("payroll-summary", visible)
        self.assertNotIn("ticket-priority", visible)
        self.assertNotIn("overdue-tickets", visible)
        self.assertTrue(response.data["company_is_all"])
        self.assertTrue(response.data["can_open_ess"])
        self.assertTrue(response.data["can_open_analytics"])
        pref_ids = {p["id"] for p in response.data["chart_prefs"]}
        self.assertIn("department_headcount", pref_ids)
        self.assertIn("ticket_priority", pref_ids)

    def test_saved_prefs_override_role_defaults(self):
        user = make_user("dash_prefs", is_superuser=True)
        emp = make_employee(
            company=self.company, email="dash_prefs@test.horilla", user=user
        )
        DashboardEmployeeCharts.objects.create(
            employee=emp,
            charts=[
                {"id": "attendance_trend", "visible": True},
                {"id": "department_headcount", "visible": False},
            ],
        )
        self.client.force_authenticate(user=user)

        response = self.client.get(SUMMARY_URL)
        self.assertEqual(response.status_code, 200, response.content)
        visible = response.data["visible_charts"]
        self.assertIn("attendance-trend", visible)
        self.assertNotIn("department-headcount", visible)

    def test_superuser_company_header_narrows_dashboard_scope(self):
        user = make_user("dash_switch", password="secret123", is_superuser=True)
        make_employee(
            company=self.company, email="dash_switch@test.horilla", user=user
        )
        login = self.client.post(
            "/api/v1/auth/login/",
            {"username": "dash_switch", "password": "secret123"},
            format="json",
        )
        self.assertEqual(login.status_code, 200, login.content)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        all_scope = client.get(SUMMARY_URL)
        self.assertEqual(all_scope.status_code, 200, all_scope.content)
        self.assertTrue(all_scope.data["company_is_all"])

        one = client.get(
            SUMMARY_URL,
            HTTP_X_HORILLA_COMPANY=str(self.company.id),
        )
        self.assertEqual(one.status_code, 200, one.content)
        self.assertFalse(one.data["company_is_all"])
        self.assertEqual(one.data["company_label"], self.company.company)


class DashboardPrefsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Prefs Co")
        self.user = make_user("prefs_lead", is_superuser=True)
        self.employee = make_employee(
            company=self.company, email="prefs_lead@test.horilla", user=self.user
        )
        self.client.force_authenticate(user=self.user)

    def test_put_round_trip_updates_summary_visible_charts(self):
        response = self.client.put(
            PREFS_URL,
            {
                "prefs": [
                    {"id": "gender_distribution", "visible": True},
                    {"id": "leave_breakdown", "visible": False},
                    {"id": "ticket_priority", "visible": True},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["status"], "ok")
        self.assertIn("gender", response.data["visible_charts"])
        self.assertIn("ticket-priority", response.data["visible_charts"])
        self.assertNotIn("leave-breakdown", response.data["visible_charts"])

        stored = DashboardEmployeeCharts.objects.get(employee=self.employee)
        self.assertEqual(len(stored.charts), 3)

        summary = self.client.get(SUMMARY_URL)
        self.assertEqual(summary.status_code, 200, summary.content)
        self.assertIn("gender", summary.data["visible_charts"])
        self.assertIn("ticket-priority", summary.data["visible_charts"])

        loaded = self.client.get(PREFS_URL)
        self.assertEqual(loaded.status_code, 200, loaded.content)
        self.assertIn("gender", loaded.data["visible_charts"])


class DashboardSetupChecklistTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Setup Co")
        self.admin = make_user("setup_admin", is_superuser=True)
        make_employee(
            company=self.company, email="setup_admin@test.horilla", user=self.admin
        )
        self.employee_user = make_user("setup_employee")
        make_employee(
            company=self.company,
            email="setup_employee@test.horilla",
            user=self.employee_user,
        )

    def test_employee_does_not_see_checklist(self):
        self.client.force_authenticate(user=self.employee_user)
        response = self.client.get(SETUP_URL)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.data["show_setup_checklist"])

    def test_admin_can_dismiss_checklist(self):
        self.client.force_authenticate(user=self.admin)
        before = self.client.get(SETUP_URL)
        self.assertEqual(before.status_code, 200, before.content)
        self.assertIn("show_setup_checklist", before.data)

        dismiss = self.client.post(SETUP_DISMISS_URL, {}, format="json")
        self.assertEqual(dismiss.status_code, 200, dismiss.content)
        self.assertTrue(dismiss.data["ok"])

        after = self.client.get(SETUP_URL)
        self.assertEqual(after.status_code, 200, after.content)
        self.assertFalse(after.data["show_setup_checklist"])


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

    def test_ticket_widgets_are_soft_gated_for_employees(self):
        self.client.force_authenticate(user=self.employee_user)
        for slug in ("ticket-priority", "overdue-tickets"):
            response = self.client.get(widget_url(slug))
            self.assertEqual(response.status_code, 200, (slug, response.content))
            self.assertTrue(response.json().get("no_permission"))

    def test_period_query_is_echoed_on_period_aware_charts(self):
        self.client.force_authenticate(user=self.admin)
        today = date.today()
        from_date = today.replace(day=1).isoformat()
        to_date = today.isoformat()
        response = self.client.get(
            widget_url("leave-breakdown"),
            {"from_date": from_date, "to_date": to_date},
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data.get("from_date"), from_date)
        self.assertEqual(data.get("to_date"), to_date)

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
