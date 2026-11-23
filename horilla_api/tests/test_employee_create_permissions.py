"""Adding an employee as a non-superuser, the way the new UI does it.

The UI offered "Add employee" to holders of change_employee while the API
required add_employee, the work step needed a second permission nobody
thought to grant, and bank details had no create route at all.
"""

from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from employee.models import EmployeeBankDetails
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

EMPLOYEES = "/api/v1/employee/employees/"
WORK = "/api/v1/employee/employee-work-information/"
BANK = "/api/v1/employee/employee-bank-details/"


class EmployeeCreatePermissionTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.company = make_company("Hiring Co")
        self.client = APIClient()

    def _login(self, username, *codenames):
        user = make_user(username, password="secret123")
        make_employee(
            company=self.company,
            email=f"{username}@test.horilla",
            user=user,
            first_name=username,
        )
        for codename in codenames:
            user.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label="employee", codename=codename
                )
            )
        self.client.force_authenticate(user=type(user).objects.get(pk=user.pk))
        return user

    def _create(self, tag):
        return self.client.post(
            EMPLOYEES,
            {
                "employee_first_name": "New",
                "employee_last_name": tag,
                "email": f"new.{tag}@test.horilla",
                "is_active": True,
            },
            format="json",
        )

    def _capabilities(self):
        home = self.client.get("/api/v1/mobile/home/")
        self.assertEqual(home.status_code, 200, home.content)
        return home.data["capabilities"]["permissions"]

    def test_add_employee_is_its_own_capability(self):
        self._login("hire_adder", "add_employee", "view_employee")
        permissions = self._capabilities()
        self.assertTrue(permissions["add_employee"])
        self.assertFalse(permissions["edit_employee"])

    def test_change_employee_alone_cannot_create(self):
        self._login("hire_editor", "change_employee", "view_employee")
        self.assertFalse(self._capabilities()["add_employee"])
        self.assertIn(self._create("editor").status_code, (401, 403))

    def test_add_employee_covers_the_work_step(self):
        self._login("hire_work", "add_employee", "view_employee")
        created = self._create("work")
        self.assertEqual(created.status_code, 201, created.content)
        work_id = created.data["employee_work_info_id"]

        read = self.client.get(f"{WORK}{work_id}/")
        self.assertEqual(read.status_code, 200, read.content)
        saved = self.client.put(
            f"{WORK}{work_id}/",
            {
                "employee_id": created.data["id"],
                "company_id": self.company.id,
                "location": "Head office",
            },
            format="json",
        )
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.data["location"], "Head office")

    def test_change_employee_covers_the_work_step(self):
        self._login("hire_setup", "add_employee", "view_employee")
        created = self._create("changed")
        work_id = created.data["employee_work_info_id"]
        self._login("hire_changer", "change_employee", "view_employee")
        saved = self.client.put(
            f"{WORK}{work_id}/", {"location": "Depot"}, format="json"
        )
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.data["location"], "Depot")

    def test_no_employee_permission_cannot_touch_work_information(self):
        self._login("hire_setup2", "add_employee", "view_employee")
        created = self._create("locked")
        work_id = created.data["employee_work_info_id"]
        self._login("hire_nobody")
        saved = self.client.put(
            f"{WORK}{work_id}/", {"location": "Mine now"}, format="json"
        )
        self.assertEqual(saved.status_code, 403, saved.content)
        read = self.client.get(f"{WORK}{work_id}/")
        self.assertNotEqual(read.status_code, 200)

    def test_bank_details_can_be_created(self):
        self._login(
            "hire_bank", "add_employee", "view_employee", "add_employeebankdetails"
        )
        created = self._create("bank")
        body = {
            "employee_id": created.data["id"],
            "bank_name": "Stanbic",
            "account_number": "0012345",
        }
        saved = self.client.post(BANK, body, format="json")
        self.assertEqual(saved.status_code, 201, saved.content)
        self.assertTrue(
            EmployeeBankDetails.objects.filter(
                employee_id=created.data["id"], account_number="0012345"
            ).exists()
        )
        # The create route creates and nothing else.
        self.assertEqual(self.client.get(BANK).status_code, 405)

    def test_bank_details_still_need_their_own_permission(self):
        self._login("hire_nobank", "add_employee", "view_employee")
        created = self._create("nobank")
        refused = self.client.post(
            BANK,
            {
                "employee_id": created.data["id"],
                "bank_name": "Stanbic",
                "account_number": "0099999",
            },
            format="json",
        )
        self.assertEqual(refused.status_code, 403, refused.content)
