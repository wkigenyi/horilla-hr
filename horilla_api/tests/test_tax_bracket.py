"""Open-ended tax brackets store an infinite max income, which JSON cannot encode."""

import json
import math

from django.test import TestCase
from rest_framework.test import APIClient

from horilla.testkit import make_company, make_employee, make_user
from payroll.models.models import FilingStatus
from payroll.models.tax_models import TaxBracket


class TaxBracketApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        company = make_company("Tax Co")
        self.user = make_user("tax_admin", password="secret123", is_superuser=True)
        make_employee(company=company, email="tax_admin@test.horilla", user=self.user)
        self.filing = FilingStatus.objects.create(
            filing_status="Single", company_id=company
        )
        self.client.force_authenticate(user=self.user)

    def test_list_encodes_an_open_ended_bracket(self):
        TaxBracket.objects.create(
            filing_status_id=self.filing,
            min_income=0,
            max_income=math.inf,
            tax_rate=10,
        )
        TaxBracket.objects.create(
            filing_status_id=self.filing,
            min_income=50000,
            max_income=100000,
            tax_rate=20,
        )

        response = self.client.get("/api/v1/payroll/tax-bracket/")

        self.assertEqual(response.status_code, 200, response.content)
        body = json.loads(response.content)
        by_min = {row["min_income"]: row["max_income"] for row in body}
        self.assertIsNone(by_min[0])
        self.assertEqual(by_min[50000], 100000)

    def test_create_without_a_maximum_stores_the_open_ended_sentinel(self):
        response = self.client.post(
            "/api/v1/payroll/tax-bracket/",
            {"filing_status_id": self.filing.id, "min_income": 0, "tax_rate": 10},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.data["max_income"])
        stored = TaxBracket.objects.get(id=response.data["id"])
        self.assertTrue(math.isinf(stored.max_income))
