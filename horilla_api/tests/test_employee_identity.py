"""National ID, Tax ID, and other identity documents."""

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from employee.models import EmployeeIdentifier, ProfileEditFeature
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user


def employee_url(employee):
    return f"/api/v1/employee/employees/{employee.pk}/"


def identifiers_url(employee_id, pk=None):
    base = f"/api/v1/employee/employees/{employee_id}/identifiers/"
    if pk is None:
        return base
    return f"{base}{pk}/"


class EmployeeStatutoryIdTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Identity Co")
        self.user = make_user("identity_self")
        self.employee = make_employee(
            company=self.company,
            email="identity-self@test.horilla",
            first_name="Sam",
            user=self.user,
        )
        ProfileEditFeature.objects.create(is_enabled=True)
        self.client.force_authenticate(user=self.user)

    def test_blank_statutory_ids_are_allowed(self):
        other = make_employee(
            company=self.company,
            email="identity-other@test.horilla",
            first_name="Ora",
        )
        self.employee.refresh_from_db()
        other.refresh_from_db()
        self.assertIsNone(self.employee.national_id)
        self.assertIsNone(self.employee.tax_id)
        self.assertIsNone(other.national_id)
        self.assertIsNone(other.tax_id)

    def test_self_cannot_set_tax_id(self):
        response = self.client.put(
            employee_url(self.employee),
            {"tax_id": "TIN-SELF", "phone": "5551234567"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.employee.refresh_from_db()
        self.assertIsNone(self.employee.tax_id)
        self.assertEqual(self.employee.phone, "5551234567")
        detail = self.client.get(employee_url(self.employee))
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertIn("tax_id", detail.data)
        self.assertIsNone(detail.data["tax_id"])
        self.assertIn("national_id", detail.data)

    def test_directory_omits_statutory_ids(self):
        response = self.client.get("/api/v1/employee/list/employees/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertGreater(response.data["count"], 0)
        for row in response.data["results"]:
            self.assertNotIn("national_id", row)
            self.assertNotIn("tax_id", row)

    def test_hr_can_set_tax_id_and_duplicates_are_rejected(self):
        hr = make_user("identity_hr")
        make_employee(
            company=self.company,
            email="identity-hr@test.horilla",
            first_name="Hera",
            user=hr,
        )
        hr.user_permissions.add(Permission.objects.get(codename="change_employee"))
        hr_client = APIClient()
        hr_client.force_authenticate(user=hr)

        response = hr_client.put(
            employee_url(self.employee), {"tax_id": "TIN-1"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.tax_id, "TIN-1")

        other = make_employee(
            company=self.company,
            email="identity-dup@test.horilla",
            first_name="Dee",
        )
        duplicate = hr_client.put(
            employee_url(other), {"tax_id": "TIN-1"}, format="json"
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.content)
        self.assertIn("tax_id", duplicate.data)
        other.refresh_from_db()
        self.assertIsNone(other.tax_id)

        cleared = hr_client.put(
            employee_url(self.employee), {"tax_id": ""}, format="json"
        )
        self.assertEqual(cleared.status_code, 200, cleared.content)
        self.employee.refresh_from_db()
        self.assertIsNone(self.employee.tax_id)


class EmployeeIdentifierAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Documents Co")
        self.user = make_user("docs_self")
        self.employee = make_employee(
            company=self.company,
            email="docs-self@test.horilla",
            first_name="Sam",
            user=self.user,
        )
        ProfileEditFeature.objects.create(is_enabled=True)
        self.stranger = make_user("docs_stranger")
        make_employee(
            company=self.company,
            email="docs-stranger@test.horilla",
            first_name="Sid",
            user=self.stranger,
        )
        self.client.force_authenticate(user=self.user)

    def test_create_passport(self):
        response = self.client.post(
            identifiers_url(self.employee.pk),
            {
                "document_type": "passport",
                "document_number": "P123456",
                "issuing_authority": "Immigration",
                "issue_date": "2020-01-15",
                "expiry_date": "2030-01-14",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["document_type_display"], "Passport")
        self.assertEqual(response.data["document_type_other"], "")
        self.assertEqual(response.data["document_number"], "P123456")

    def test_other_requires_a_label(self):
        missing = self.client.post(
            identifiers_url(self.employee.pk),
            {"document_type": "other", "document_number": "X1"},
            format="json",
        )
        self.assertEqual(missing.status_code, 400, missing.content)
        self.assertIn("document_type_other", missing.data)

        created = self.client.post(
            identifiers_url(self.employee.pk),
            {
                "document_type": "other",
                "document_type_other": "Voter card",
                "document_number": "X1",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.data["document_type_other"], "Voter card")

    def test_label_rejected_unless_type_is_other(self):
        response = self.client.post(
            identifiers_url(self.employee.pk),
            {
                "document_type": "driving_licence",
                "document_type_other": "Motorcycle",
                "document_number": "DL9",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("document_type_other", response.data)

    def test_expiry_before_issue_date_is_rejected(self):
        response = self.client.post(
            identifiers_url(self.employee.pk),
            {
                "document_type": "passport",
                "document_number": "P1",
                "issue_date": "2024-06-01",
                "expiry_date": "2024-05-01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("expiry_date", response.data)
        self.assertFalse(
            EmployeeIdentifier.objects.filter(employee=self.employee).exists()
        )

    def test_stranger_cannot_list(self):
        self.client.force_authenticate(user=self.stranger)
        response = self.client.get(identifiers_url(self.employee.pk))
        self.assertEqual(response.status_code, 403, response.content)

    def test_two_passports_are_allowed(self):
        for number in ("OLD", "NEW"):
            response = self.client.post(
                identifiers_url(self.employee.pk),
                {"document_type": "passport", "document_number": number},
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            EmployeeIdentifier.objects.filter(
                employee=self.employee, document_type="passport"
            ).count(),
            2,
        )
