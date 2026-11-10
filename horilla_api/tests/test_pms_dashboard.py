"""The performance dashboard over JWT."""

from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_user

ROOT = "/api/v1/pms/dashboard/"


def widget_url(slug):
    return f"{ROOT}{slug}/"


class PmsDashboardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Performance Co")
        self.user = make_user("pms_manager", is_superuser=True)

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(widget_url("kpi")).status_code, 401)

    def test_kpi_returns_objective_counts(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(widget_url("kpi"))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        for key in ("total_objectives", "avg_progress", "at_risk", "pending_feedback"):
            self.assertIn(key, data)
        self.assertEqual(data["total_objectives"], 0)

    def test_every_widget_answers_json(self):
        from horilla_api.api_views.dashboard.views import PMS_WIDGETS

        self.client.force_authenticate(user=self.user)
        for slug in PMS_WIDGETS:
            response = self.client.get(widget_url(slug))
            self.assertEqual(response.status_code, 200, (slug, response.content))
            response.json()

    def test_unknown_widget_is_404(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(widget_url("nope")).status_code, 404)
