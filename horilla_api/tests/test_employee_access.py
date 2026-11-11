"""An employee profile lists that person's roles, and only a superuser can change them."""

from django.contrib.auth.models import Group, Permission
from rest_framework.test import APIClient

from django.test import TestCase

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

PASSWORD = "secret123"


def access_url(employee_id):
    return f"/api/v1/base/roles/people/{employee_id}/permissions/"


class EmployeeAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Access Co")
        self.user = make_user("access_user", password=PASSWORD)
        self.employee = make_employee(
            company=self.company,
            email="access@test.horilla",
            first_name="Amina",
            user=self.user,
        )
        self.role = Group.objects.create(name="Payroll readers")
        self.user.groups.add(self.role)
        self.view_employee = Permission.objects.get(codename="view_employee")

    def test_employee_sees_their_own_roles_and_not_the_permission_list(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(access_url(self.employee.id))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["roles"], [{"id": self.role.id, "name": "Payroll readers"}])
        self.assertEqual(response.data["permissions"], [])

    def test_another_employee_cannot_read_those_roles(self):
        other = make_user("access_other", password=PASSWORD)
        make_employee(
            company=self.company,
            email="other-access@test.horilla",
            first_name="Omar",
            user=other,
        )
        self.client.force_authenticate(user=other)
        response = self.client.get(access_url(self.employee.id))
        self.assertEqual(response.status_code, 403, response.content)

    def test_view_employee_can_read_roles(self):
        viewer = make_user("access_viewer", password=PASSWORD)
        viewer.user_permissions.add(self.view_employee)
        make_employee(
            company=self.company,
            email="viewer-access@test.horilla",
            first_name="Vera",
            user=viewer,
        )
        self.client.force_authenticate(user=viewer)
        response = self.client.get(access_url(self.employee.id))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["roles"][0]["name"], "Payroll readers")
        self.assertEqual(response.data["permissions"], [])

    def test_only_a_superuser_can_change_direct_permissions(self):
        self.client.force_authenticate(user=self.user)
        denied = self.client.put(
            access_url(self.employee.id),
            {"permissions": []},
            format="json",
        )
        self.assertEqual(denied.status_code, 403, denied.content)

        admin = make_user("access_admin", password=PASSWORD, is_superuser=True)
        self.client.force_authenticate(user=admin)
        allowed = self.client.put(
            access_url(self.employee.id),
            {"permissions": ["auth.view_group"]},
            format="json",
        )
        self.assertEqual(allowed.status_code, 200, allowed.content)
        self.assertIn("auth.view_group", allowed.data["permissions"])
        self.assertEqual(allowed.data["roles"][0]["name"], "Payroll readers")
