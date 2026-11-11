"""
Admin reset-password API: one-time JSON reveal, no email.

Stricter than the HTML view, which soft-fails self/no-user with HTTP 200
and a flash or empty modal. React needs 403/404 instead.
"""

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

PASSWORD = "secret123"


def reset_url(employee_id):
    return f"/api/v1/employee/employees/{employee_id}/reset-password/"


class AdminResetPasswordAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Reset Co")
        self.admin = make_user("reset_admin", password=PASSWORD)
        self.admin.user_permissions.add(
            Permission.objects.get(codename="change_employee")
        )
        make_employee(
            company=self.company,
            email="reset-admin@test.horilla",
            first_name="Admin",
            user=self.admin,
        )
        self.target_user = make_user("reset_target", password=PASSWORD)
        self.target = make_employee(
            company=self.company,
            email="reset-target@test.horilla",
            first_name="Target",
            user=self.target_user,
        )

    def test_admin_gets_a_new_password_once(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(reset_url(self.target.id))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Content-Type"].split(";")[0], "application/json")
        password = response.data["password"]
        self.assertIsInstance(password, str)
        self.assertTrue(password)
        self.target_user.refresh_from_db()
        self.assertTrue(self.target_user.check_password(password))
        self.assertTrue(self.target_user.is_new_employee)

    def test_forbidden_without_change_employee(self):
        plain = make_user("reset_plain", password=PASSWORD)
        make_employee(
            company=self.company,
            email="reset-plain@test.horilla",
            first_name="Plain",
            user=plain,
        )
        self.client.force_authenticate(user=plain)
        response = self.client.post(reset_url(self.target.id))
        self.assertEqual(response.status_code, 403, response.content)
        self.target_user.refresh_from_db()
        self.assertTrue(self.target_user.check_password(PASSWORD))

    def test_forbidden_when_resetting_self(self):
        admin_employee = self.admin.employee_get
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(reset_url(admin_employee.id))
        self.assertEqual(response.status_code, 403, response.content)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password(PASSWORD))

    def test_not_found_for_missing_employee(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(reset_url(99999999))
        self.assertEqual(response.status_code, 404, response.content)

    def test_not_found_when_employee_has_no_user(self):
        # Employee.save() auto-creates a login; clear the link without
        # going through save() so the row has no sign-in user.
        orphan = make_employee(
            company=self.company,
            email="reset-orphan@test.horilla",
            first_name="Orphan",
        )
        from employee.models import Employee

        Employee.objects.filter(pk=orphan.pk).update(employee_user_id=None)
        orphan.refresh_from_db()
        self.assertIsNone(orphan.employee_user_id_id)

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(reset_url(orphan.id))
        self.assertEqual(response.status_code, 404, response.content)
