"""Ready-made tax packs through the JSON API, as Imara loads them."""

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user
from payroll.models.models import Deduction, FilingStatus
from payroll.models.tax_models import PayrollSettings

URL = "/api/v1/payroll/tax-pack/"
UGANDA = "Uganda PAYE (FY 2025/26)"


class TaxPackApiTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.client = APIClient()
        self.company = make_company("Pack Api Co")
        self.user = make_user("pack_api", password="secret123", is_superuser=True)
        make_employee(
            company=self.company, email="pack_api@test.horilla", user=self.user
        )
        # Drop the cached "no employee" the user picked up before it had one.
        self.user.refresh_from_db()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        set_selected_company(None)

    def test_the_list_describes_the_uganda_pack(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.data if item["key"] == "ug_paye")
        self.assertEqual(row["name"], UGANDA)
        self.assertEqual(row["tax_scale"], "period")
        self.assertEqual(row["top_rate"], 40)
        self.assertEqual(
            row["components"],
            ["Employee NSSF Contribution", "Employer NSSF Contribution", "LST"],
        )
        self.assertEqual(row["currency"], {"symbol": "UGX", "position": "prefix"})
        self.assertFalse(row["already_loaded"])

    def test_loading_creates_paye_nssf_lst_and_sets_ugx(self):
        response = self.client.post(URL, {"keys": ["ug_paye"]}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn(UGANDA, response.data["created"])
        self.assertIn("Currency UGX", response.data["created"])
        status = FilingStatus.objects.get(filing_status=UGANDA)
        self.assertEqual(status.tax_scale, "period")
        self.assertTrue(
            Deduction.objects.filter(title="Employee NSSF Contribution").exists()
        )
        settings = PayrollSettings.objects.get(company_id=self.company)
        self.assertEqual(settings.currency_symbol, "UGX")
        listed = self.client.get(URL).data
        self.assertTrue(
            next(item for item in listed if item["key"] == "ug_paye")["already_loaded"]
        )

    def test_loading_twice_creates_nothing_the_second_time(self):
        self.client.post(URL, {"keys": ["ug_paye"]}, format="json")
        response = self.client.post(URL, {"keys": ["ug_paye"]}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["created"], [])
        self.assertEqual(Deduction.objects.filter(title="LST").count(), 1)

    def test_keys_must_be_a_list(self):
        response = self.client.post(URL, {"keys": "ug_paye"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FilingStatus.objects.exists())

    def test_without_permission_to_change_currency_the_uganda_pack_is_refused(self):
        user = make_user("pack_limited", password="secret123")
        make_employee(
            company=self.company, email="pack_limited@test.horilla", user=user
        )
        user.refresh_from_db()
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=["view_filingstatus", "add_filingstatus", "add_deduction"]
            )
        )
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(URL, {"keys": ["ug_paye"]}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(FilingStatus.objects.filter(filing_status=UGANDA).exists())
        # A pack that touches neither components nor currency still loads.
        response = client.post(URL, {"keys": ["flat_10"]}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
