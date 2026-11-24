"""Employee roles are readable by self / view_employee; direct perms use auth.*_permission."""

from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from base.models import CompanyGroupAssignment
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
        self.view_permission = Permission.objects.get(
            content_type__app_label="auth", codename="view_permission"
        )
        self.change_permission = Permission.objects.get(
            content_type__app_label="auth", codename="change_permission"
        )
        self.view_group = Permission.objects.get(
            content_type__app_label="auth", codename="view_group"
        )

    def test_employee_sees_their_own_roles_and_not_the_permission_list(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(access_url(self.employee.id))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.data["roles"],
            [{"id": self.role.id, "name": "Payroll readers", "companies": []}],
        )
        self.assertEqual(response.data["permissions"], [])

    def test_roles_name_the_companies_they_apply_in(self):
        other_company = make_company("Access Branch")
        for company in (self.company, other_company):
            CompanyGroupAssignment.objects.create(
                user=self.user, group=self.role, company=company
            )
        unassigned = Group.objects.create(name="Unassigned role")
        self.user.groups.add(unassigned)
        self.client.force_authenticate(user=self.user)
        with override_settings(COMPANY_SCOPED_PERMISSIONS=True):
            response = self.client.get(access_url(self.employee.id))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data["company_scoped"])
        self.assertEqual(response.data["company"], "Access Co")
        roles = {role["name"]: role["companies"] for role in response.data["roles"]}
        self.assertEqual(roles["Payroll readers"], ["Access Branch", "Access Co"])
        self.assertEqual(roles["Unassigned role"], [])

    def test_roles_carry_no_company_when_scoping_is_off(self):
        CompanyGroupAssignment.objects.create(
            user=self.user, group=self.role, company=self.company
        )
        self.client.force_authenticate(user=self.user)
        with override_settings(COMPANY_SCOPED_PERMISSIONS=False):
            response = self.client.get(access_url(self.employee.id))
        self.assertFalse(response.data["company_scoped"])
        self.assertEqual(response.data["roles"][0]["companies"], [])

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

    def test_view_permission_returns_direct_permission_ids(self):
        self.user.user_permissions.add(self.view_group)
        reader = make_user("access_perm_reader", password=PASSWORD)
        reader.user_permissions.add(self.view_employee, self.view_permission)
        make_employee(
            company=self.company,
            email="perm-reader@test.horilla",
            first_name="Pam",
            user=reader,
        )
        self.client.force_authenticate(user=reader)
        response = self.client.get(access_url(self.employee.id))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("auth.view_group", response.data["permissions"])

    def test_change_permission_can_put_direct_permissions(self):
        self.client.force_authenticate(user=self.user)
        denied = self.client.put(
            access_url(self.employee.id),
            {"permissions": []},
            format="json",
        )
        self.assertEqual(denied.status_code, 403, denied.content)

        editor = make_user("access_perm_editor", password=PASSWORD)
        editor.user_permissions.add(
            self.view_employee, self.change_permission, self.view_group
        )
        make_employee(
            company=self.company,
            email="perm-editor@test.horilla",
            first_name="Edd",
            user=editor,
        )
        # Reload so has_perm sees grants (permission cache).
        editor = type(editor).objects.get(pk=editor.pk)
        self.client.force_authenticate(user=editor)
        allowed = self.client.put(
            access_url(self.employee.id),
            {"permissions": ["auth.view_group"]},
            format="json",
        )
        self.assertEqual(allowed.status_code, 200, allowed.content)
        self.assertIn("auth.view_group", allowed.data["permissions"])
        self.assertEqual(allowed.data["roles"][0]["name"], "Payroll readers")

        escalate = self.client.put(
            access_url(self.employee.id),
            {"permissions": ["auth.add_group"]},
            format="json",
        )
        self.assertEqual(escalate.status_code, 400, escalate.content)
