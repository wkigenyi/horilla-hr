"""The recruitment dashboard over JWT."""

from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_user

ROOT = "/api/v1/recruitment/dashboard/"


def widget_url(slug):
    return f"{ROOT}{slug}/"


class RecruitmentDashboardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Recruitment Co")
        self.user = make_user("recruitment_manager", is_superuser=True)

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(widget_url("kpi")).status_code, 401)

    def test_kpi_returns_vacancy_counts(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(widget_url("kpi"))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        for key in ("total_vacancy", "ongoing_recruitments", "total_hired", "conversion_rate", "acceptance_rate"):
            self.assertIn(key, data)
        self.assertEqual(data["total_vacancy"], 0)

    def test_every_widget_answers_json(self):
        from horilla_api.api_views.dashboard.views import RECRUITMENT_WIDGETS

        self.client.force_authenticate(user=self.user)
        for slug in RECRUITMENT_WIDGETS:
            response = self.client.get(widget_url(slug))
            self.assertEqual(response.status_code, 200, (slug, response.content))
            response.json()

    def test_unknown_widget_is_404(self):
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get(widget_url("nope")).status_code, 404)
