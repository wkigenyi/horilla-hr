from django.test import TestCase

from ohs.models import OshWorkplace
from horilla.testkit import make_company


class OhsModelSmokeTests(TestCase):
    def test_workplace_str(self):
        company = make_company("OHS Smoke")
        workplace = OshWorkplace.objects.create(
            name="Site A", company_id=company, jurisdiction="UG"
        )
        self.assertEqual(str(workplace), "Site A")
