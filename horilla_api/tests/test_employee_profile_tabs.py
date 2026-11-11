"""
Read-only JSON for the Note, Mail Log, History, and Work Type & Shift
profile tabs. Visibility matches employee.cbv.accessibility; HTML stays
the write UI.
"""

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from base.models import EmailLog, WorkType, WorkTypeRequest
from employee.models import EmployeeNote
from horilla.horilla_middlewares import set_selected_company
from horilla.testkit import make_company, make_employee, make_user

PASSWORD = "secret123"


def notes_url(employee_id):
    return f"/api/v1/employee/employees/{employee_id}/notes/"


def mail_url(employee_id):
    return f"/api/v1/employee/employees/{employee_id}/mail-log/"


def history_url(employee_id):
    return f"/api/v1/employee/employees/{employee_id}/history/"


def work_shift_url(employee_id):
    return f"/api/v1/employee/employees/{employee_id}/work-shift/"


class EmployeeProfileTabsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        set_selected_company(None)
        self.company = make_company("Tabs Co")

        self.viewer = make_user("tabs_viewer", password=PASSWORD)
        self.viewer_emp = make_employee(
            company=self.company,
            email="tabs-viewer@test.horilla",
            first_name="Vera",
            user=self.viewer,
        )
        self.target_user = make_user("tabs_target", password=PASSWORD)
        self.target = make_employee(
            company=self.company,
            email="tabs-target@test.horilla",
            first_name="Tess",
            user=self.target_user,
        )
        self.stranger = make_user("tabs_stranger", password=PASSWORD)
        make_employee(
            company=self.company,
            email="tabs-stranger@test.horilla",
            first_name="Sid",
            user=self.stranger,
        )

    def _grant(self, user, *codenames):
        for codename in codenames:
            user.user_permissions.add(Permission.objects.get(codename=codename))
        return type(user).objects.get(pk=user.pk)

    def test_notes_list_for_permission_holder(self):
        self.viewer = self._grant(self.viewer, "view_employeenote")
        note = EmployeeNote.objects.create(
            employee_id=self.target,
            description="Check probation",
            updated_by=self.viewer_emp,
        )
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(notes_url(self.target.id))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["id"], note.id)
        self.assertEqual(row["description"], "Check probation")
        self.assertEqual(row["updated_by"]["id"], self.viewer_emp.id)
        self.assertIn("note_files", row)
        self.assertIsNotNone(row["created_at"])

    def test_notes_forbidden_for_self_without_superuser(self):
        self.target_user = self._grant(self.target_user, "view_employeenote")
        EmployeeNote.objects.create(
            employee_id=self.target,
            description="Own note",
            updated_by=self.target,
        )
        self.client.force_authenticate(user=self.target_user)
        response = self.client.get(notes_url(self.target.id))
        self.assertEqual(response.status_code, 403, response.content)

    def test_notes_not_found(self):
        self.viewer = self._grant(self.viewer, "view_employeenote")
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(notes_url(99999999))
        self.assertEqual(response.status_code, 404, response.content)

    def test_mail_log_for_self(self):
        EmailLog.objects.create(
            subject="Welcome",
            body="Hi",
            from_email="hr@test.horilla",
            to=self.target.email,
            status="sent",
            company_id=self.company,
        )
        self.client.force_authenticate(user=self.target_user)
        response = self.client.get(mail_url(self.target.id))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["subject"], "Welcome")
        self.assertEqual(row["status"], "sent")
        self.assertIsNotNone(row["created_at"])

    def test_mail_log_forbidden_for_stranger(self):
        self.client.force_authenticate(user=self.stranger)
        response = self.client.get(mail_url(self.target.id))
        self.assertEqual(response.status_code, 403, response.content)

    def test_history_for_permission_holder(self):
        self.viewer = self._grant(
            self.viewer, "view_historicalemployeeworkinformation"
        )
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(history_url(self.target.id))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("count", response.data)
        self.assertIn("results", response.data)
        self.assertEqual(response.data.get("model"), "employee.employeeworkinformation")

    def test_history_forbidden_for_stranger(self):
        self.client.force_authenticate(user=self.stranger)
        response = self.client.get(history_url(self.target.id))
        self.assertEqual(response.status_code, 403, response.content)

    def test_work_shift_for_self_includes_work_type_request(self):
        work_type = WorkType.objects.create(work_type="Remote")
        WorkTypeRequest.objects.create(
            employee_id=self.target,
            work_type_id=work_type,
            requested_date=timezone.localdate(),
            description="WFH week",
        )
        self.client.force_authenticate(user=self.target_user)
        response = self.client.get(work_shift_url(self.target.id))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["kind"], "work_type_request")
        self.assertEqual(row["work_type"], "Remote")
        self.assertEqual(row["description"], "WFH week")
        self.assertIsNotNone(row["requested_date"])

    def test_work_shift_forbidden_for_stranger(self):
        self.client.force_authenticate(user=self.stranger)
        response = self.client.get(work_shift_url(self.target.id))
        self.assertEqual(response.status_code, 403, response.content)
