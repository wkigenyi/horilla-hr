"""Filing status tax scale through the JSON API, as Imara uses it."""

from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_user
from payroll.models.models import FilingStatus
from payroll.models.tax_models import TaxBracket

UGANDA_MONTHLY = [
    (0, 235_000, 0),
    (235_000, 335_000, 10),
    (335_000, 410_000, 20),
    (410_000, 10_000_000, 30),
    (10_000_000, None, 40),
]


class FilingTaxScaleApiTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.client = APIClient()
        self.company = make_company("Tax Scale Co")
        self.user = make_user("tax_scale_api", password="secret123", is_superuser=True)
        self.client.force_authenticate(user=self.user)
        self.filing = FilingStatus.objects.create(
            filing_status="Uganda PAYE",
            based_on="taxable_gross_pay",
            company_id=self.company,
        )
        for low, high, rate in UGANDA_MONTHLY:
            TaxBracket.objects.create(
                filing_status_id=self.filing,
                min_income=low,
                max_income=high,
                tax_rate=rate,
            )
        self.url = f"/api/v1/payroll/filing-status/{self.filing.pk}/"

    def tearDown(self):
        set_selected_company(None)

    def test_a_status_reports_its_scale_band_unit_and_choices(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["tax_scale"], "annual")
        self.assertEqual(response.data["band_unit"], "year")
        values = [item["value"] for item in response.data["tax_scale_choices"]]
        self.assertEqual(values, ["annual", "period"])

    def test_switching_to_monthly_changes_band_unit_and_steps(self):
        response = self.client.put(self.url, {"tax_scale": "period"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["tax_scale"], "period")
        self.assertEqual(response.data["band_unit"], "month")
        self.assertIn("monthly", response.data["steps"][0])
        self.assertFalse(
            any("yearly figure" in step for step in response.data["steps"])
        )
        self.filing.refresh_from_db()
        self.assertEqual(self.filing.tax_scale, "period")

    def test_an_unknown_scale_is_refused(self):
        response = self.client.put(self.url, {"tax_scale": "weekly"}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.filing.refresh_from_db()
        self.assertEqual(self.filing.tax_scale, "annual")

    def test_saving_other_fields_keeps_the_scale(self):
        self.client.put(self.url, {"tax_scale": "period"}, format="json")
        response = self.client.put(self.url, {"cess_percent": 0}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["tax_scale"], "period")

    def test_monthly_preview_takes_a_months_income(self):
        self.client.put(self.url, {"tax_scale": "period"}, format="json")
        response = self.client.post(
            f"{self.url}preview/", {"income": 5_000_000}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["band_unit"], "month")
        self.assertEqual(response.data["income"], 5_000_000)
        self.assertEqual(response.data["tax"], 1_402_000)

    def test_preview_still_accepts_yearly_income(self):
        response = self.client.post(
            f"{self.url}preview/", {"yearly_income": 5_000_000}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["band_unit"], "year")
        self.assertEqual(response.data["tax"], 1_402_000)

    def test_preview_refuses_text_with_the_unit_in_the_message(self):
        self.client.put(self.url, {"tax_scale": "period"}, format="json")
        response = self.client.post(
            f"{self.url}preview/", {"income": "lots"}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("monthly", str(response.data["detail"]))
