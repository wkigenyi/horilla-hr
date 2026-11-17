"""Roles admin uses auth.*_group via has_perm — not is_superuser."""

from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from rest_framework.test import APIClient

from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

PASSWORD = "secret123"
ROLES_URL = "/api/v1/base/roles/"


def _grant(user, *codenames):
    for codename in codenames:
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="auth", codename=codename)
        )
    return type(user).objects.get(pk=user.pk)


class RolesApiTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.client = APIClient()
        self.company = make_company("Roles Co")
        self.view_employee = Permission.objects.get(codename="view_employee")
        self.view_group_perm = Permission.objects.get(
            content_type__app_label="auth", codename="view_group"
        )

    def _user(self, username, *auth_codenames):
        user = make_user(username, password=PASSWORD)
        make_employee(
            company=self.company,
            email=f"{username}@test.horilla",
            user=user,
        )
        if auth_codenames:
            user = _grant(user, *auth_codenames)
        self.client.force_authenticate(user=user)
        return user

    def test_view_group_can_list_roles(self):
        self._user("roles_viewer", "view_group")
        response = self.client.get(ROLES_URL)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("roles", response.data)
        self.assertIn("catalog", response.data)

    def test_without_view_group_list_is_forbidden(self):
        self._user("roles_plain")
        response = self.client.get(ROLES_URL)
        self.assertEqual(response.status_code, 403, response.content)

    def test_add_group_can_create_role(self):
        self._user("roles_adder", "add_group")
        response = self.client.post(ROLES_URL, {"name": "Safety leads"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["name"], "Safety leads")

        self._user("roles_no_add")
        denied = self.client.post(ROLES_URL, {"name": "Nope"}, format="json")
        self.assertEqual(denied.status_code, 403, denied.content)

    def test_change_group_can_patch_and_manage_members(self):
        group = Group.objects.create(name="Ops")
        member_user = make_user("roles_member", password=PASSWORD)
        member = make_employee(
            company=self.company,
            email="roles_member@test.horilla",
            user=member_user,
        )
        editor = self._user("roles_editor", "change_group", "view_group")
        # Editor holds view_employee so catalog-related work is fine; grant the
        # permission they will assign onto the role.
        editor.user_permissions.add(self.view_employee, self.view_group_perm)
        editor = type(editor).objects.get(pk=editor.pk)
        self.client.force_authenticate(user=editor)

        patched = self.client.patch(
            f"{ROLES_URL}{group.id}/",
            {"name": "Ops Desk", "permissions": ["employee.view_employee"]},
            format="json",
        )
        self.assertEqual(patched.status_code, 200, patched.content)
        self.assertEqual(patched.data["name"], "Ops Desk")
        self.assertIn("employee.view_employee", patched.data["permissions"])

        added = self.client.post(
            f"{ROLES_URL}{group.id}/members/",
            {"employee_id": member.id},
            format="json",
        )
        self.assertEqual(added.status_code, 200, added.content)
        self.assertEqual(len(added.data["members"]), 1)

        people = self.client.get(f"{ROLES_URL}people/?q=roles_member")
        self.assertEqual(people.status_code, 200, people.content)

        removed = self.client.delete(f"{ROLES_URL}{group.id}/members/{member.id}/")
        self.assertEqual(removed.status_code, 200, removed.content)
        self.assertEqual(removed.data["members"], [])

        self._user("roles_no_change")
        denied = self.client.patch(
            f"{ROLES_URL}{group.id}/",
            {"name": "Blocked"},
            format="json",
        )
        self.assertEqual(denied.status_code, 403, denied.content)

    def test_delete_group_can_delete(self):
        group = Group.objects.create(name="Temp role")
        self._user("roles_deleter", "delete_group")
        response = self.client.delete(f"{ROLES_URL}{group.id}/")
        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(Group.objects.filter(pk=group.id).exists())

        group2 = Group.objects.create(name="Temp role 2")
        self._user("roles_no_delete")
        denied = self.client.delete(f"{ROLES_URL}{group2.id}/")
        self.assertEqual(denied.status_code, 403, denied.content)

    def test_cannot_escalate_role_permissions(self):
        group = Group.objects.create(name="Limited")
        editor = self._user("roles_escalator", "change_group")
        editor.user_permissions.add(self.view_group_perm)
        editor = type(editor).objects.get(pk=editor.pk)
        self.client.force_authenticate(user=editor)
        response = self.client.patch(
            f"{ROLES_URL}{group.id}/",
            {"permissions": ["auth.add_group"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("permissions", response.data)
