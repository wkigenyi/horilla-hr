"""
The onboarding dashboard over JWT.

``onboarding/dashboard.py`` computes every KPI and chart the reference page
draws. These pin the API door: the same JSON, for an authenticated caller.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

ROOT = "/api/v1/onboarding/dashboard/"


def widget_url(slug):
    return f"{ROOT}{slug}/"


class OnboardingDashboardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Onboarding Co")
        self.user = make_user("onboarding_manager", is_superuser=True)
        make_employee(
            company=self.company,
            email="onboarding_manager@test.horilla",
            user=self.user,
        )

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(widget_url("kpi")).status_code, 401)

    def test_kpi_returns_period_counts(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(widget_url("kpi"))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        for key in (
            "total_candidates",
            "active_recruitments",
            "completed_onboarding",
            "in_progress",
            "task_completion",
            "period_from_date",
            "period_to_date",
        ):
            self.assertIn(key, data)
        self.assertEqual(data["total_candidates"], 0)
        self.assertEqual(data["completed_onboarding"], 0)

    def test_every_widget_answers_json(self):
        from horilla_api.api_views.dashboard.views import ONBOARDING_WIDGETS

        self.client.force_authenticate(user=self.user)
        for slug in ONBOARDING_WIDGETS:
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
