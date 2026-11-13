"""Family-member JSON API. React registers members; the classic UI is unchanged."""

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from employee.models import EmployeeFamilyMember, ProfileEditFeature
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user


def family_url(employee_id, pk=None):
    base = f"/api/v1/employee/employees/{employee_id}/family/"
    if pk is None:
        return base
    return f"{base}{pk}/"


class EmployeeFamilyAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Family Co")

        self.user = make_user("family_self")
        self.employee = make_employee(
            company=self.company,
            email="family-self@test.horilla",
            first_name="Sam",
            user=self.user,
        )
        ProfileEditFeature.objects.create(is_enabled=True)

        self.stranger = make_user("family_stranger")
        make_employee(
            company=self.company,
            email="family-stranger@test.horilla",
            first_name="Sid",
            user=self.stranger,
        )
        self.client.force_authenticate(user=self.user)

    def test_create_with_required_fields_only(self):
        response = self.client.post(
            family_url(self.employee.pk),
            {"first_name": "Ada", "relation": "spouse"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["first_name"], "Ada")
        self.assertEqual(response.data["relation"], "spouse")
        self.assertEqual(response.data["relation_display"], "Spouse")
        self.assertEqual(response.data["relation_other"], "")
        self.assertIsNone(response.data["last_name"])
        self.assertIsNone(response.data["phone"])
        self.assertIsNone(response.data["alternative_phone"])
        self.assertIsNone(response.data["email"])
        self.assertIsNone(response.data["address"])
        self.assertIsNone(response.data["gender"])
        self.assertIsNone(response.data["date_of_birth"])
        self.assertEqual(
            EmployeeFamilyMember.objects.filter(employee=self.employee).count(), 1
        )

    def test_other_requires_free_text_relation(self):
        response = self.client.post(
            family_url(self.employee.pk),
            {"first_name": "Ned", "relation": "other"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("relation_other", response.data)

        response = self.client.post(
            family_url(self.employee.pk),
            {
                "first_name": "Ned",
                "relation": "other",
                "relation_other": "Cousin",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["relation_display"], "Other")
        self.assertEqual(response.data["relation_other"], "Cousin")

    def test_relation_other_rejected_unless_relation_is_other(self):
        response = self.client.post(
            family_url(self.employee.pk),
            {
                "first_name": "Ada",
                "relation": "child",
                "relation_other": "Stepson",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("relation_other", response.data)
        self.assertFalse(
            EmployeeFamilyMember.objects.filter(employee=self.employee).exists()
        )

    def test_invalid_phone_is_rejected(self):
        response = self.client.post(
            family_url(self.employee.pk),
            {"first_name": "Ada", "relation": "parent", "phone": "12"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("phone", response.data)

    def test_optional_contact_fields_round_trip(self):
        response = self.client.post(
            family_url(self.employee.pk),
            {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "relation": "spouse",
                "gender": "female",
                "date_of_birth": "1990-12-10",
                "phone": "+1 555 123 4567",
                "alternative_phone": "5557654321",
                "email": "ada@example.com",
                "address": "1 Analytical Engine",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["email"], "ada@example.com")
        self.assertEqual(response.data["phone"], "+1 555 123 4567")
        self.assertEqual(response.data["address"], "1 Analytical Engine")
        self.assertEqual(response.data["gender"], "female")
        self.assertEqual(response.data["date_of_birth"], "1990-12-10")

    def test_stranger_cannot_list_or_create(self):
        self.client.force_authenticate(user=self.stranger)
        listed = self.client.get(family_url(self.employee.pk))
        self.assertEqual(listed.status_code, 403, listed.content)
        created = self.client.post(
            family_url(self.employee.pk),
            {"first_name": "Ada", "relation": "spouse"},
            format="json",
        )
        self.assertEqual(created.status_code, 403, created.content)

    def test_self_edit_respects_profile_edit_toggle(self):
        ProfileEditFeature.objects.update(is_enabled=False)
        response = self.client.post(
            family_url(self.employee.pk),
            {"first_name": "Ada", "relation": "spouse"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)
        listed = self.client.get(family_url(self.employee.pk))
        self.assertEqual(listed.status_code, 200, listed.content)

    def test_manager_can_register_for_a_report(self):
        ProfileEditFeature.objects.update(is_enabled=False)
        report = make_employee(
            company=self.company,
            email="family-report@test.horilla",
            first_name="Rory",
        )
        report.employee_work_info.reporting_manager_id = self.employee
        report.employee_work_info.save()

        response = self.client.post(
            family_url(report.pk),
            {"first_name": "Ada", "relation": "sibling"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_hr_can_edit_without_profile_edit(self):
        ProfileEditFeature.objects.update(is_enabled=False)
        hr = make_user("family_hr")
        make_employee(
            company=self.company,
            email="family-hr@test.horilla",
            first_name="Hera",
            user=hr,
        )
        hr.user_permissions.add(Permission.objects.get(codename="change_employee"))
        self.client.force_authenticate(user=hr)
        response = self.client.post(
            family_url(self.employee.pk),
            {"first_name": "Ada", "relation": "guardian"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_patch_clears_relation_other_when_leaving_other(self):
        created = self.client.post(
            family_url(self.employee.pk),
            {
                "first_name": "Ned",
                "relation": "other",
                "relation_other": "Cousin",
            },
            format="json",
        )
        pk = created.data["id"]
        response = self.client.patch(
            family_url(self.employee.pk, pk),
            {"relation": "parent"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["relation"], "parent")
        self.assertEqual(response.data["relation_other"], "")

    def test_delete_and_missing_member(self):
        created = self.client.post(
            family_url(self.employee.pk),
            {"first_name": "Ada", "relation": "spouse"},
            format="json",
        )
        pk = created.data["id"]
        deleted = self.client.delete(family_url(self.employee.pk, pk))
        self.assertEqual(deleted.status_code, 204, deleted.content)
        missing = self.client.get(family_url(self.employee.pk, pk))
        self.assertEqual(missing.status_code, 404, missing.content)

    def test_unknown_employee_is_404(self):
        response = self.client.get(family_url(99999999))
        self.assertEqual(response.status_code, 404, response.content)
