"""
Assigning a company to several employees from the directory.

Pins who may do it, that each record is saved rather than queryset-updated,
that a person with no work-info record still gets one, and that a scoped user
cannot move people into a company outside their scope.
"""

from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from base.models import CompanyGroupAssignment
from employee.models import EmployeeWorkInformation
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

URL = "/api/v1/employee/employees/bulk-company/"


class EmployeeBulkCompanyTests(TestCase):
    def setUp(self):
        set_selected_company(None)
        self.home = make_company("Home Co")
        self.other = make_company("Other Co", hq=False)

        self.user = make_user("bulk_company_hr")
        self.hr = make_employee(
            company=self.home, email="hr@test.horilla", first_name="Hana", user=self.user
        )
        self.user.user_permissions.add(
            Permission.objects.get(codename="change_employee", content_type__app_label="employee")
        )

        self.unassigned = make_employee(
            company=self.home, email="none@test.horilla", first_name="Nadia"
        )
        self.unassigned.employee_work_info.company_id = None
        self.unassigned.employee_work_info.save()

        self.placed = make_employee(
            company=self.home, email="placed@test.horilla", first_name="Paul"
        )

        self.client = self._client(self.user)

    def tearDown(self):
        set_selected_company(None)

    def _client(self, user):
        client = APIClient()
        # A fresh instance so the permission cache is rebuilt.
        client.force_authenticate(user=type(user).objects.get(pk=user.pk))
        return client

    def _grant_other_company(self):
        """A role in Other Co, so a scoped HR user may move people there."""
        group = Group.objects.create(name="Bulk company HR")
        CompanyGroupAssignment.objects.create(user=self.user, company=self.other, group=group)
        self.client = self._client(self.user)

    def _company_of(self, employee):
        return EmployeeWorkInformation.objects.get(employee_id=employee).company_id_id

    def test_assigns_the_company_and_reports_what_changed(self):
        response = self.client.post(
            URL,
            {"ids": [self.unassigned.pk, self.placed.pk], "company_id": self.home.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["updated"], 1)
        self.assertEqual(response.data["unchanged"], 1)
        self.assertEqual(response.data["problems"], [])
        self.assertEqual(response.data["company"], "Home Co")
        self.assertEqual(self._company_of(self.unassigned), self.home.pk)

    def test_moves_people_to_another_company(self):
        self._grant_other_company()
        response = self.client.post(
            URL, {"ids": [self.placed.pk], "company_id": self.other.pk}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["updated"], 1)
        self.assertEqual(self._company_of(self.placed), self.other.pk)

    def test_creates_work_info_for_someone_without_it(self):
        self._grant_other_company()
        EmployeeWorkInformation.objects.filter(employee_id=self.unassigned).delete()
        response = self.client.post(
            URL, {"ids": [self.unassigned.pk], "company_id": self.other.pk}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["updated"], 1)
        self.assertEqual(self._company_of(self.unassigned), self.other.pk)

    def test_unknown_ids_are_named_and_the_rest_still_save(self):
        response = self.client.post(
            URL, {"ids": [self.unassigned.pk, 987654], "company_id": self.home.pk}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["updated"], 1)
        self.assertEqual(len(response.data["problems"]), 1)
        self.assertIn("987654", response.data["problems"][0])

    def test_needs_change_employee(self):
        plain = make_user("bulk_company_plain")
        make_employee(company=self.home, email="plain@test.horilla", user=plain)
        response = self._client(plain).post(
            URL, {"ids": [self.unassigned.pk], "company_id": self.home.pk}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self._company_of(self.unassigned))

    def test_rejects_a_missing_company_and_an_empty_selection(self):
        no_company = self.client.post(
            URL, {"ids": [self.unassigned.pk], "company_id": 987654}, format="json"
        )
        self.assertEqual(no_company.status_code, 400)
        no_ids = self.client.post(URL, {"ids": [], "company_id": self.home.pk}, format="json")
        self.assertEqual(no_ids.status_code, 400)

    @override_settings(COMPANY_SCOPED_PERMISSIONS=True)
    def test_scoped_user_cannot_assign_a_company_outside_their_scope(self):
        response = self.client.post(
            URL, {"ids": [self.unassigned.pk], "company_id": self.other.pk}, format="json"
        )
        self.assertEqual(response.status_code, 403, response.content)
        self.assertIsNone(self._company_of(self.unassigned))

    @override_settings(COMPANY_SCOPED_PERMISSIONS=True)
    def test_scoped_user_can_assign_their_own_company(self):
        response = self.client.post(
            URL, {"ids": [self.unassigned.pk], "company_id": self.home.pk}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self._company_of(self.unassigned), self.home.pk)
